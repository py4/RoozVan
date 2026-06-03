"""Cloudflare R2 object storage utilities."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openrouter_client import load_default_env_files


class R2StorageError(RuntimeError):
    """Raised when Cloudflare R2 operations fail."""


@dataclass(frozen=True)
class R2UploadedObject:
    bucket_name: str
    key: str
    public_url: str

    def to_dict(self) -> dict[str, str]:
        return {
            "bucket_name": self.bucket_name,
            "key": self.key,
            "public_url": self.public_url,
        }


@dataclass
class R2Storage:
    """Small Cloudflare R2 client using the S3-compatible API.

    Env vars:
    - R2_ACCESS_KEY_ID
    - R2_SECRET_ACCESS_KEY
    - R2_TOKEN_VALUE: Cloudflare API token, used for account/bucket/public URL management
    - R2_ACCOUNT_ID: optional; auto-discovered from R2_TOKEN_VALUE if omitted
    - R2_BUCKET_NAME: optional; defaults to roozvan-story-images
    - R2_PUBLIC_BASE_URL: optional custom public URL; otherwise r2.dev managed URL is used
    """

    access_key_id: str | None = None
    secret_access_key: str | None = None
    cloudflare_api_token: str | None = None
    account_id: str | None = None
    bucket_name: str | None = None
    public_base_url: str | None = None
    timeout: int = 60
    create_bucket_if_missing: bool = True
    enable_public_dev_url: bool = True

    def __post_init__(self) -> None:
        load_default_env_files()
        self.access_key_id = self.access_key_id or os.getenv("R2_ACCESS_KEY_ID")
        self.secret_access_key = self.secret_access_key or os.getenv("R2_SECRET_ACCESS_KEY")
        self.cloudflare_api_token = self.cloudflare_api_token or os.getenv("R2_TOKEN_VALUE")
        self.account_id = self.account_id or os.getenv("R2_ACCOUNT_ID")
        self.bucket_name = self.bucket_name or os.getenv("R2_BUCKET_NAME") or "roozvan-story-images"
        self.public_base_url = self.public_base_url or os.getenv("R2_PUBLIC_BASE_URL")

        if not self.access_key_id:
            raise R2StorageError("Missing R2_ACCESS_KEY_ID.")
        if not self.secret_access_key:
            raise R2StorageError("Missing R2_SECRET_ACCESS_KEY.")
        if not self.cloudflare_api_token and (not self.account_id or not self.public_base_url):
            raise R2StorageError(
                "Missing R2_TOKEN_VALUE. It is required to auto-discover R2_ACCOUNT_ID "
                "and the public r2.dev URL."
            )
        if not self.account_id:
            self.account_id = self.discover_account_id()

    @property
    def s3_endpoint(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    def ensure_bucket(self) -> None:
        buckets = self.list_buckets()
        if self.bucket_name in buckets:
            return
        if not self.create_bucket_if_missing:
            raise R2StorageError(f"R2 bucket does not exist: {self.bucket_name}")
        self.create_bucket(self.bucket_name)

    def upload_file(
        self,
        local_path: str | Path,
        *,
        key: str | None = None,
        content_type: str | None = None,
    ) -> R2UploadedObject:
        path = Path(local_path)
        if not path.exists():
            raise R2StorageError(f"Local file does not exist: {path}")
        if not path.is_file():
            raise R2StorageError(f"Local path is not a file: {path}")

        self.ensure_bucket()
        key = key or path.name
        content_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self._s3_request("PUT", key, body=body, content_type=content_type)
        return R2UploadedObject(
            bucket_name=self.bucket_name or "",
            key=key,
            public_url=self.public_url_for_key(key),
        )

    def delete_object(self, key: str) -> None:
        self._s3_request("DELETE", key)

    def public_url_for_key(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{urllib.parse.quote(key)}"

        managed = self.get_managed_public_domain()
        if not managed.get("enabled"):
            if not self.enable_public_dev_url:
                raise R2StorageError(f"Public r2.dev URL is disabled for bucket: {self.bucket_name}")
            managed = self.set_managed_public_domain(enabled=True)

        domain = managed.get("domain")
        if not isinstance(domain, str) or not domain:
            raise R2StorageError(f"Cloudflare did not return a managed public domain: {managed}")
        return f"https://{domain.rstrip('/')}/{urllib.parse.quote(key)}"

    def discover_account_id(self) -> str:
        response = self._cloudflare_request("GET", "/accounts")
        accounts = response.get("result")
        if not isinstance(accounts, list) or not accounts:
            raise R2StorageError(f"Cloudflare token cannot discover an account: {response}")
        account_id = accounts[0].get("id")
        if not isinstance(account_id, str) or not account_id:
            raise R2StorageError(f"Cloudflare account id missing from response: {response}")
        return account_id

    def list_buckets(self) -> set[str]:
        response = self._cloudflare_request("GET", f"/accounts/{self.account_id}/r2/buckets")
        result = response.get("result")
        bucket_items = result.get("buckets") if isinstance(result, dict) else result
        if not isinstance(bucket_items, list):
            raise R2StorageError(f"Unexpected Cloudflare bucket response: {response}")
        return {item["name"] for item in bucket_items if isinstance(item, dict) and isinstance(item.get("name"), str)}

    def create_bucket(self, bucket_name: str) -> None:
        self._cloudflare_request(
            "POST",
            f"/accounts/{self.account_id}/r2/buckets",
            json_body={"name": bucket_name, "storage_class": "Standard"},
        )

    def get_managed_public_domain(self) -> dict[str, Any]:
        response = self._cloudflare_request(
            "GET",
            f"/accounts/{self.account_id}/r2/buckets/{self.bucket_name}/domains/managed",
        )
        result = response.get("result")
        if not isinstance(result, dict):
            raise R2StorageError(f"Unexpected Cloudflare managed domain response: {response}")
        return result

    def set_managed_public_domain(self, *, enabled: bool) -> dict[str, Any]:
        response = self._cloudflare_request(
            "PUT",
            f"/accounts/{self.account_id}/r2/buckets/{self.bucket_name}/domains/managed",
            json_body={"enabled": enabled},
        )
        result = response.get("result")
        if not isinstance(result, dict):
            raise R2StorageError(f"Unexpected Cloudflare managed domain response: {response}")
        return result

    def _cloudflare_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.cloudflare_api_token:
            raise R2StorageError("Cloudflare API token is required for this operation.")
        data = None
        headers = {"Authorization": f"Bearer {self.cloudflare_api_token}"}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"https://api.cloudflare.com/client/v4{path}",
            data=data,
            headers=headers,
            method=method,
        )
        return self._json_urlopen(request, service_name="Cloudflare")

    def _s3_request(
        self,
        method: str,
        key: str,
        *,
        body: bytes = b"",
        content_type: str | None = None,
    ) -> bytes:
        quoted_key = urllib.parse.quote(key, safe="/")
        path = f"/{self.bucket_name}/{quoted_key}"
        url = f"{self.s3_endpoint}{path}"
        headers = self._signed_s3_headers(method, path, body, content_type=content_type)
        request = urllib.request.Request(url, data=body if method != "GET" else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise R2StorageError(f"R2 S3 HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise R2StorageError(f"Failed to call R2 S3 API: {exc}") from exc

    def _signed_s3_headers(
        self,
        method: str,
        canonical_uri: str,
        body: bytes,
        *,
        content_type: str | None = None,
    ) -> dict[str, str]:
        now = dt.datetime.now(dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()
        host = f"{self.account_id}.r2.cloudflarestorage.com"
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if content_type:
            headers["content-type"] = content_type

        signed_header_names = sorted(headers)
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in signed_header_names)
        signed_headers = ";".join(signed_header_names)
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/auto/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = self._aws_signature_key(date_stamp)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key_id}/{credential_scope},"
            f"SignedHeaders={signed_headers},"
            f"Signature={signature}"
        )
        return {
            "Authorization": authorization,
            "Content-Type": content_type or "application/octet-stream",
            "Host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }

    def _aws_signature_key(self, date_stamp: str) -> bytes:
        key_date = _hmac_sha256(("AWS4" + (self.secret_access_key or "")).encode("utf-8"), date_stamp)
        key_region = _hmac_sha256(key_date, "auto")
        key_service = _hmac_sha256(key_region, "s3")
        return _hmac_sha256(key_service, "aws4_request")

    def _json_urlopen(self, request: urllib.request.Request, *, service_name: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw_response = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise R2StorageError(f"{service_name} HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise R2StorageError(f"Failed to call {service_name}: {exc}") from exc

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise R2StorageError(f"{service_name} returned invalid JSON: {raw_response}") from exc
        if not isinstance(parsed, dict):
            raise R2StorageError(f"{service_name} returned unexpected JSON: {parsed!r}")
        if parsed.get("success") is False:
            raise R2StorageError(f"{service_name} error: {parsed}")
        return parsed


def _hmac_sha256(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

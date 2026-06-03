"""Instagram publishing helpers for RoozVan."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openrouter_client import load_default_env_files
from roozvan.r2_storage import R2Storage


class InstagramPublishError(RuntimeError):
    """Raised when Instagram Graph API publishing fails."""


@dataclass(frozen=True)
class InstagramPublishResult:
    creation_id: str
    media_id: str
    image_url: str | None = None
    temporary_object_key: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "creation_id": self.creation_id,
            "media_id": self.media_id,
            "image_url": self.image_url,
            "temporary_object_key": self.temporary_object_key,
        }


@dataclass
class InstagramPublisher:
    """Publish image posts to an Instagram professional account.

    Required env vars, if not passed explicitly:
    - INSTAGRAM_ACCESS_TOKEN
    - INSTAGRAM_USER_ID

    Instagram Graph API requires `image_url` to be publicly reachable. Local
    paths are only supported when `public_base_url` maps them to public URLs.
    """

    access_token: str | None = None
    instagram_user_id: str | None = None
    graph_api_version: str = "v24.0"
    graph_api_base_url: str = "https://graph.instagram.com"
    timeout: int = 60
    publish_attempts: int = 10
    publish_retry_delay_seconds: int = 5
    public_base_url: str | None = None
    public_base_path: Path = Path(".")

    def __post_init__(self) -> None:
        load_default_env_files()
        self.access_token = self.access_token or os.getenv("IG_ACCESS_TOKEN") or os.getenv("INSTAGRAM_ACCESS_TOKEN")
        self.instagram_user_id = self.instagram_user_id or os.getenv("IG_USER_ID") or os.getenv("INSTAGRAM_USER_ID")
        self.graph_api_version = os.getenv("INSTAGRAM_GRAPH_API_VERSION", self.graph_api_version)
        self.graph_api_base_url = os.getenv("INSTAGRAM_GRAPH_API_BASE_URL", self.graph_api_base_url)
        self.public_base_url = self.public_base_url or os.getenv("INSTAGRAM_PUBLIC_BASE_URL")
        public_base_path = os.getenv("INSTAGRAM_PUBLIC_BASE_PATH")
        if public_base_path:
            self.public_base_path = Path(public_base_path)

        if not self.access_token:
            raise InstagramPublishError("Missing IG_ACCESS_TOKEN or INSTAGRAM_ACCESS_TOKEN.")
        if not self.instagram_user_id:
            raise InstagramPublishError("Missing IG_USER_ID or INSTAGRAM_USER_ID.")

    def publish_image_post(
        self,
        *,
        caption: str,
        image_url: str | None = None,
        image_path: str | Path | None = None,
    ) -> InstagramPublishResult:
        """Create and publish a single-image Instagram feed post."""
        public_image_url = image_url or self.public_url_for_path(image_path)
        creation_id = self.create_photo_container(public_image_url, caption)
        media_id = self.publish_container(creation_id)
        return InstagramPublishResult(creation_id=creation_id, media_id=media_id, image_url=public_image_url)

    def publish_image_story(
        self,
        *,
        image_url: str | None = None,
        image_path: str | Path | None = None,
    ) -> InstagramPublishResult:
        """Create and publish a single-image Instagram Story."""
        public_image_url = image_url or self.public_url_for_path(image_path)
        creation_id = self.create_story_container(public_image_url)
        media_id = self.publish_container(creation_id)
        return InstagramPublishResult(creation_id=creation_id, media_id=media_id, image_url=public_image_url)

    def publish_local_image_post_with_r2(
        self,
        *,
        image_path: str | Path,
        caption: str,
        object_key: str | None = None,
        delete_after_publish: bool = True,
        r2_storage: R2Storage | None = None,
    ) -> InstagramPublishResult:
        """Upload a local image to R2 temporarily, publish it to Instagram, then optionally delete it."""
        storage = r2_storage or R2Storage(timeout=self.timeout)
        uploaded = storage.upload_file(image_path, key=object_key)
        try:
            result = self.publish_image_post(caption=caption, image_url=uploaded.public_url)
            return InstagramPublishResult(
                creation_id=result.creation_id,
                media_id=result.media_id,
                image_url=uploaded.public_url,
                temporary_object_key=uploaded.key,
            )
        finally:
            if delete_after_publish:
                storage.delete_object(uploaded.key)

    def publish_local_image_story_with_r2(
        self,
        *,
        image_path: str | Path,
        object_key: str | None = None,
        delete_after_publish: bool = True,
        r2_storage: R2Storage | None = None,
    ) -> InstagramPublishResult:
        """Upload a local image to R2 temporarily, publish it as a Story, then optionally delete it."""
        storage = r2_storage or R2Storage(timeout=self.timeout)
        uploaded = storage.upload_file(image_path, key=object_key)
        try:
            result = self.publish_image_story(image_url=uploaded.public_url)
            return InstagramPublishResult(
                creation_id=result.creation_id,
                media_id=result.media_id,
                image_url=uploaded.public_url,
                temporary_object_key=uploaded.key,
            )
        finally:
            if delete_after_publish:
                storage.delete_object(uploaded.key)

    def create_photo_container(self, image_url: str, caption: str) -> str:
        response = self._post(
            f"{self.instagram_user_id}/media",
            {
                "image_url": image_url,
                "caption": caption,
                "access_token": self.access_token,
            },
        )
        creation_id = response.get("id")
        if not isinstance(creation_id, str) or not creation_id:
            raise InstagramPublishError(f"Instagram did not return a creation id: {response}")
        return creation_id

    def create_story_container(self, image_url: str) -> str:
        response = self._post(
            f"{self.instagram_user_id}/media",
            {
                "image_url": image_url,
                "media_type": "STORIES",
                "access_token": self.access_token,
            },
        )
        creation_id = response.get("id")
        if not isinstance(creation_id, str) or not creation_id:
            raise InstagramPublishError(f"Instagram did not return a story creation id: {response}")
        return creation_id

    def publish_container(self, creation_id: str) -> str:
        response = None
        for attempt in range(1, self.publish_attempts + 1):
            try:
                response = self._post(
                    f"{self.instagram_user_id}/media_publish",
                    {
                        "creation_id": creation_id,
                        "access_token": self.access_token,
                    },
                )
                break
            except InstagramPublishError as exc:
                if attempt >= self.publish_attempts or "Media ID is not available" not in str(exc):
                    raise
                time.sleep(self.publish_retry_delay_seconds)
        media_id = response.get("id")
        if not isinstance(media_id, str) or not media_id:
            raise InstagramPublishError(f"Instagram did not return a media id: {response}")
        return media_id

    def public_url_for_path(self, image_path: str | Path | None) -> str:
        if image_path is None:
            raise InstagramPublishError("Pass image_url, or image_path with INSTAGRAM_PUBLIC_BASE_URL configured.")
        if not self.public_base_url:
            raise InstagramPublishError(
                "Instagram Graph API requires a public image_url. Set INSTAGRAM_PUBLIC_BASE_URL "
                "to map local image_path values to public URLs."
            )

        path = Path(image_path)
        if not path.exists():
            raise InstagramPublishError(f"Image path does not exist: {path}")
        try:
            relative_path = path.resolve().relative_to(self.public_base_path.resolve())
        except ValueError as exc:
            raise InstagramPublishError(
                f"Image path must be inside INSTAGRAM_PUBLIC_BASE_PATH: {self.public_base_path}"
            ) from exc
        quoted_path = urllib.parse.quote(relative_path.as_posix())
        return f"{self.public_base_url.rstrip('/')}/{quoted_path}"

    def _post(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self.graph_api_base_url.rstrip('/')}/{self.graph_api_version}/{endpoint.lstrip('/')}"
        data = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw_response = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise InstagramPublishError(f"Instagram HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise InstagramPublishError(f"Failed to call Instagram: {exc}") from exc

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise InstagramPublishError(f"Instagram returned invalid JSON: {raw_response}") from exc
        if not isinstance(parsed, dict):
            raise InstagramPublishError(f"Instagram returned unexpected JSON: {parsed!r}")
        if "error" in parsed:
            raise InstagramPublishError(f"Instagram error: {parsed['error']}")
        return parsed


def publish_image_to_instagram(
    *,
    caption: str,
    image_url: str | None = None,
    image_path: str | Path | None = None,
    access_token: str | None = None,
    instagram_user_id: str | None = None,
    public_base_url: str | None = None,
    public_base_path: str | Path = ".",
    graph_api_version: str = "v24.0",
    graph_api_base_url: str = "https://graph.instagram.com",
    timeout: int = 60,
) -> InstagramPublishResult:
    """Publish a single image and caption to an Instagram creator/business account."""
    publisher = InstagramPublisher(
        access_token=access_token,
        instagram_user_id=instagram_user_id,
        public_base_url=public_base_url,
        public_base_path=Path(public_base_path),
        graph_api_version=graph_api_version,
        graph_api_base_url=graph_api_base_url,
        timeout=timeout,
    )
    return publisher.publish_image_post(caption=caption, image_url=image_url, image_path=image_path)


def publish_local_image_to_instagram_with_r2(
    *,
    image_path: str | Path,
    caption: str,
    object_key: str | None = None,
    delete_after_publish: bool = True,
    access_token: str | None = None,
    instagram_user_id: str | None = None,
    graph_api_version: str = "v24.0",
    graph_api_base_url: str = "https://graph.instagram.com",
    timeout: int = 60,
) -> InstagramPublishResult:
    """Temporarily upload a local image to R2, publish it to Instagram, and delete the object."""
    publisher = InstagramPublisher(
        access_token=access_token,
        instagram_user_id=instagram_user_id,
        graph_api_version=graph_api_version,
        graph_api_base_url=graph_api_base_url,
        timeout=timeout,
    )
    return publisher.publish_local_image_post_with_r2(
        image_path=image_path,
        caption=caption,
        object_key=object_key,
        delete_after_publish=delete_after_publish,
    )


def publish_story_image_to_instagram(
    *,
    image_url: str | None = None,
    image_path: str | Path | None = None,
    access_token: str | None = None,
    instagram_user_id: str | None = None,
    public_base_url: str | None = None,
    public_base_path: str | Path = ".",
    graph_api_version: str = "v24.0",
    graph_api_base_url: str = "https://graph.instagram.com",
    timeout: int = 60,
) -> InstagramPublishResult:
    """Publish a single image as an Instagram Story."""
    publisher = InstagramPublisher(
        access_token=access_token,
        instagram_user_id=instagram_user_id,
        public_base_url=public_base_url,
        public_base_path=Path(public_base_path),
        graph_api_version=graph_api_version,
        graph_api_base_url=graph_api_base_url,
        timeout=timeout,
    )
    return publisher.publish_image_story(image_url=image_url, image_path=image_path)


def publish_local_story_image_to_instagram_with_r2(
    *,
    image_path: str | Path,
    object_key: str | None = None,
    delete_after_publish: bool = True,
    access_token: str | None = None,
    instagram_user_id: str | None = None,
    graph_api_version: str = "v24.0",
    graph_api_base_url: str = "https://graph.instagram.com",
    timeout: int = 60,
) -> InstagramPublishResult:
    """Temporarily upload a local image to R2, publish it as a Story, and delete the object."""
    publisher = InstagramPublisher(
        access_token=access_token,
        instagram_user_id=instagram_user_id,
        graph_api_version=graph_api_version,
        graph_api_base_url=graph_api_base_url,
        timeout=timeout,
    )
    return publisher.publish_local_image_story_with_r2(
        image_path=image_path,
        object_key=object_key,
        delete_after_publish=delete_after_publish,
    )

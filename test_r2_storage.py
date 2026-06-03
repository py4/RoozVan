#!/usr/bin/env python3
"""Upload/fetch/delete smoke test for Cloudflare R2."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from roozvan.r2_storage import R2Storage


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Cloudflare R2 upload, public fetch, and delete.")
    parser.add_argument("image_path", help="Local image file to upload for the smoke test.")
    parser.add_argument("--key", default=None, help="Optional R2 object key.")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds.")
    args = parser.parse_args()

    local_path = Path(args.image_path)
    key = args.key or f"smoke-tests/{int(time.time())}-{local_path.name}"

    storage = R2Storage(timeout=args.timeout)
    uploaded = storage.upload_file(local_path, key=key)
    public_status = wait_for_status(uploaded.public_url, expected=200, timeout=args.timeout, attempts=6)
    if public_status != 200:
        storage.delete_object(uploaded.key)
        raise SystemExit(f"Expected public URL to return 200, got {public_status}: {uploaded.public_url}")

    storage.delete_object(uploaded.key)
    deleted_status = wait_for_not_status(uploaded.public_url, unexpected=200, timeout=args.timeout, attempts=6)
    if deleted_status == 200:
        raise SystemExit(f"Expected deleted public URL to stop returning 200: {uploaded.public_url}")

    print(
        json.dumps(
            {
                **uploaded.to_dict(),
                "public_fetch_status": public_status,
                "after_delete_fetch_status": deleted_status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def fetch_status(url: str, *, timeout: int) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": "RoozVan-R2-Smoke-Test/1.0"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(1)
            return response.status
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code


def wait_for_status(url: str, *, expected: int, timeout: int, attempts: int) -> int:
    status = 0
    for _ in range(attempts):
        status = fetch_status(url, timeout=timeout)
        if status == expected:
            return status
        time.sleep(2)
    return status


def wait_for_not_status(url: str, *, unexpected: int, timeout: int, attempts: int) -> int:
    status = unexpected
    for _ in range(attempts):
        status = fetch_status(url, timeout=timeout)
        if status != unexpected:
            return status
        time.sleep(2)
    return status


if __name__ == "__main__":
    raise SystemExit(main())

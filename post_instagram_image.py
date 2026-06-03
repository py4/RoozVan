#!/usr/bin/env python3
"""Publish an image post to the configured Instagram creator account."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from roozvan.instagram import publish_image_to_instagram, publish_local_image_to_instagram_with_r2


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish an image and caption to Instagram.")
    image_group = parser.add_mutually_exclusive_group(required=True)
    image_group.add_argument("--image-url", help="Publicly reachable image URL.")
    image_group.add_argument("--image-path", help="Local image path mapped by INSTAGRAM_PUBLIC_BASE_URL.")
    caption_group = parser.add_mutually_exclusive_group(required=True)
    caption_group.add_argument("--caption", help="Instagram caption text.")
    caption_group.add_argument("--caption-file", help="Path to a UTF-8 caption text file.")
    parser.add_argument("--public-base-url", help="Public URL prefix for --image-path.")
    parser.add_argument("--public-base-path", default=".", help="Local base path that maps to --public-base-url.")
    parser.add_argument(
        "--upload-r2",
        action="store_true",
        help="Temporarily upload --image-path to Cloudflare R2, publish, then delete the R2 object.",
    )
    parser.add_argument("--r2-key", help="Optional R2 object key when --upload-r2 is used.")
    parser.add_argument(
        "--keep-r2-object",
        action="store_true",
        help="Do not delete the temporary R2 object after publishing.",
    )
    parser.add_argument("--timeout", type=int, default=60, help="Instagram Graph API timeout in seconds.")
    args = parser.parse_args()

    caption = args.caption
    if args.caption_file:
        caption = Path(args.caption_file).read_text(encoding="utf-8").strip()

    if args.upload_r2:
        if not args.image_path:
            parser.error("--upload-r2 requires --image-path")
        result = publish_local_image_to_instagram_with_r2(
            image_path=args.image_path,
            caption=caption or "",
            object_key=args.r2_key,
            delete_after_publish=not args.keep_r2_object,
            timeout=args.timeout,
        )
    else:
        result = publish_image_to_instagram(
            image_url=args.image_url,
            image_path=args.image_path,
            caption=caption or "",
            public_base_url=args.public_base_url,
            public_base_path=args.public_base_path,
            timeout=args.timeout,
        )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

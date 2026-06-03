#!/usr/bin/env python3
"""Publish an image post to the configured Instagram creator account."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from roozvan.instagram import publish_image_to_instagram


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
    parser.add_argument("--timeout", type=int, default=60, help="Instagram Graph API timeout in seconds.")
    args = parser.parse_args()

    caption = args.caption
    if args.caption_file:
        caption = Path(args.caption_file).read_text(encoding="utf-8").strip()

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

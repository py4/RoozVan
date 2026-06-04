#!/usr/bin/env python3
"""Publish an image post to the configured Instagram creator account."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from roozvan.instagram import (
    publish_image_to_instagram,
    publish_local_carousel_to_instagram_with_r2,
    publish_local_image_to_instagram_with_r2,
    publish_local_story_image_to_instagram_with_r2,
    publish_story_image_to_instagram,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish an image and caption to Instagram.")
    image_group = parser.add_mutually_exclusive_group()
    image_group.add_argument("--image-url", help="Publicly reachable image URL.")
    image_group.add_argument("--image-path", help="Local image path mapped by INSTAGRAM_PUBLIC_BASE_URL.")
    caption_group = parser.add_mutually_exclusive_group()
    caption_group.add_argument("--caption", help="Instagram caption text.")
    caption_group.add_argument("--caption-file", help="Path to a UTF-8 caption text file.")
    parser.add_argument("--story", action="store_true", help="Publish image as an Instagram Story instead of a feed post.")
    parser.add_argument(
        "--carousel",
        action="store_true",
        help="Publish multiple images as an Instagram carousel feed post (requires --image-paths).",
    )
    parser.add_argument(
        "--image-paths",
        nargs="+",
        help="Local image paths for a carousel post, in order.",
    )
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
    if args.carousel and args.story:
        parser.error("--carousel cannot be combined with --story")
    if args.carousel and not args.image_paths:
        parser.error("--carousel requires --image-paths")
    if args.image_paths and not args.carousel:
        parser.error("--image-paths requires --carousel")
    if not args.story and not args.carousel and caption is None:
        parser.error("feed publishing requires --caption or --caption-file")
    if args.carousel and caption is None:
        parser.error("carousel publishing requires --caption or --caption-file")
    if not args.carousel and not args.image_url and not args.image_path:
        parser.error("requires --image-url or --image-path (or use --carousel with --image-paths)")

    if args.carousel:
        if not args.upload_r2:
            parser.error("carousel publishing currently requires --upload-r2")
        result = publish_local_carousel_to_instagram_with_r2(
            image_paths=args.image_paths,
            caption=caption or "",
            key_prefix=args.r2_key,
            delete_after_publish=not args.keep_r2_object,
            timeout=args.timeout,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.upload_r2:
        if not args.image_path:
            parser.error("--upload-r2 requires --image-path")
        if args.story:
            result = publish_local_story_image_to_instagram_with_r2(
                image_path=args.image_path,
                object_key=args.r2_key,
                delete_after_publish=not args.keep_r2_object,
                timeout=args.timeout,
            )
        else:
            result = publish_local_image_to_instagram_with_r2(
                image_path=args.image_path,
                caption=caption or "",
                object_key=args.r2_key,
                delete_after_publish=not args.keep_r2_object,
                timeout=args.timeout,
            )
    else:
        if args.story:
            result = publish_story_image_to_instagram(
                image_url=args.image_url,
                image_path=args.image_path,
                public_base_url=args.public_base_url,
                public_base_path=args.public_base_path,
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

#!/usr/bin/env python3
"""Generate images for items already selected in a pipeline dump (after HTML review)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from openrouter_client import OpenRouterClient, load_default_env_files
from roozvan.models import ScoredItem
from roozvan.post_content import generate_post_images_for_scored_items
from roozvan.story_images import (
    DEFAULT_GEMINI_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_PROVIDER,
    generate_story_images_for_scored_items,
)
from run_pipeline import write_html_report, write_json


def load_selected_items(dump_dir: Path) -> list[ScoredItem]:
    selected_path = dump_dir / "selected.json"
    if not selected_path.exists():
        raise FileNotFoundError(f"Missing {selected_path}; run the pipeline first.")
    data = json.loads(selected_path.read_text(encoding="utf-8"))
    return [ScoredItem.from_dict(item) for item in data]


def save_selected_items(dump_dir: Path, items: list[ScoredItem]) -> None:
    write_json(dump_dir / "selected.json", [item.to_dict() for item in items])
    drafts_path = dump_dir / "post_drafts.json"
    if drafts_path.exists():
        drafts = json.loads(drafts_path.read_text(encoding="utf-8"))
        by_index = {item.source_index: item for item in items}
        for draft in drafts:
            scored = draft.get("scored_item", draft)
            source_index = scored.get("source_index")
            if source_index in by_index:
                if "scored_item" in draft:
                    draft["scored_item"] = by_index[source_index].to_dict()
                else:
                    draft.update(by_index[source_index].to_dict())
        write_json(drafts_path, drafts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate post/carousel/story images for items in a pipeline dump.",
    )
    parser.add_argument(
        "--dump-dir",
        default="runs/live-debug",
        help="Pipeline dump directory containing selected.json.",
    )
    parser.add_argument("--timeout", type=int, default=60, help="OpenRouter timeout in seconds.")
    parser.add_argument(
        "--story-image-timeout",
        type=int,
        default=300,
        help="Image API timeout in seconds.",
    )
    parser.add_argument("--workers", type=int, default=4, help="Parallel image workers.")
    parser.add_argument(
        "--story-image-provider",
        choices=("openrouter", "gemini"),
        default=DEFAULT_STORY_IMAGE_PROVIDER,
        help="Image provider for generated assets (default: OpenRouter).",
    )
    parser.add_argument(
        "--story-image-model",
        default=DEFAULT_STORY_IMAGE_MODEL,
        help="OpenRouter image model when provider is openrouter.",
    )
    parser.add_argument(
        "--gemini-story-image-model",
        default=DEFAULT_GEMINI_STORY_IMAGE_MODEL,
        help="Gemini image model when provider is gemini.",
    )
    parser.add_argument(
        "--post-image-output-dir",
        default="generated_post_images",
        help="Directory for post and carousel images.",
    )
    parser.add_argument(
        "--story-image-output-dir",
        default="generated_story_images",
        help="Directory for story images.",
    )
    parser.add_argument(
        "--logo-path",
        default="assets/logo.png",
        help="Logo overlay path.",
    )
    parser.add_argument(
        "--skip-logo-overlay",
        action="store_true",
        help="Skip applying the RoozVan logo overlay.",
    )
    parser.add_argument(
        "--only-source-index",
        type=int,
        action="append",
        dest="only_source_indexes",
        help="Generate images only for the given source_index (repeatable).",
    )
    args = parser.parse_args()

    load_default_env_files()
    dump_dir = Path(args.dump_dir)
    all_items = load_selected_items(dump_dir)
    items_to_process = all_items
    if args.only_source_indexes:
        allowed = set(args.only_source_indexes)
        items_to_process = [item for item in all_items if item.source_index in allowed]

    post_items = [
        item
        for item in items_to_process
        if item.format_selected in {"post", "carousel_post"}
    ]
    story_items = [item for item in items_to_process if item.format_selected == "story"]

    image_model = (
        args.gemini_story_image_model
        if args.story_image_provider == "gemini"
        else args.story_image_model
    )
    image_client = OpenRouterClient(
        model=image_model,
        timeout=args.story_image_timeout,
        app_name="RoozVan",
    )

    started_at = time.perf_counter()
    updated_by_index = {item.source_index: item for item in all_items}

    if post_items:
        image_prompt_template = Path("prompts/post_image_generation.md").read_text(encoding="utf-8")
        carousel_image_prompt_template = Path("prompts/carousel_image_background_generation.md").read_text(
            encoding="utf-8"
        )
        generated_posts = generate_post_images_for_scored_items(
            post_items,
            image_prompt_template=image_prompt_template,
            carousel_image_prompt_template=carousel_image_prompt_template,
            image_client=image_client,
            output_dir=Path(args.post_image_output_dir),
            image_model=image_model,
            image_provider=args.story_image_provider,
            workers=args.workers,
            apply_logo_overlay_enabled=not args.skip_logo_overlay,
            logo_path=Path(args.logo_path),
        )
        for item in generated_posts:
            updated_by_index[item.source_index] = item

    if story_items:
        story_prompt_template = Path("prompts/story_image_generation.md").read_text(encoding="utf-8")
        generated_stories = generate_story_images_for_scored_items(
            story_items,
            story_prompt_template,
            image_client,
            output_dir=Path(args.story_image_output_dir),
            model=image_model,
            provider=args.story_image_provider,
            workers=args.workers,
            apply_logo_overlay_enabled=not args.skip_logo_overlay,
            logo_path=Path(args.logo_path),
        )
        for item in generated_stories:
            updated_by_index[item.source_index] = item

    updated_items = [updated_by_index[item.source_index] for item in all_items]
    save_selected_items(dump_dir, updated_items)
    write_html_report(dump_dir / "index.html", updated_items)

    elapsed = time.perf_counter() - started_at
    print(f"Updated {dump_dir / 'selected.json'} and {dump_dir / 'index.html'} in {elapsed:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

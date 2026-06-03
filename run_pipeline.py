#!/usr/bin/env python3
"""Run the RoozVan editorial pipeline and print selected post candidates."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from roozvan.pipeline import PipelineConfig, build_default_pipeline
from roozvan.story_images import DEFAULT_GEMINI_STORY_IMAGE_MODEL, DEFAULT_STORY_IMAGE_MODEL


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RoozVan sources -> select pipeline.")
    parser.add_argument("--sources", default="sources.txt", help="File containing RSS/Atom URLs or paths, one per line.")
    parser.add_argument("--prompt", default="scoring_prompt.md", help="Editorial scoring prompt file.")
    parser.add_argument(
        "--format-instruction",
        default="format_selection_instruction.md",
        help="Instagram format selection instruction file.",
    )
    parser.add_argument(
        "--story-image-prompt",
        default="prompts/story_image_generation.md",
        help="Story image generation prompt file.",
    )
    parser.add_argument("--model", default="openrouter/owl-alpha", help="OpenRouter model name.")
    parser.add_argument(
        "--story-image-model",
        default=DEFAULT_STORY_IMAGE_MODEL,
        help="OpenRouter image generation model name.",
    )
    parser.add_argument(
        "--story-image-provider",
        choices=("openrouter", "gemini"),
        default="gemini",
        help="Provider for story image generation.",
    )
    parser.add_argument(
        "--gemini-story-image-model",
        default=DEFAULT_GEMINI_STORY_IMAGE_MODEL,
        help="Direct Gemini API image generation model name.",
    )
    parser.add_argument("--timeout", type=int, default=60, help="Network and OpenRouter timeout in seconds.")
    parser.add_argument(
        "--story-image-timeout",
        type=int,
        default=300,
        help="OpenRouter timeout in seconds for story image generation.",
    )
    parser.add_argument("--max-items", type=int, default=None, help="Optional limit for scoring only the first N RSS items.")
    parser.add_argument("--max-tokens", type=int, default=600, help="Maximum output tokens for each LLM response.")
    parser.add_argument(
        "--format-max-tokens",
        type=int,
        default=80,
        help="Maximum output tokens for each format selection LLM response.",
    )
    parser.add_argument(
        "--story-image-max-tokens",
        type=int,
        default=12000,
        help="Maximum output tokens for each story image generation response.",
    )
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel OpenRouter scoring requests.")
    parser.add_argument("--selection-limit", type=int, default=5, help="Maximum candidates to select.")
    parser.add_argument("--minimum-score", type=float, default=12, help="Minimum overall score for selected candidates.")
    parser.add_argument("--post-only", action="store_true", help="Exclude maybe decisions from selected candidates.")
    parser.add_argument(
        "--skip-story-images",
        action="store_true",
        help="Skip story image generation after article ranking and selection.",
    )
    parser.add_argument(
        "--story-image-output-dir",
        default="generated_story_images",
        help="Directory where generated story images will be saved.",
    )
    parser.add_argument(
        "--dump-dir",
        default=None,
        help="Optional directory for full pipeline debug dumps.",
    )
    parser.add_argument("--json", action="store_true", help="Print selected candidates as JSON.")
    args = parser.parse_args()

    config = PipelineConfig(
        sources_path=Path(args.sources),
        scoring_prompt_path=Path(args.prompt),
        format_selection_instruction_path=Path(args.format_instruction),
        story_image_prompt_path=Path(args.story_image_prompt),
        model=args.model,
        story_image_model=args.story_image_model,
        gemini_story_image_model=args.gemini_story_image_model,
        story_image_provider=args.story_image_provider,
        timeout=args.timeout,
        story_image_timeout=args.story_image_timeout,
        max_items=args.max_items,
        max_tokens=args.max_tokens,
        format_selection_max_tokens=args.format_max_tokens,
        story_image_max_tokens=args.story_image_max_tokens,
        workers=args.workers,
        selection_limit=args.selection_limit,
        minimum_score=args.minimum_score,
        include_maybe=not args.post_only,
        generate_story_images=not args.skip_story_images,
        story_image_output_dir=Path(args.story_image_output_dir),
    )
    started_at = time.perf_counter()
    result = build_default_pipeline().run(config)
    total_elapsed = time.perf_counter() - started_at
    if args.dump_dir:
        write_debug_dump(Path(args.dump_dir), result, config, total_elapsed)

    if args.json:
        print(json.dumps(result.selected_as_dicts(), ensure_ascii=False, indent=2))
        print_timing_summary(result.stage_timings, total_elapsed, file=sys.stderr)
        return 0

    print(f"Extracted: {len(result.items)}")
    print(f"Scored: {len(result.scored_items)}")
    print(f"Deduped: {len(result.deduped_items)}")
    print(f"Selected: {len(result.selected_items)}")
    print(f"Selected readable without JS: {sum(1 for item in result.selected_items if item.item.article_readable_without_js)}")
    print()
    for index, item in enumerate(result.selected_items, start=1):
        evaluation = item.evaluation
        news = item.item
        print(
            f"{index}. [{item.overall_score}] {evaluation.get('post_decision')} / "
            f"{evaluation.get('recommended_format')} / format_selected={item.format_selected}"
        )
        print(f"   {news.title}")
        print(f"   {evaluation.get('persian_angle')}")
        print(f"   readable_without_js={news.article_readable_without_js}")
        print(f"   story_image_path={news.story_image_path}")
        print(f"   {news.url}")
        print()
    print_timing_summary(result.stage_timings, total_elapsed)
    return 0


def write_debug_dump(dump_dir: Path, result, config: PipelineConfig, total_elapsed: float) -> None:
    dump_dir.mkdir(parents=True, exist_ok=True)
    write_json(dump_dir / "extracted.json", [item.to_dict() for item in result.items])
    write_json(dump_dir / "scored.json", [item.to_dict() for item in result.scored_items])
    write_json(dump_dir / "ranked.json", [item.to_dict() for item in result.ranked_items])
    write_json(dump_dir / "deduped.json", [item.to_dict() for item in result.deduped_items])
    write_json(dump_dir / "selected.json", [item.to_dict() for item in result.selected_items])
    write_json(dump_dir / "post_drafts.json", [draft.to_dict() for draft in result.post_drafts])
    write_json(
        dump_dir / "timing.json",
        {
            "stages": [
                {"name": stage_name, "seconds": round(elapsed, 3)}
                for stage_name, elapsed in result.stage_timings
            ],
            "total_seconds": round(total_elapsed, 3),
        },
    )
    write_json(
        dump_dir / "config.json",
        {
            "sources_path": str(config.sources_path),
            "scoring_prompt_path": str(config.scoring_prompt_path),
            "format_selection_instruction_path": str(config.format_selection_instruction_path),
            "story_image_prompt_path": str(config.story_image_prompt_path),
            "model": config.model,
            "story_image_model": config.story_image_model,
            "gemini_story_image_model": config.gemini_story_image_model,
            "story_image_provider": config.story_image_provider,
            "timeout": config.timeout,
            "story_image_timeout": config.story_image_timeout,
            "max_items": config.max_items,
            "max_tokens": config.max_tokens,
            "format_selection_max_tokens": config.format_selection_max_tokens,
            "story_image_max_tokens": config.story_image_max_tokens,
            "workers": config.workers,
            "selection_limit": config.selection_limit,
            "minimum_score": config.minimum_score,
            "include_maybe": config.include_maybe,
            "generate_story_images": config.generate_story_images,
            "story_image_output_dir": str(config.story_image_output_dir),
        },
    )
    print(f"Debug dump written to {dump_dir}", file=sys.stderr)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def print_timing_summary(stage_timings: list[tuple[str, float]], total_elapsed: float, *, file=sys.stdout) -> None:
    print("Timing:", file=file)
    for stage_name, elapsed in stage_timings:
        print(f"  {stage_name}: {format_duration(elapsed)}", file=file)
    print(f"  total: {format_duration(total_elapsed)}", file=file)


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes}m {remaining_seconds:.1f}s"


if __name__ == "__main__":
    raise SystemExit(main())

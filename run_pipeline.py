#!/usr/bin/env python3
"""Run the RoozVan editorial pipeline and print selected post candidates."""

from __future__ import annotations

import argparse
import html
import json
import os
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
    parser.add_argument(
        "--post-image-prompt",
        default="prompts/post_image_generation.md",
        help="Post image generation prompt file.",
    )
    parser.add_argument(
        "--post-caption-prompt",
        default="prompts/post_caption_generation.md",
        help="Post caption generation prompt file.",
    )
    parser.add_argument(
        "--carousel-content-prompt",
        default="prompts/carousel_content_generation.md",
        help="Carousel slide plan and caption generation prompt file.",
    )
    parser.add_argument(
        "--carousel-image-prompt",
        default="prompts/carousel_image_generation.md",
        help="Carousel slide image generation prompt file.",
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
    parser.add_argument(
        "--post-caption-max-tokens",
        type=int,
        default=900,
        help="Maximum output tokens for each post caption generation response.",
    )
    parser.add_argument(
        "--post-image-max-tokens",
        type=int,
        default=12000,
        help="Maximum output tokens for each post image generation response.",
    )
    parser.add_argument("--workers", type=int, default=16, help="Number of parallel OpenRouter scoring requests.")
    parser.add_argument("--selection-limit", type=int, default=5, help="Maximum candidates to select.")
    parser.add_argument("--minimum-score", type=float, default=12, help="Minimum overall score for selected candidates.")
    parser.add_argument(
        "--skip-story-images",
        action="store_true",
        help="Skip story image generation after article ranking and selection.",
    )
    parser.add_argument(
        "--skip-post-content",
        action="store_true",
        help="Skip post image and caption generation after format selection.",
    )
    parser.add_argument(
        "--story-image-output-dir",
        default="generated_story_images",
        help="Directory where generated story images will be saved.",
    )
    parser.add_argument(
        "--post-image-output-dir",
        default="generated_post_images",
        help="Directory where generated post images will be saved.",
    )
    parser.add_argument(
        "--logo-path",
        default="assets/logo.png",
        help="Logo image applied to the bottom-left of generated story and post images.",
    )
    parser.add_argument(
        "--skip-logo-overlay",
        action="store_true",
        help="Skip applying the RoozVan logo to generated images.",
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
        post_image_prompt_path=Path(args.post_image_prompt),
        post_caption_prompt_path=Path(args.post_caption_prompt),
        carousel_content_prompt_path=Path(args.carousel_content_prompt),
        carousel_image_prompt_path=Path(args.carousel_image_prompt),
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
        post_caption_max_tokens=args.post_caption_max_tokens,
        post_image_max_tokens=args.post_image_max_tokens,
        workers=args.workers,
        selection_limit=args.selection_limit,
        minimum_score=args.minimum_score,
        generate_story_images=not args.skip_story_images,
        generate_post_content=not args.skip_post_content,
        story_image_output_dir=Path(args.story_image_output_dir),
        post_image_output_dir=Path(args.post_image_output_dir),
        logo_path=Path(args.logo_path),
        apply_logo_overlay=not args.skip_logo_overlay,
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
        print(f"{index}. [{item.overall_score}] format_selected={item.format_selected}")
        print(f"   {news.title}")
        print(f"   {evaluation.get('persian_angle')}")
        print(f"   readable_without_js={news.article_readable_without_js}")
        print(f"   story_image_path={news.story_image_path}")
        print(f"   post_image_path={news.post_image_path}")
        print(f"   carousel_image_paths={news.carousel_image_paths}")
        print(f"   post_caption_fa={news.post_caption_fa}")
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
            "post_image_prompt_path": str(config.post_image_prompt_path),
            "post_caption_prompt_path": str(config.post_caption_prompt_path),
            "carousel_content_prompt_path": str(config.carousel_content_prompt_path),
            "carousel_image_prompt_path": str(config.carousel_image_prompt_path),
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
            "post_caption_max_tokens": config.post_caption_max_tokens,
            "post_image_max_tokens": config.post_image_max_tokens,
            "workers": config.workers,
            "selection_limit": config.selection_limit,
            "minimum_score": config.minimum_score,
            "generate_story_images": config.generate_story_images,
            "generate_post_content": config.generate_post_content,
            "story_image_output_dir": str(config.story_image_output_dir),
            "post_image_output_dir": str(config.post_image_output_dir),
            "logo_path": str(config.logo_path),
            "apply_logo_overlay": config.apply_logo_overlay,
        },
    )
    write_html_report(dump_dir / "index.html", result.selected_items)
    print(f"Debug dump written to {dump_dir}", file=sys.stderr)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_html_report(path: Path, selected_items) -> None:
    rows = "\n".join(render_instagram_row(path.parent, item) for item in selected_items)
    if not rows:
        rows = '<div class="empty">No selected items.</div>'
    path.write_text(
        f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RoozVan Pipeline Preview</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f5f7;
      --panel: #ffffff;
      --text: #151515;
      --muted: #777;
      --line: #dedede;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Tahoma, Arial, sans-serif;
    }}
    .page {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1 {{
      margin: 0 0 20px;
      font-size: 22px;
      font-weight: 750;
      direction: ltr;
      text-align: left;
    }}
    .row {{
      display: grid;
      grid-template-columns: minmax(280px, 420px) 1fr;
      gap: 24px;
      align-items: start;
      padding: 22px 0;
      border-top: 1px solid var(--line);
    }}
    .row:first-of-type {{ border-top: 0; }}
    .phone {{
      width: min(100%, 420px);
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      direction: ltr;
      box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }}
    .ig-header {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      border-bottom: 1px solid #eee;
      font-size: 14px;
      font-weight: 700;
    }}
    .avatar {{
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: linear-gradient(135deg, #0e7490, #111827);
    }}
    .media {{
      display: block;
      width: 100%;
      background: #111;
      object-fit: cover;
    }}
    .post .media {{ aspect-ratio: 4 / 5; }}
    .carousel {{
      width: min(100%, 420px);
      direction: ltr;
    }}
    .carousel-track {{
      display: flex;
      gap: 12px;
      overflow-x: auto;
      scroll-snap-type: x mandatory;
      padding-bottom: 10px;
    }}
    .carousel-slide {{
      flex: 0 0 min(100%, 420px);
      scroll-snap-align: start;
    }}
    .carousel-slide .media {{ aspect-ratio: 4 / 5; }}
    .carousel-count {{
      direction: ltr;
      text-align: center;
      color: var(--muted);
      font-size: 12px;
      margin: 0 0 8px;
    }}
    .story {{
      max-width: 340px;
      border-radius: 22px;
      background: #111;
      padding: 10px;
    }}
    .story .media {{
      aspect-ratio: 9 / 16;
      border-radius: 16px;
    }}
    .ig-actions {{
      padding: 10px 12px 0;
      font-size: 22px;
      letter-spacing: 4px;
    }}
    .caption {{
      padding: 8px 12px 14px;
      direction: rtl;
      text-align: right;
      line-height: 1.75;
      white-space: pre-wrap;
      font-size: 14px;
    }}
    .meta {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      direction: rtl;
      text-align: right;
    }}
    .badge {{
      display: inline-block;
      direction: ltr;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 9px;
      margin-bottom: 10px;
      font-size: 12px;
      color: var(--muted);
      background: #fafafa;
    }}
    .title {{
      margin: 0 0 8px;
      font-size: 17px;
      line-height: 1.55;
      font-weight: 750;
    }}
    .angle {{
      margin: 0;
      color: #333;
      line-height: 1.8;
      font-size: 14px;
    }}
    .path {{
      margin-top: 12px;
      direction: ltr;
      text-align: left;
      color: var(--muted);
      font-size: 12px;
      word-break: break-all;
    }}
    .missing {{
      aspect-ratio: 4 / 5;
      display: grid;
      place-items: center;
      background: #111;
      color: #fff;
      padding: 24px;
      text-align: center;
    }}
    .empty {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px;
      direction: ltr;
    }}
    @media (max-width: 760px) {{
      .page {{ padding: 14px; }}
      .row {{ grid-template-columns: 1fr; }}
      .story {{ max-width: 100%; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <h1>RoozVan Pipeline Preview</h1>
    {rows}
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )


def render_instagram_row(dump_dir: Path, item) -> str:
    news = item.item
    selected_format = item.format_selected or "unknown"
    is_story = selected_format == "story"
    is_carousel = selected_format == "carousel_post"
    image_path = news.story_image_path if is_story else news.post_image_path
    image_paths = news.carousel_image_paths if is_carousel else None
    media = render_carousel_media(dump_dir, image_paths) if is_carousel else render_media(dump_dir, image_path)
    caption = html.escape(news.post_caption_fa or "")
    title = html.escape(news.title or "")
    angle = html.escape(str(item.evaluation.get("persian_angle") or ""))
    score = html.escape(str(item.overall_score))
    image_path_text = html.escape("\n".join(image_paths or []) if is_carousel else image_path or "")
    source_url = html.escape(news.source_url or "")
    article_url = html.escape(news.url or "")

    if is_story:
        preview = f'<div class="phone story">{media}</div>'
    elif is_carousel:
        preview = f"""
        <div class="carousel">
          <div class="carousel-count">{len(image_paths or [])} slides · scroll horizontally</div>
          <div class="carousel-track">{media}</div>
          <div class="phone post">
            <div class="ig-header"><div class="avatar"></div><div>roozvan.ca</div></div>
            <div class="ig-actions">♡ ◌ ↗</div>
            <div class="caption"><strong>roozvan.ca</strong> {caption}</div>
          </div>
        </div>
        """
    else:
        preview = f"""
        <div class="phone post">
          <div class="ig-header"><div class="avatar"></div><div>roozvan.ca</div></div>
          {media}
          <div class="ig-actions">♡ ◌ ↗</div>
          <div class="caption"><strong>roozvan.ca</strong> {caption}</div>
        </div>
        """

    return f"""
    <section class="row">
      {preview}
      <aside class="meta">
        <div class="badge">{html.escape(selected_format)} · score {score}</div>
        <h2 class="title">{title}</h2>
        <p class="angle">{angle}</p>
        <div class="path">rss_source: {source_url}</div>
        <div class="path">article: {article_url}</div>
        <div class="path">{image_path_text}</div>
      </aside>
    </section>
    """


def render_media(dump_dir: Path, image_path: str | None) -> str:
    if not image_path:
        return '<div class="missing">No image generated</div>'
    relative_path = html.escape(relative_asset_path(dump_dir, Path(image_path)))
    return f'<img class="media" src="{relative_path}" alt="">'


def render_carousel_media(dump_dir: Path, image_paths: list[str] | None) -> str:
    if not image_paths:
        return '<div class="phone post"><div class="missing">No carousel slides generated</div></div>'
    slides = []
    for index, image_path in enumerate(image_paths, start=1):
        slides.append(
            f"""
            <div class="phone post carousel-slide">
              <div class="ig-header"><div class="avatar"></div><div>roozvan.ca · {index}/{len(image_paths)}</div></div>
              {render_media(dump_dir, image_path)}
            </div>
            """
        )
    return "\n".join(slides)


def relative_asset_path(from_dir: Path, asset_path: Path) -> str:
    return os.path.relpath(asset_path, from_dir).replace(os.sep, "/")


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

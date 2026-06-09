#!/usr/bin/env python3
"""Run the RoozVan editorial pipeline and print selected post candidates."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from openrouter_client import DEFAULT_TEXT_MODEL
from roozvan.pipeline import PipelineConfig, build_default_pipeline
from roozvan.story_images import (
    DEFAULT_GEMINI_STORY_IMAGE_MODEL,
    DEFAULT_OPENROUTER_IMAGE_MAX_TOKENS,
    DEFAULT_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_PROVIDER,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RoozVan sources -> select pipeline.")
    parser.add_argument("--sources", default="sources.txt", help="File containing RSS/Atom URLs or paths, one per line.")
    parser.add_argument("--prompt", default="scoring_prompt.md", help="Editorial scoring prompt file.")
    parser.add_argument(
        "--instagram-content-prompt",
        default="prompts/instagram_content_generation.md",
        help="Unified Instagram format + caption/slide text generation prompt.",
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
        default="prompts/carousel_image_background_generation.md",
        help="Carousel slide image generation prompt file.",
    )
    parser.add_argument("--model", default=DEFAULT_TEXT_MODEL, help="OpenRouter model name.")
    parser.add_argument(
        "--story-image-model",
        default=DEFAULT_STORY_IMAGE_MODEL,
        help="OpenRouter image generation model name.",
    )
    parser.add_argument(
        "--story-image-provider",
        choices=("openrouter", "gemini"),
        default=DEFAULT_STORY_IMAGE_PROVIDER,
        help="Provider for story/post/carousel image generation (default: OpenRouter).",
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
    parser.add_argument("--selection-limit", type=int, default=20, help="Maximum candidates to select.")
    parser.add_argument("--minimum-score", type=float, default=12, help="Minimum overall score for selected candidates.")
    parser.add_argument(
        "--no-recency-boost",
        action="store_true",
        help="Disable extra ranking points for recently published RSS items.",
    )
    parser.add_argument(
        "--no-feel-good-boost",
        action="store_true",
        help="Disable extra ranking points for uplifting local community/lifestyle stories.",
    )
    parser.add_argument(
        "--generate-images",
        action="store_true",
        help="Generate post/carousel/story images during the pipeline (expensive; default is text-only for HTML review).",
    )
    parser.add_argument(
        "--generate-story-images",
        action="store_true",
        help="Generate story images (implies image generation for stories; use with --generate-images or alone).",
    )
    parser.add_argument(
        "--generate-carousel-content",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--skip-post-text",
        action="store_true",
        help="Skip post/carousel caption and slide text generation.",
    )
    parser.add_argument(
        "--skip-story-images",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--skip-post-content",
        action="store_true",
        help=argparse.SUPPRESS,
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
        default="runs/live-debug",
        help="Directory for full pipeline debug dumps.",
    )
    parser.add_argument("--json", action="store_true", help="Print selected candidates as JSON.")
    args = parser.parse_args()

    config = PipelineConfig(
        sources_path=Path(args.sources),
        scoring_prompt_path=Path(args.prompt),
        instagram_content_prompt_path=Path(args.instagram_content_prompt),
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
        story_image_max_tokens=args.story_image_max_tokens,
        post_caption_max_tokens=args.post_caption_max_tokens,
        post_image_max_tokens=args.post_image_max_tokens,
        workers=args.workers,
        selection_limit=args.selection_limit,
        minimum_score=args.minimum_score,
        recency_boost_enabled=not args.no_recency_boost,
        feel_good_boost_enabled=not args.no_feel_good_boost,
        generate_story_images=args.generate_story_images or args.generate_images,
        generate_post_content=not args.skip_post_text and not args.skip_post_content,
        generate_post_images=args.generate_images,
        story_image_output_dir=Path(args.story_image_output_dir),
        post_image_output_dir=Path(args.post_image_output_dir),
        logo_path=Path(args.logo_path),
        apply_logo_overlay=not args.skip_logo_overlay,
    )
    started_at = time.perf_counter()
    result = build_default_pipeline().run(config)
    total_elapsed = time.perf_counter() - started_at
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
            "instagram_content_prompt_path": str(config.instagram_content_prompt_path),
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
            "story_image_max_tokens": config.story_image_max_tokens,
            "post_caption_max_tokens": config.post_caption_max_tokens,
            "post_image_max_tokens": config.post_image_max_tokens,
            "workers": config.workers,
            "selection_limit": config.selection_limit,
            "minimum_score": config.minimum_score,
            "recency_boost_enabled": config.recency_boost_enabled,
            "feel_good_boost_enabled": config.feel_good_boost_enabled,
            "generate_story_images": config.generate_story_images,
            "generate_post_content": config.generate_post_content,
            "generate_post_images": config.generate_post_images,
            "story_image_output_dir": str(config.story_image_output_dir),
            "post_image_output_dir": str(config.post_image_output_dir),
            "logo_path": str(config.logo_path),
            "apply_logo_overlay": config.apply_logo_overlay,
        },
    )
    write_status_json(dump_dir, result, total_elapsed)
    write_html_report(dump_dir / "index.html", result.selected_items)
    print(f"Debug dump written to {dump_dir}", file=sys.stderr)
    if result.errors:
        print(f"Pipeline completed with {len(result.errors)} warning(s). See {dump_dir / 'status.json'}", file=sys.stderr)
    if not config.generate_post_images and not config.generate_story_images:
        print(
            "Images were not generated. Review index.html, then run:\n"
            f"  python3 generate_selected_images.py --dump-dir {dump_dir}",
            file=sys.stderr,
        )


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_status_json(dump_dir: Path, result, total_elapsed: float) -> None:
    write_json(
        dump_dir / "status.json",
        build_pipeline_status(result, total_elapsed),
    )


def build_pipeline_status(result, total_elapsed: float) -> dict:
    return {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "extracted_count": len(result.items),
        "scored_count": len(result.scored_items),
        "deduped_count": len(result.deduped_items),
        "selected_count": len(result.selected_items),
        "error_count": len(result.errors),
        "errors": result.errors[:50],
        "elapsed_seconds": round(total_elapsed, 3),
    }


def has_pipeline_run(status: dict | None) -> bool:
    return bool(status and status.get("completed_at"))


def embed_json_in_html(value) -> str:
    """Embed JSON in a script tag without breaking HTML or JSON.parse."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def load_pipeline_status(dump_dir: Path) -> dict | None:
    status_path = dump_dir / "status.json"
    if not status_path.exists():
        return None
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_html_report(path: Path, selected_items) -> None:
    dump_dir = path.parent
    rows = "\n".join(render_instagram_row(dump_dir, item) for item in selected_items)
    if not rows:
        rows = render_empty_state(dump_dir)
    status = load_pipeline_status(dump_dir) or {}
    status_json = embed_json_in_html(status)
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
    .slide-text-list {{
      margin-top: 14px;
      display: grid;
      gap: 10px;
    }}
    .slide-text {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 14px;
      line-height: 1.7;
    }}
    .slide-body {{
      color: #333;
      margin-top: 4px;
    }}
    .slide-badge {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    .empty {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px;
      direction: ltr;
      text-align: left;
      line-height: 1.6;
    }}
    .empty-actions {{
      margin-top: 14px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .error-list {{
      margin: 12px 0 0;
      padding-left: 18px;
      color: #912018;
      font-size: 13px;
    }}
    .error-list li {{ margin: 4px 0; }}
    .pipeline-stats {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 18px;
      padding: 14px 16px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      direction: ltr;
      text-align: left;
    }}
    .toolbar-note {{
      color: var(--muted);
      font-size: 13px;
      margin-left: auto;
    }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
      direction: ltr;
      text-align: left;
    }}
    .controls-group {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      width: 100%;
    }}
    .controls-label {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
      min-width: 52px;
    }}
    .btn {{
      appearance: none;
      border: 1px solid #c9c9c9;
      background: #fafafa;
      color: #222;
      border-radius: 6px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      line-height: 1.2;
    }}
    .btn:hover:not(:disabled) {{ background: #f0f0f0; }}
    .btn:disabled {{ opacity: 0.55; cursor: wait; }}
    .btn-primary {{
      background: #0e7490;
      border-color: #0e7490;
      color: #fff;
    }}
    .btn-primary:hover:not(:disabled) {{ background: #0b5f74; }}
    .btn-danger {{
      background: #b42318;
      border-color: #b42318;
      color: #fff;
    }}
    .btn-danger:hover:not(:disabled) {{ background: #912018; }}
    .status-banner {{
      display: none;
      margin-bottom: 14px;
      padding: 10px 14px;
      border-radius: 8px;
      direction: ltr;
      text-align: left;
      font-size: 13px;
    }}
    .status-banner.visible {{ display: block; }}
    .status-banner.ok {{ background: #ecfdf3; border: 1px solid #abefc6; color: #067647; }}
    .status-banner.error {{ background: #fef3f2; border: 1px solid #fecdca; color: #b42318; }}
    .status-banner.warn {{ background: #fffaeb; border: 1px solid #fedf89; color: #b54708; }}
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
    {render_control_toolbar()}
    <div id="status-banner" class="status-banner" role="status"></div>
    {rows}
  </main>
  <script id="pipeline-status" type="application/json">{status_json}</script>
  {control_panel_script()}
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
        slide_text = render_carousel_slide_text(item.evaluation.get("carousel_post"))
        carousel_note = render_carousel_review_note(item, caption, slide_text)
        preview = f"""
        <div class="carousel">
          <div class="carousel-count">{carousel_count_label(image_paths, item.evaluation.get("carousel_post"))}</div>
          <div class="carousel-track">{media}</div>
          {slide_text}
          {carousel_note}
          <div class="phone post">
            <div class="ig-header"><div class="avatar"></div><div>roozvan.ca</div></div>
            <div class="ig-actions">♡ ◌ ↗</div>
            <div class="caption"><strong>roozvan.ca</strong> {caption or '<em>Caption not generated yet</em>'}</div>
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
        {render_story_overlay_text(item) if is_story else ""}
        {render_row_controls(item)}
      </aside>
    </section>
    """


def render_story_overlay_text(item) -> str:
    caption = item.evaluation.get("post_caption")
    if not isinstance(caption, dict):
        return ""
    headline = html.escape(str(caption.get("image_headline_fa") or "")).replace("\n", " · ")
    subline = html.escape(str(caption.get("image_subline_fa") or "")).replace("\n", " · ")
    category = html.escape(str(caption.get("category_label_fa") or ""))
    if not headline and not subline:
        return '<div class="path">story overlay: not generated yet</div>'
    badge = f"[{category}] " if category else ""
    return (
        f'<div class="path">story overlay: {badge}{headline}'
        f'{(" — " + subline) if subline else ""}</div>'
    )


def render_media(dump_dir: Path, image_path: str | None) -> str:
    if not image_path:
        return '<div class="missing">Image not generated yet</div>'
    asset_path = Path(image_path)
    resolved = asset_path if asset_path.is_file() else Path.cwd() / asset_path
    relative_path = html.escape(relative_asset_path(dump_dir, asset_path))
    version = f"?v={int(resolved.stat().st_mtime)}" if resolved.is_file() else ""
    return f'<img class="media" src="{relative_path}{version}" alt="">'


def carousel_count_label(image_paths: list[str] | None, carousel_post: dict | None) -> str:
    if image_paths:
        return f"{len(image_paths)} slides · scroll horizontally"
    slides = (carousel_post or {}).get("slides") or []
    if slides:
        return f"{len(slides)} slides · text preview (images not generated yet)"
    return "carousel · text not generated yet"


def render_carousel_review_note(item, caption: str, slide_text: str) -> str:
    if caption or slide_text:
        return ""
    angle = html.escape(str(item.evaluation.get("persian_angle") or ""))
    return (
        '<div class="slide-text-list">'
        '<div class="slide-text"><strong>Review</strong>'
        "<div>Carousel caption/slides were not generated in this pipeline run.</div>"
        f'<div class="slide-body">{angle or "Re-run with text generation enabled, or regenerate text from the control panel."}</div>'
        "</div></div>"
    )


def render_carousel_slide_text(carousel_post: dict | None) -> str:
    slides = (carousel_post or {}).get("slides") or []
    if not slides:
        return ""
    blocks = []
    for index, slide in enumerate(slides, start=1):
        headline = html.escape(str(slide.get("headline_fa") or ""))
        body = html.escape(str(slide.get("body_fa") or ""))
        category = html.escape(str(slide.get("category_label_fa") or ""))
        badge = f'<span class="slide-badge">{category}</span> ' if category else ""
        blocks.append(
            f'<div class="slide-text"><strong>Slide {index}</strong> {badge}<div>{headline}</div><div class="slide-body">{body}</div></div>'
        )
    return f'<div class="slide-text-list">{"".join(blocks)}</div>'


def render_carousel_media(dump_dir: Path, image_paths: list[str] | None) -> str:
    if not image_paths:
        return '<div class="phone post"><div class="missing">Images not generated yet</div></div>'
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


def render_control_toolbar() -> str:
    return """
    <div class="toolbar">
      <button class="btn btn-primary" type="button" data-action="reingest">Reingest RSS</button>
      <span class="toolbar-note">Fetch feeds, score, and refresh preview (no images).</span>
    </div>
    """


def render_empty_state(dump_dir: Path) -> str:
    status = load_pipeline_status(dump_dir)
    stats_html = ""
    errors_html = ""
    if has_pipeline_run(status):
        stats_bits = []
        if status.get("extracted_count") is not None:
            stats_bits.append(f"extracted {status.get('extracted_count', 0)}")
        if status.get("scored_count") is not None:
            stats_bits.append(f"scored {status.get('scored_count', 0)}")
        if status.get("selected_count") is not None:
            stats_bits.append(f"selected {status.get('selected_count', 0)}")
        if stats_bits:
            stats_html = f'<div class="pipeline-stats">Last run: {html.escape(", ".join(stats_bits))}</div>'

        errors = status.get("errors") or []
        error_count = int(status.get("error_count") or len(errors))
        if errors:
            items = "".join(f"<li>{html.escape(str(error))}</li>" for error in errors[:8])
            more = ""
            if error_count > 8:
                more = f"<li>…and {error_count - 8} more (see status.json)</li>"
            errors_html = f"<ul class=\"error-list\">{items}{more}</ul>"

    return f"""
    <div class="empty">
      <strong>No selected items yet.</strong>
      <div>Use <strong>Reingest RSS</strong> above to fetch feeds and run the editorial pipeline.</div>
      {stats_html}
      {errors_html}
    </div>
    """


def render_row_controls(item) -> str:
    source_index = int(item.source_index)
    selected_format = item.format_selected or "unknown"
    groups: list[str] = []

    if selected_format in {"story", "post", "carousel_post"}:
        groups.append(
            _control_group(
                "Text",
                _button("↻ Regenerate text", "regenerate-text", source_index),
            )
        )

    if selected_format == "story":
        groups.append(
            _control_group(
                "Image",
                _button("↻ Story image", "regenerate-image", source_index),
            )
        )
    elif selected_format == "post":
        groups.append(
            _control_group(
                "Image",
                _button("↻ Post image", "regenerate-image", source_index),
            )
        )
    elif selected_format == "carousel_post":
        slides = (item.evaluation.get("carousel_post") or {}).get("slides") or []
        image_paths = item.item.carousel_image_paths or []
        slide_count = max(len(slides), len(image_paths))
        image_buttons = "".join(
            _button(
                f"↻ Slide {index} image",
                "regenerate-image",
                source_index,
                slide=index,
            )
            for index in range(1, slide_count + 1)
        )
        if image_buttons:
            groups.append(_control_group("Images", image_buttons))

    groups.append(
        _control_group(
            "Publish",
            f'<button class="btn btn-danger" type="button" data-action="publish" data-source-index="{source_index}">Post to Instagram</button>',
        )
    )

    return f'<div class="controls" data-source-index="{source_index}">{"".join(groups)}</div>'


def _control_group(label: str, buttons_html: str) -> str:
    return f'<div class="controls-group"><span class="controls-label">{html.escape(label)}</span>{buttons_html}</div>'


def _button(
    label: str,
    action: str,
    source_index: int,
    *,
    target: str | None = None,
    slide: int | None = None,
    title: str | None = None,
) -> str:
    attrs = [
        'class="btn"',
        'type="button"',
        f'data-action="{html.escape(action)}"',
        f'data-source-index="{source_index}"',
    ]
    if target:
        attrs.append(f'data-target="{html.escape(target)}"')
    if slide is not None:
        attrs.append(f'data-slide="{slide}"')
    if title:
        attrs.append(f'title="{html.escape(title)}"')
    return f"<button {' '.join(attrs)}>{html.escape(label)}</button>"


def control_panel_script() -> str:
    return """
<script>
(() => {
  const banner = document.getElementById("status-banner");
  let busy = false;

  if (window.location.protocol === "file:") {
    banner.textContent = "Open this page through the control panel server: http://127.0.0.1:8765/ (buttons do not work from a local file).";
    banner.className = "status-banner visible error";
    return;
  }

  function setStatus(message, kind) {
    banner.textContent = message;
    banner.className = "status-banner visible " + (kind || "ok");
  }

  function formatPipelineStatus(status) {
    if (!status) return "";
    const bits = [];
    if (status.extracted_count != null) bits.push("extracted " + status.extracted_count);
    if (status.scored_count != null) bits.push("scored " + status.scored_count);
    if (status.selected_count != null) bits.push("selected " + status.selected_count);
    return bits.join(", ");
  }

  function showPipelineStatus(status) {
    if (!status || !status.completed_at) return;
    const summary = formatPipelineStatus(status);
    const errors = status.errors || [];
    if (errors.length) {
      const preview = errors.slice(0, 3).join(" | ");
      const suffix = status.error_count > 3 ? " (+" + (status.error_count - 3) + " more)" : "";
      setStatus((summary ? summary + ". " : "") + preview + suffix, "warn");
      return;
    }
    if (status.selected_count === 0 && summary) {
      setStatus(summary + ". No items selected yet — try Reingest RSS.", "warn");
    }
  }

  function loadEmbeddedStatus() {
    const node = document.getElementById("pipeline-status");
    if (!node || !node.textContent) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (error) {
      return null;
    }
  }

  function setBusy(nextBusy) {
    busy = nextBusy;
    document.querySelectorAll("button").forEach((button) => {
      button.disabled = nextBusy;
    });
  }

  async function callApi(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      throw new Error(data.error || ("Request failed (" + response.status + ")"));
    }
    return data;
  }

  async function handleAction(button) {
    if (busy) return;
    const action = button.dataset.action;
    const sourceIndex = button.dataset.sourceIndex ? Number(button.dataset.sourceIndex) : null;
    const target = button.dataset.target || null;
    const slide = button.dataset.slide ? Number(button.dataset.slide) : null;

    setBusy(true);
    setStatus("Working… this can take a minute.", "ok");
    try {
      if (action === "reingest") {
        const result = await callApi("/api/reingest", {});
        if (result.error_count) {
          const preview = (result.errors || []).slice(0, 2).join(" | ");
          const suffix = result.error_count > 2 ? " (+" + (result.error_count - 2) + " more)" : "";
          setStatus(
            "Reingest finished with " + result.error_count + " warning(s): " + preview + suffix + " Refreshing…",
            "warn"
          );
        } else {
          setStatus("Reingest complete (" + result.selected_count + " items). Refreshing…", "ok");
        }
      } else if (action === "regenerate-text") {
        const result = await callApi("/api/regenerate-text", {
          source_index: sourceIndex,
        });
        const warnings = result.warnings || [];
        if (warnings.length) {
          setStatus(
            "Text updated with warnings: " + warnings.slice(0, 2).join(" | ") + ". Refreshing…",
            "warn"
          );
        } else {
          setStatus("Text updated. Refreshing…", "ok");
        }
      } else if (action === "regenerate-image") {
        await callApi("/api/regenerate-image", {
          source_index: sourceIndex,
          slide: slide,
        });
        setStatus("Image updated. Refreshing…", "ok");
      } else if (action === "publish") {
        const result = await callApi("/api/publish", { source_index: sourceIndex });
        setStatus("Published to Instagram. media_id=" + result.publish.media_id, "ok");
        setBusy(false);
        return;
      } else {
        throw new Error("Unknown action: " + action);
      }
      window.location.reload();
    } catch (error) {
      setStatus(error.message || String(error), "error");
      setBusy(false);
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    event.preventDefault();
    handleAction(button);
  });

  showPipelineStatus(loadEmbeddedStatus());
})();
</script>
"""


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

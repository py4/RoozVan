#!/usr/bin/env python3
"""Generate unified Instagram content for selected RoozVan preview items."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from openrouter_client import OpenRouterClient, OpenRouterError
from roozvan.models import ScoredItem
from roozvan.scoring import is_unsupported_structured_output_error, parse_json_object
from roozvan.post_content import normalize_caption_fa
from run_pipeline import write_html_report, write_json


DEFAULT_PROMPT = Path("prompts/instagram_content_generation.md")
DEFAULT_MODEL = "google/gemini-3.5-flash"
OVERLAY_CATEGORIES = (
    "transit",
    "traffic",
    "money",
    "jobs",
    "weather",
    "event",
    "food",
    "travel",
    "community",
    "lifestyle",
    "sports",
    "culture",
    "safety",
    "government",
    "other",
)

OVERLAY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(OVERLAY_CATEGORIES)},
        "title": {"type": "string", "minLength": 1},
        "body": {"type": "string", "minLength": 1},
    },
    "required": ["category", "title", "body"],
    "additionalProperties": False,
}

UNIFIED_CONTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "format": {"type": "string", "enum": ["story", "post", "carousel_post"]},
        "overlay": OVERLAY_SCHEMA,
        "caption_fa": {"type": ["string", "null"]},
        "short_alt_text_fa": {"type": "string"},
        "carousel_slides": {
            "type": "array",
            "minItems": 0,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "overlay": OVERLAY_SCHEMA,
                    "visual_direction": {"type": "string"},
                },
                "required": ["overlay", "visual_direction"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["format", "overlay", "caption_fa", "short_alt_text_fa", "carousel_slides"],
    "additionalProperties": False,
}


def unified_content_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "roozvan_instagram_content",
            "strict": True,
            "schema": UNIFIED_CONTENT_SCHEMA,
        },
    }


def load_selected(dump_dir: Path) -> list[ScoredItem]:
    data = json.loads((dump_dir / "selected.json").read_text(encoding="utf-8"))
    return [ScoredItem.from_dict(item) for item in data]


def build_context(item: ScoredItem) -> dict[str, Any]:
    news = item.item
    return {
        "source_index": item.source_index,
        "format": item.format_selected,
        "title": news.title,
        "description": news.description,
        "article_content": news.article_content,
        "date": news.date,
        "url": news.url,
        "category": item.evaluation.get("category"),
        "overall_score": item.overall_score,
        "reason_en": item.evaluation.get("reason_en"),
    }


def build_prompt(template: str, item: ScoredItem) -> str:
    return template.replace("{{CONTENT_CONTEXT}}", json.dumps(build_context(item), ensure_ascii=False, indent=2))


def normalize_unified_content(parsed: dict[str, Any], expected_format: str | None) -> dict[str, Any]:
    content = {
        "format": str(parsed.get("format") or expected_format or ""),
        "overlay": normalize_overlay(parsed.get("overlay")),
        "caption_fa": parsed.get("caption_fa"),
        "short_alt_text_fa": str(parsed.get("short_alt_text_fa") or ""),
        "carousel_slides": [],
    }
    if content["caption_fa"] is not None:
        content["caption_fa"] = normalize_caption_fa(str(content["caption_fa"]))

    raw_slides = parsed.get("carousel_slides") or []
    if isinstance(raw_slides, list):
        for raw_slide in raw_slides:
            if not isinstance(raw_slide, dict):
                continue
            content["carousel_slides"].append(
                {
                    "overlay": normalize_overlay(raw_slide.get("overlay")),
                    "visual_direction": str(raw_slide.get("visual_direction") or ""),
                }
            )
    if content["format"] != "carousel_post":
        content["carousel_slides"] = []
    return content


def normalize_overlay(raw: Any) -> dict[str, str]:
    raw = raw if isinstance(raw, dict) else {}
    category = str(raw.get("category") or "other").strip()
    if category not in OVERLAY_CATEGORIES:
        category = "other"
    return {
        "category": category,
        "title": str(raw.get("title") or "خبر مهم ونکوور").strip(),
        "body": str(raw.get("body") or "جزئیات این خبر برای ساکنان ونکوور مهم است.").strip(),
    }


def generate_content(
    item: ScoredItem,
    *,
    prompt_template: str,
    client: OpenRouterClient,
    max_tokens: int,
) -> ScoredItem:
    prompt = build_prompt(prompt_template, item)
    try:
        raw = client.ask(
            prompt,
            temperature=0.25,
            max_tokens=max_tokens,
            extra_body={
                "response_format": unified_content_response_format(),
                "provider": {"require_parameters": True},
            },
        )
    except OpenRouterError as exc:
        if not is_unsupported_structured_output_error(exc):
            raise
        raw = client.ask(prompt, temperature=0.25, max_tokens=max_tokens)
    parsed = parse_json_object(raw)
    content = normalize_unified_content(parsed, item.format_selected)
    evaluation = {
        **item.evaluation,
        "instagram_content": content,
    }
    news_item = item.item
    if item.format_selected in {"post", "carousel_post"} and content.get("caption_fa"):
        news_item = replace(news_item, post_caption_fa=str(content["caption_fa"]))
    if item.format_selected == "post":
        evaluation["post_caption"] = {
            "caption_fa": content.get("caption_fa") or "",
            "short_alt_text_fa": content.get("short_alt_text_fa") or "",
            "image_headline_fa": content["overlay"]["title"],
            "image_subline_fa": content["overlay"]["body"],
            "category_label_fa": content["overlay"]["category"],
        }
    if item.format_selected == "carousel_post":
        slides = [
            {
                "headline_fa": slide["overlay"]["title"],
                "body_fa": slide["overlay"]["body"],
                "category_label_fa": slide["overlay"]["category"] if index == 0 else "",
                "visual_direction": slide.get("visual_direction") or "",
            }
            for index, slide in enumerate(content.get("carousel_slides") or [])
        ]
        evaluation["carousel_post"] = {
            "caption_fa": content.get("caption_fa") or "",
            "short_alt_text_fa": content.get("short_alt_text_fa") or "",
            "slides": slides,
        }
    return replace(item, item=news_item, evaluation=evaluation)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump-dir", type=Path, default=Path("runs/live-debug"))
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=1800)
    parser.add_argument("--only-source-index", type=int, action="append", dest="only_source_indexes")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    items = load_selected(args.dump_dir)
    prompt_template = args.prompt.read_text(encoding="utf-8")
    allowed = set(args.only_source_indexes) if args.only_source_indexes else None
    indexes_to_process = [
        index for index, item in enumerate(items) if allowed is None or item.source_index in allowed
    ]
    client = OpenRouterClient(model=args.model, timeout=120, app_name="RoozVan")
    updated = list(items)

    def generate_index(index: int) -> tuple[int, ScoredItem]:
        item = items[index]
        print(f"{item.source_index}: generating unified content for {item.format_selected}", file=sys.stderr)
        return index, generate_content(
            item,
            prompt_template=prompt_template,
            client=client,
            max_tokens=args.max_tokens,
        )

    worker_count = max(1, min(args.workers, len(indexes_to_process) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(generate_index, index): index for index in indexes_to_process}
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                completed_index, item = future.result()
                updated[completed_index] = item
                print(f"{item.source_index}: content ready", file=sys.stderr)
            except Exception as exc:
                print(f"warning: failed item index {index}: {exc}", file=sys.stderr)

    write_json(args.dump_dir / "selected.json", [item.to_dict() for item in updated])
    write_html_report(args.dump_dir / "index.html", updated)
    print(args.dump_dir / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

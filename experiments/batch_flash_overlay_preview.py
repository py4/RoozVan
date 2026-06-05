#!/usr/bin/env python3
"""Generate text-free image backgrounds and local Farsi overlays for preview items."""

from __future__ import annotations

import base64
import argparse
import concurrent.futures
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from openrouter_client import OpenRouterClient, OpenRouterError
from roozvan.models import ScoredItem
from roozvan.story_images import (
    build_openrouter_image_request_body,
    extension_for_mime_type,
    parse_data_url,
    post_openrouter_image_request,
)
from run_pipeline import write_html_report, write_json
from experiments.farsi_story_overlay import StoryText, overlay_category_label_fa, render_overlay


DEFAULT_TEXT_MODEL = "openai/gpt-oss-120b:free"
DEFAULT_IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"
DEFAULT_OUTPUT_DIR = Path("generated_post_images/flash_overlay_batch")


def load_items(
    dump_dir: Path,
    *,
    formats: set[str],
    only_source_indexes: set[int] | None,
) -> list[ScoredItem]:
    data = json.loads((dump_dir / "selected.json").read_text(encoding="utf-8"))
    return [
        ScoredItem.from_dict(item)
        for item in data
        if item.get("format_selected") in formats
        and (only_source_indexes is None or int(item.get("source_index")) in only_source_indexes)
    ]


def overlay_copy_prompt(item: ScoredItem) -> str:
    news = item.item
    candidate = {
        "source_index": item.source_index,
        "format": item.format_selected,
        "english_title": news.title,
        "description": news.description,
        "category": item.evaluation.get("category"),
        "post_caption_fa": news.post_caption_fa,
    }
    prompt = (
        "Write compact Persian/Farsi overlay copy for this RoozVan IMAGE, not the caption.\n"
        "Audience: Iranian diaspora in Metro Vancouver. Tone: clear, local, practical.\n"
        "Return only valid JSON: {\"source_index\":number,\"kicker\":\"...\",\"title\":\"...\",\"body\":\"...\"}.\n"
        "Core length rules: kicker max 3 words, title 4-7 words, body one sentence under 18 words. "
        "No hashtags, no emojis, no dense paragraphs.\n"
        "The title should be a clean Farsi news hook. The body should explain the practical point.\n"
        "Do not translate word-for-word. Understand the item, localize it, and write natural Farsi.\n"
        "Use natural Persian for generic concepts. Preserve official proper nouns, acronyms, brand names, "
        "station names, venue names, product names, and event names exactly in English when they are needed "
        "for recognition. Do not translate or phonetic-transliterate those names.\n"
        "Avoid awkward phonetic transliteration. If a term is not a proper noun and has a normal Persian "
        "equivalent, use the Persian equivalent.\n"
        "Do not invent a category or label that is not supported by the item.\n"
        "Prefer Farsi wording for the headline; use at most one official English name in the title.\n"
        "Never write internal judgment language such as low value, not useful, or not practical.\n"
        "Use standard Persian numerals for numbers in Persian sentences, e.g. ۲۵، ۴۰ هزار، ۵٪.\n"
        "Keep the copy short enough for an image overlay.\n\n"
        f"Item:\n{json.dumps(candidate, ensure_ascii=False, indent=2)}"
    )
    return prompt


def generate_overlay_copy_for_item(item: ScoredItem, *, text_model: str) -> StoryText:
    client = OpenRouterClient(model=text_model, timeout=120, app_name="RoozVan")
    raw = client.ask(overlay_copy_prompt(item), temperature=0.2, max_tokens=350)
    parsed = json.loads(extract_json(raw))
    return StoryText(
        kicker=str(parsed.get("kicker") or category_kicker(item)),
        title=str(parsed.get("title") or "خبر مهم ونکوور"),
        body=str(parsed.get("body") or ""),
    )


def generate_overlay_copy(
    items: list[ScoredItem],
    *,
    text_model: str,
    workers: int,
) -> dict[int, StoryText]:
    by_index: dict[int, StoryText] = {}
    worker_count = max(1, min(workers, len(items) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(generate_overlay_copy_for_item, item, text_model=text_model): item
            for item in items
        }
        for future in concurrent.futures.as_completed(futures):
            item = futures[future]
            try:
                by_index[item.source_index] = future.result()
            except Exception as exc:
                print(
                    f"warning: overlay copy failed for {item.source_index}, using fallback: {exc}",
                    file=sys.stderr,
                )
                by_index[item.source_index] = fallback_story_text(item)
    return by_index


def overlay_copy_from_unified_content(items: list[ScoredItem]) -> dict[int, StoryText]:
    by_index: dict[int, StoryText] = {}
    for item in items:
        content = item.evaluation.get("instagram_content")
        if not isinstance(content, dict):
            continue
        overlay = content.get("overlay")
        if not isinstance(overlay, dict):
            continue
        by_index[item.source_index] = StoryText(
            kicker=overlay_category_label_fa(str(overlay.get("category") or "")),
            title=str(overlay.get("title") or "خبر مهم ونکوور"),
            body=str(overlay.get("body") or ""),
        )
    return by_index


def generate_overlay_copy_legacy_batch(items: list[ScoredItem], *, text_model: str) -> dict[int, StoryText]:
    """Kept for quick comparison if batch prompting is useful later."""
    try:
        candidates = []
        for item in items:
            news = item.item
            candidates.append(
                {
                    "source_index": item.source_index,
                    "format": item.format_selected,
                    "english_title": news.title,
                    "description": news.description,
                    "category": item.evaluation.get("category"),
                    "post_caption_fa": news.post_caption_fa,
                }
            )
        client = OpenRouterClient(model=text_model, timeout=120, app_name="RoozVan")
        raw = client.ask(
            "Return compact Farsi overlay copy JSON for these items: "
            f"{json.dumps(candidates, ensure_ascii=False)}",
            temperature=0.2,
            max_tokens=2200,
        )
        parsed = json.loads(extract_json(raw))
    except Exception as exc:
        print(f"warning: overlay copy LLM failed, using fallback copy: {exc}", file=sys.stderr)
        return {item.source_index: fallback_story_text(item) for item in items}

    by_index = {}
    for raw_item in parsed.get("items", []):
        try:
            source_index = int(raw_item["source_index"])
            by_index[source_index] = StoryText(
                kicker=str(raw_item.get("kicker") or "رویداد ونکوور"),
                title=str(raw_item.get("title") or "خبر مهم ونکوور"),
                body=str(raw_item.get("body") or ""),
            )
        except (KeyError, TypeError, ValueError):
            continue
    for item in items:
        by_index.setdefault(item.source_index, fallback_story_text(item))
    return by_index


def write_overlay_copy(path: Path, overlay_copy: dict[int, StoryText]) -> None:
    path.write_text(
        json.dumps(
            {
                str(source_index): {
                    "kicker": text.kicker,
                    "title": text.title,
                    "body": text.body,
                }
                for source_index, text in sorted(overlay_copy.items())
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def extract_json(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        return text[start : end + 1]
    return text


def fallback_story_text(item: ScoredItem) -> StoryText:
    title = item.item.post_caption_fa or item.item.title or "خبر مهم برای ونکوور"
    words = str(title).split()
    compact_title = " ".join(words[:7])
    body = " ".join(words[7:25]) or "جزئیات این خبر می‌تواند برای برنامه‌ریزی روزانه مفید باشد."
    return StoryText(kicker=category_kicker(item), title=compact_title, body=body)


def category_kicker(item: ScoredItem) -> str:
    category = str(item.evaluation.get("category") or "")
    if "transit" in category:
        return "حمل‌ونقل"
    if "weather" in category:
        return "هواشناسی"
    if "jobs" in category:
        return "کار"
    if "money" in category:
        return "هزینه‌ها"
    if "community" in category:
        return "جامعه"
    if "lifestyle" in category:
        return "زندگی ونکوور"
    return "ونکوور"


def background_prompt(item: ScoredItem, aspect_ratio: str) -> str:
    news = item.item
    context = (news.article_content or news.description or "")[:1800]
    return f"""
Create a realistic editorial photo background for an Instagram news {item.format_selected}.

Aspect ratio: {aspect_ratio}. Image only, no typography.

News title:
{news.title}

Article context:
{context}

Generic visual direction:
Create a local Metro Vancouver editorial news image that reflects the article topic in a practical, realistic way. Use real-world Vancouver/BC public spaces, streets, transit, weather, community venues, airports, parks, or everyday residents only when relevant to the article. The mood should be trustworthy, civic, useful, and Instagram-ready, like a high-quality local news magazine photo.

Composition:
Reserve the top 38% as clean, uncluttered negative space for Persian text added later. Put the main scene, people, vehicles, objects, or venue details mostly in the lower 62%. Keep faces natural and avoid dramatic staged poses.

Strict restrictions:
No readable text, no fake writing, no letters, no numbers, no logos, no route numbers, no brand names, no watermarks, no captions, no signage, no posters, no screen text. Any signs, screens, cards, ads, posters, vehicle displays, storefronts, or maps must be blank, blurred, cropped, or abstract with no readable writing. No Farsi. No English.
""".strip()


def generate_background(
    item: ScoredItem,
    aspect_ratio: str,
    *,
    image_model: str,
    output_dir: Path,
    force: bool,
) -> Path:
    extension = "jpg"
    background_path = output_dir / f"source-{item.source_index}-{item.format_selected}-background.{extension}"
    if background_path.exists() and not force:
        return background_path

    client = OpenRouterClient(model=image_model, timeout=300, app_name="RoozVan")
    body = build_openrouter_image_request_body(
        model=image_model,
        prompt=background_prompt(item, aspect_ratio),
        aspect_ratio=aspect_ratio,
    )
    response = post_openrouter_image_request(client, body)
    message = response.get("choices", [{}])[0].get("message", {})
    images = message.get("images") or []
    if not images:
        raise OpenRouterError(f"OpenRouter returned no images: {response}")
    image_url = images[0].get("image_url", {}).get("url")
    if not isinstance(image_url, str):
        raise OpenRouterError(f"Unexpected image payload: {images[0]!r}")
    mime, payload = parse_data_url(image_url)
    extension = extension_for_mime_type(mime)
    background_path = output_dir / f"source-{item.source_index}-{item.format_selected}-background.{extension}"
    background_path.write_bytes(base64.b64decode(payload))
    background_path.with_suffix(".response_summary.json").write_text(
        json.dumps(
            {
                "model": image_model,
                "source_index": item.source_index,
                "format": item.format_selected,
                "title": item.item.title,
                "usage": response.get("usage"),
                "id": response.get("id"),
                "assistant_content": message.get("content"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return background_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump-dir", type=Path, default=Path("runs/live-debug"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--text-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--image-model", default=DEFAULT_IMAGE_MODEL)
    parser.add_argument(
        "--format",
        action="append",
        choices=("story", "post", "carousel_post"),
        dest="formats",
        help="Format to process. Repeatable. Defaults to story and post.",
    )
    parser.add_argument(
        "--only-source-index",
        type=int,
        action="append",
        dest="only_source_indexes",
        help="Process only this source_index. Repeatable.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate backgrounds even if matching files already exist.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel image/background workers. Existing backgrounds are reused unless --force is set.",
    )
    parser.add_argument(
        "--prefer-unified-content",
        action="store_true",
        help="Use evaluation.instagram_content.overlay when present before calling --text-model.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    formats = set(args.formats or ["story", "post"])
    only_source_indexes = set(args.only_source_indexes) if args.only_source_indexes else None
    all_data = json.loads((args.dump_dir / "selected.json").read_text(encoding="utf-8"))
    items = load_items(args.dump_dir, formats=formats, only_source_indexes=only_source_indexes)
    overlay_copy = overlay_copy_from_unified_content(items) if args.prefer_unified_content else {}
    missing_items = [item for item in items if item.source_index not in overlay_copy]
    if missing_items:
        overlay_copy.update(
            generate_overlay_copy(missing_items, text_model=args.text_model, workers=args.workers)
        )
    write_overlay_copy(args.output_dir / "overlay_copy.json", overlay_copy)

    def process_item(item: ScoredItem) -> tuple[int, str]:
        aspect_ratio = "9:16" if item.format_selected == "story" else "4:5"
        print(f"{item.source_index}: generating {item.format_selected} background", file=sys.stderr)
        background = generate_background(
            item,
            aspect_ratio,
            image_model=args.image_model,
            output_dir=args.output_dir,
            force=args.force,
        )
        output = args.output_dir / f"source-{item.source_index}-{item.format_selected}-overlay.jpg"
        render_overlay(background, output, overlay_copy[item.source_index])
        return item.source_index, str(output)

    updated_paths: dict[int, str] = {}
    worker_count = max(1, min(args.workers, len(items) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(process_item, item): item for item in items}
        for future in concurrent.futures.as_completed(futures):
            item = futures[future]
            source_index, output = future.result()
            updated_paths[source_index] = output
            print(f"{item.source_index}: {output}", file=sys.stderr)

    for raw_item in all_data:
        source_index = raw_item.get("source_index")
        if source_index not in updated_paths:
            continue
        if raw_item.get("format_selected") == "story":
            raw_item["item"]["story_image_path"] = updated_paths[source_index]
        elif raw_item.get("format_selected") == "post":
            raw_item["item"]["post_image_path"] = updated_paths[source_index]

    write_json(args.dump_dir / "selected.json", all_data)
    write_html_report(args.dump_dir / "index.html", [ScoredItem.from_dict(item) for item in all_data])
    print(args.dump_dir / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

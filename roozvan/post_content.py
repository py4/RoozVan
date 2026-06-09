"""Post image and caption generation for selected RoozVan post items."""

from __future__ import annotations

import base64
import concurrent.futures
import copy
import json
import re
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from openrouter_client import OpenRouterClient, OpenRouterError
from roozvan.logo_overlay import DEFAULT_LOGO_PATH, apply_logo_overlay
from roozvan.models import ScoredItem
from roozvan.progress import ProgressLogger, log_progress, short_title
from roozvan.scoring import is_unsupported_structured_output_error, parse_json_object
from roozvan.text_overlay import OverlayText, render_overlay
from roozvan.story_images import (
    DEFAULT_GEMINI_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_PROVIDER,
    build_openrouter_image_request_body,
    build_story_image_prompt,
    extension_for_mime_type,
    extract_gemini_inline_image,
    parse_data_url,
    post_gemini_image_request_with_config,
    post_openrouter_image_request,
)

# Instagram-friendly bullets the caption formatter recognizes.
ALLOWED_INSTAGRAM_FORMATS = frozenset({"story", "post", "carousel_post"})

CAPTION_BULLET_MARKERS = (
    "📌",
    "✅",
    "🔎",
    "🗓️",
    "📍",
    "💡",
    "⚽",
    "🎉",
    "🎭",
    "🎶",
    "🎨",
    "•",
)


CAPTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "caption_fa": {"type": "string", "minLength": 1},
        "short_alt_text_fa": {"type": "string", "minLength": 1},
        "image_headline_fa": {"type": "string", "minLength": 1},
        "image_subline_fa": {"type": "string", "minLength": 1},
        "category_label_fa": {"type": "string", "minLength": 1},
    },
    "required": [
        "caption_fa",
        "short_alt_text_fa",
        "image_headline_fa",
        "image_subline_fa",
        "category_label_fa",
    ],
    "additionalProperties": False,
}

CAROUSEL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "caption_fa": {"type": "string", "minLength": 1},
        "short_alt_text_fa": {"type": "string", "minLength": 1},
        "slides": {
            "type": "array",
            "minItems": 3,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "headline_fa": {"type": "string", "minLength": 1},
                    "body_fa": {"type": "string", "minLength": 1},
                    "category_label_fa": {"type": "string"},
                    "visual_direction": {"type": "string", "minLength": 1},
                },
                "required": [
                    "headline_fa",
                    "body_fa",
                    "category_label_fa",
                    "visual_direction",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["caption_fa", "short_alt_text_fa", "slides"],
    "additionalProperties": False,
}


def caption_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "instagram_post_caption",
            "strict": True,
            "schema": CAPTION_RESPONSE_SCHEMA,
        },
    }


def carousel_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "instagram_carousel_post",
            "strict": True,
            "schema": CAROUSEL_RESPONSE_SCHEMA,
        },
    }


UNIFIED_INSTAGRAM_CONTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "format": {"type": "string", "enum": sorted(ALLOWED_INSTAGRAM_FORMATS)},
        "caption_fa": {"type": ["string", "null"]},
        "short_alt_text_fa": {"type": "string", "minLength": 1},
        "image_headline_fa": {"type": "string", "minLength": 1},
        "image_subline_fa": {"type": "string", "minLength": 1},
        "category_label_fa": {"type": "string", "minLength": 1},
        "slides": {
            "type": "array",
            "minItems": 0,
            "maxItems": 6,
            "items": CAROUSEL_RESPONSE_SCHEMA["properties"]["slides"]["items"],
        },
    },
    "required": [
        "format",
        "caption_fa",
        "short_alt_text_fa",
        "image_headline_fa",
        "image_subline_fa",
        "category_label_fa",
        "slides",
    ],
    "additionalProperties": False,
}


def unified_instagram_content_response_format(*, fixed_format: str | None = None) -> dict[str, Any]:
    schema = copy.deepcopy(UNIFIED_INSTAGRAM_CONTENT_SCHEMA)
    if fixed_format:
        schema["properties"]["format"] = {"type": "string", "enum": [fixed_format]}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "roozvan_instagram_content",
            "strict": True,
            "schema": schema,
        },
    }


def build_scoring_context(scored_item: ScoredItem) -> dict[str, Any]:
    evaluation = scored_item.evaluation
    return {
        "overall_score": scored_item.overall_score,
        "category": evaluation.get("category"),
        "base_score": evaluation.get("base_score"),
        "editorial_adjustment": evaluation.get("editorial_adjustment"),
        "editorial_adjustment_reasons": evaluation.get("editorial_adjustment_reasons"),
        "selection_gate_passed": evaluation.get("selection_gate_passed"),
        "selection_gate_reasons": evaluation.get("selection_gate_reasons"),
        "local_relevance": evaluation.get("local_relevance"),
        "practical_usefulness": evaluation.get("practical_usefulness"),
        "immigrant_relevance": evaluation.get("immigrant_relevance"),
        "urgency": evaluation.get("urgency"),
        "share_save_potential": evaluation.get("share_save_potential"),
        "trustworthiness": evaluation.get("trustworthiness"),
        "actionability": evaluation.get("actionability"),
        "originality": evaluation.get("originality"),
        "reason_en": evaluation.get("reason_en"),
        "persian_angle": evaluation.get("persian_angle"),
    }


def build_content_generation_context(scored_item: ScoredItem) -> dict[str, Any]:
    item = scored_item.item
    return {
        "source_index": scored_item.source_index,
        "title": item.title,
        "description": item.description,
        "date": item.date,
        "url": item.url,
        "article_content": item.article_content,
        "category": scored_item.evaluation.get("category"),
        "overall_score": scored_item.overall_score,
        "persian_angle": scored_item.evaluation.get("persian_angle"),
        "reason_en": scored_item.evaluation.get("reason_en"),
        "selection_gate_reasons": scored_item.evaluation.get("selection_gate_reasons"),
        "editorial_adjustment_reasons": scored_item.evaluation.get("editorial_adjustment_reasons"),
    }


FORMAT_REGENERATION_LOCK = """\
## Format lock (regeneration)

This item already uses format `{required_format}`. You MUST return `"format": "{required_format}"` exactly.
Regenerate all text fields for that format only (caption, overlay text, carousel slides as applicable).
Do not switch to another format.\
"""


def build_content_generation_prompt(
    prompt_template: str,
    scored_item: ScoredItem,
    *,
    required_format: str | None = None,
) -> str:
    scoring_context = json.dumps(build_scoring_context(scored_item), ensure_ascii=False, indent=2)
    content_context = json.dumps(build_content_generation_context(scored_item), ensure_ascii=False, indent=2)
    prompt = prompt_template.replace("{{SCORING_CONTEXT}}", scoring_context)
    prompt = prompt.replace("{{CONTENT_CONTEXT}}", content_context)
    if required_format:
        prompt = f"{prompt}\n\n{FORMAT_REGENERATION_LOCK.format(required_format=required_format)}"
    return prompt


def apply_unified_instagram_content(scored_item: ScoredItem, parsed: dict[str, Any]) -> ScoredItem:
    selected_format = str(parsed.get("format") or "").strip()
    if selected_format not in ALLOWED_INSTAGRAM_FORMATS:
        raise ValueError(f"Invalid selected format: {selected_format!r}")

    short_alt_text_fa = str(parsed.get("short_alt_text_fa") or "").strip()
    image_headline_fa = str(parsed.get("image_headline_fa") or "").strip()
    image_subline_fa = str(parsed.get("image_subline_fa") or "").strip()
    category_label_fa = str(parsed.get("category_label_fa") or "").strip()
    evaluation = dict(scored_item.evaluation)
    item = scored_item.item

    if selected_format == "story":
        evaluation["post_caption"] = {
            "caption_fa": "",
            "short_alt_text_fa": short_alt_text_fa,
            "image_headline_fa": image_headline_fa,
            "image_subline_fa": image_subline_fa,
            "category_label_fa": category_label_fa,
        }
        return replace(scored_item, format_selected=selected_format, item=item, evaluation=evaluation)

    if selected_format == "post":
        caption_fa = normalize_caption_fa(str(parsed.get("caption_fa") or ""))
        if not caption_fa:
            raise ValueError("post format requires caption_fa")
        evaluation["post_caption"] = {
            "caption_fa": caption_fa,
            "short_alt_text_fa": short_alt_text_fa,
            "image_headline_fa": image_headline_fa,
            "image_subline_fa": image_subline_fa,
            "category_label_fa": category_label_fa,
        }
        item = replace(item, post_caption_fa=caption_fa)
        return replace(scored_item, format_selected=selected_format, item=item, evaluation=evaluation)

    slides = normalize_carousel_slides(parsed.get("slides"))
    if len(slides) < 3:
        raise ValueError("carousel_post format requires at least 3 slides")
    caption_fa = normalize_caption_fa(str(parsed.get("caption_fa") or ""))
    if not caption_fa:
        raise ValueError("carousel_post format requires caption_fa")
    if image_headline_fa:
        slides[0] = {
            **slides[0],
            "headline_fa": image_headline_fa,
            "body_fa": image_subline_fa or slides[0]["body_fa"],
            "category_label_fa": category_label_fa or slides[0]["category_label_fa"],
        }
    elif slides:
        image_headline_fa = slides[0]["headline_fa"]
        image_subline_fa = slides[0]["body_fa"]
        category_label_fa = slides[0]["category_label_fa"]
    evaluation["carousel_post"] = {
        "caption_fa": caption_fa,
        "short_alt_text_fa": short_alt_text_fa,
        "slides": slides,
    }
    evaluation["post_caption"] = {
        "caption_fa": caption_fa,
        "short_alt_text_fa": short_alt_text_fa,
        "image_headline_fa": image_headline_fa,
        "image_subline_fa": image_subline_fa,
        "category_label_fa": category_label_fa,
    }
    item = replace(item, post_caption_fa=caption_fa)
    return replace(scored_item, format_selected=selected_format, item=item, evaluation=evaluation)


def _call_unified_instagram_content(
    prompt: str,
    client: OpenRouterClient,
    *,
    max_tokens: int,
    fixed_format: str | None = None,
) -> dict[str, Any]:
    try:
        raw_response = client.ask(
            prompt,
            temperature=0.35,
            max_tokens=max_tokens,
            extra_body={
                "response_format": unified_instagram_content_response_format(fixed_format=fixed_format),
                "provider": {
                    "require_parameters": True,
                },
            },
        )
    except OpenRouterError as exc:
        if not is_unsupported_structured_output_error(exc):
            raise
        raw_response = client.ask(prompt, temperature=0.35, max_tokens=max_tokens)
    return parse_json_object(raw_response)


def generate_instagram_content(
    scored_item: ScoredItem,
    prompt_template: str,
    client: OpenRouterClient,
    *,
    max_tokens: int,
) -> ScoredItem:
    prompt = build_content_generation_prompt(prompt_template, scored_item)
    parsed = _call_unified_instagram_content(prompt, client, max_tokens=max_tokens)
    return apply_unified_instagram_content(scored_item, parsed)


def regenerate_instagram_content(
    scored_item: ScoredItem,
    prompt_template: str,
    client: OpenRouterClient,
    *,
    max_tokens: int,
    max_attempts: int = 3,
) -> tuple[ScoredItem, list[str]]:
    required_format = scored_item.format_selected
    if required_format not in ALLOWED_INSTAGRAM_FORMATS:
        raise ValueError(
            f"Cannot regenerate content without an existing format (got {required_format!r})"
        )

    warnings: list[str] = []
    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        prompt = build_content_generation_prompt(
            prompt_template,
            scored_item,
            required_format=required_format,
        )
        try:
            parsed = _call_unified_instagram_content(
                prompt,
                client,
                max_tokens=max_tokens,
                fixed_format=required_format,
            )
        except (OpenRouterError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            warnings.append(f"attempt {attempt}/{max_attempts} failed: {exc}")
            continue

        returned_format = str(parsed.get("format") or "").strip()
        if returned_format != required_format:
            last_error = f"model returned format {returned_format!r} instead of {required_format!r}"
            warnings.append(f"attempt {attempt}/{max_attempts}: {last_error}")
            continue

        try:
            return apply_unified_instagram_content(scored_item, parsed), warnings
        except ValueError as exc:
            last_error = str(exc)
            warnings.append(f"attempt {attempt}/{max_attempts}: {exc}")
            continue

    raise ValueError(
        f"Failed to regenerate content for format {required_format!r} after {max_attempts} attempts: {last_error}"
    )


def generate_instagram_content_for_scored_items(
    items: list[ScoredItem],
    *,
    content_prompt_template: str,
    image_prompt_template: str,
    carousel_image_prompt_template: str,
    caption_client: OpenRouterClient,
    image_client: OpenRouterClient,
    output_dir: Path,
    image_model: str,
    image_provider: str,
    caption_max_tokens: int,
    image_max_tokens: int | None,
    workers: int = 4,
    apply_logo_overlay_enabled: bool = True,
    logo_path: Path = DEFAULT_LOGO_PATH,
    generate_images: bool = False,
    progress_log: ProgressLogger | None = None,
) -> list[ScoredItem]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[ScoredItem | None] = [None] * len(items)
    total = len(items)
    completed = 0

    def generate_indexed_content(index: int, scored_item: ScoredItem) -> tuple[int, ScoredItem]:
        updated = generate_instagram_content(
            scored_item,
            content_prompt_template,
            caption_client,
            max_tokens=max(caption_max_tokens, 1400),
        )
        if not generate_images:
            return index, updated
        return index, generate_post_images_only(
            updated,
            image_prompt_template=image_prompt_template,
            carousel_image_prompt_template=carousel_image_prompt_template,
            image_client=image_client,
            output_dir=output_dir,
            image_model=image_model,
            image_provider=image_provider,
            image_max_tokens=image_max_tokens,
            apply_logo_overlay_enabled=apply_logo_overlay_enabled,
            logo_path=logo_path,
        )

    max_workers = max(1, min(workers, len(items) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(generate_indexed_content, index, scored_item): (index, scored_item)
            for index, scored_item in enumerate(items)
        }
        for future in concurrent.futures.as_completed(futures):
            index, scored_item = futures[future]
            completed += 1
            try:
                completed_index, completed_item = future.result()
            except (OpenRouterError, ValueError, json.JSONDecodeError) as exc:
                print(
                    f"warning: failed to generate instagram content for item {scored_item.source_index} "
                    f"({scored_item.item.title}): {exc}",
                    file=sys.stderr,
                )
                log_progress(
                    progress_log,
                    f"content: {completed}/{total} failed — {short_title(scored_item.item.title)}",
                )
                results[index] = scored_item
            except Exception as exc:  # noqa: BLE001
                print(
                    f"warning: unexpected failure generating instagram content for item {scored_item.source_index} "
                    f"({scored_item.item.title}): {exc}",
                    file=sys.stderr,
                )
                log_progress(
                    progress_log,
                    f"content: {completed}/{total} failed — {short_title(scored_item.item.title)}",
                )
                results[index] = scored_item
            else:
                results[completed_index] = completed_item
                log_progress(
                    progress_log,
                    f"content: {completed}/{total} {completed_item.format_selected} — "
                    f"{short_title(completed_item.item.title)}",
                )

    return [item for item in results if item is not None]


def generate_post_content_for_scored_items(
    items: list[ScoredItem],
    *,
    content_prompt_template: str,
    image_prompt_template: str,
    carousel_image_prompt_template: str,
    caption_client: OpenRouterClient,
    image_client: OpenRouterClient,
    output_dir: Path,
    image_model: str = DEFAULT_STORY_IMAGE_MODEL,
    image_provider: str = DEFAULT_STORY_IMAGE_PROVIDER,
    caption_max_tokens: int = 900,
    image_max_tokens: int | None = 12000,
    workers: int = 4,
    apply_logo_overlay_enabled: bool = True,
    logo_path: Path = DEFAULT_LOGO_PATH,
    generate_images: bool = False,
    progress_log: ProgressLogger | None = None,
    **_: Any,
) -> list[ScoredItem]:
    return generate_instagram_content_for_scored_items(
        items,
        content_prompt_template=content_prompt_template,
        image_prompt_template=image_prompt_template,
        carousel_image_prompt_template=carousel_image_prompt_template,
        caption_client=caption_client,
        image_client=image_client,
        output_dir=output_dir,
        image_model=image_model,
        image_provider=image_provider,
        caption_max_tokens=caption_max_tokens,
        image_max_tokens=image_max_tokens,
        workers=workers,
        apply_logo_overlay_enabled=apply_logo_overlay_enabled,
        logo_path=logo_path,
        generate_images=generate_images,
        progress_log=progress_log,
    )


def generate_post_images_for_scored_items(
    items: list[ScoredItem],
    *,
    image_prompt_template: str,
    carousel_image_prompt_template: str,
    image_client: OpenRouterClient,
    output_dir: Path,
    image_model: str = DEFAULT_STORY_IMAGE_MODEL,
    image_provider: str = DEFAULT_STORY_IMAGE_PROVIDER,
    image_max_tokens: int | None = 12000,
    workers: int = 4,
    apply_logo_overlay_enabled: bool = True,
    logo_path: Path = DEFAULT_LOGO_PATH,
) -> list[ScoredItem]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[ScoredItem | None] = [None] * len(items)

    def generate_indexed_images(index: int, scored_item: ScoredItem) -> tuple[int, ScoredItem]:
        if scored_item.format_selected not in {"post", "carousel_post"}:
            return index, scored_item
        completed = generate_post_images_only(
            scored_item,
            image_prompt_template=image_prompt_template,
            carousel_image_prompt_template=carousel_image_prompt_template,
            image_client=image_client,
            output_dir=output_dir,
            image_model=image_model,
            image_provider=image_provider,
            image_max_tokens=image_max_tokens,
            apply_logo_overlay_enabled=apply_logo_overlay_enabled,
            logo_path=logo_path,
        )
        return index, completed

    max_workers = max(1, min(workers, len(items) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(generate_indexed_images, index, scored_item): (index, scored_item)
            for index, scored_item in enumerate(items)
        }
        for future in concurrent.futures.as_completed(futures):
            index, scored_item = futures[future]
            try:
                completed_index, completed_item = future.result()
            except (OpenRouterError, ValueError, json.JSONDecodeError) as exc:
                print(
                    f"warning: failed to generate post images for item {scored_item.source_index} "
                    f"({scored_item.item.title}): {exc}",
                    file=sys.stderr,
                )
                results[index] = scored_item
            except Exception as exc:  # noqa: BLE001 - pipeline should continue on one failed post.
                print(
                    f"warning: unexpected failure generating post images for item {scored_item.source_index} "
                    f"({scored_item.item.title}): {exc}",
                    file=sys.stderr,
                )
                results[index] = scored_item
            else:
                results[completed_index] = completed_item

    return [item for item in results if item is not None]


def generate_post_content(
    scored_item: ScoredItem,
    *,
    image_prompt_template: str,
    caption_prompt_template: str,
    carousel_content_prompt_template: str,
    carousel_image_prompt_template: str,
    caption_client: OpenRouterClient,
    image_client: OpenRouterClient,
    output_dir: Path,
    image_model: str,
    image_provider: str,
    caption_max_tokens: int,
    image_max_tokens: int | None,
    apply_logo_overlay_enabled: bool = True,
    logo_path: Path = DEFAULT_LOGO_PATH,
    generate_images: bool = False,
) -> ScoredItem:
    if scored_item.format_selected == "carousel_post":
        return generate_carousel_content(
            scored_item,
            content_prompt_template=carousel_content_prompt_template,
            image_prompt_template=carousel_image_prompt_template,
            caption_client=caption_client,
            image_client=image_client,
            output_dir=output_dir,
            image_model=image_model,
            image_provider=image_provider,
            caption_max_tokens=caption_max_tokens,
            image_max_tokens=image_max_tokens,
            apply_logo_overlay_enabled=apply_logo_overlay_enabled,
            logo_path=logo_path,
            generate_images=generate_images,
        )

    context = build_post_context(scored_item)
    caption = generate_post_caption(
        caption_prompt_template,
        context,
        caption_client,
        max_tokens=caption_max_tokens,
    )
    item = replace(
        scored_item.item,
        post_caption_fa=caption["caption_fa"],
    )
    evaluation = {
        **scored_item.evaluation,
        "post_caption": caption,
    }
    updated = replace(scored_item, item=item, evaluation=evaluation)
    if not generate_images:
        return updated

    image_context = {
        **context,
        "image_headline_fa": caption["image_headline_fa"],
        "image_subline_fa": caption["image_subline_fa"],
        "category_label_fa": caption["category_label_fa"],
    }
    image_path = generate_post_image(
        updated,
        image_prompt_template,
        image_context,
        image_client,
        output_dir=output_dir,
        model=image_model,
        provider=image_provider,
        max_tokens=image_max_tokens,
        apply_logo_overlay_enabled=apply_logo_overlay_enabled,
        logo_path=logo_path,
    )
    background_path = ensure_post_image_background_path(updated, output_dir)
    item = replace(
        updated.item,
        post_image_path=str(image_path),
        post_image_background_path=str(background_path),
    )
    return replace(updated, item=item)


def generate_post_images_only(
    scored_item: ScoredItem,
    *,
    image_prompt_template: str,
    carousel_image_prompt_template: str,
    image_client: OpenRouterClient,
    output_dir: Path,
    image_model: str,
    image_provider: str,
    image_max_tokens: int | None,
    apply_logo_overlay_enabled: bool = True,
    logo_path: Path = DEFAULT_LOGO_PATH,
) -> ScoredItem:
    if scored_item.format_selected == "carousel_post":
        carousel_eval = scored_item.evaluation.get("carousel_post") or {}
        slides = normalize_carousel_slides(carousel_eval.get("slides"))
        if not slides:
            raise ValueError(
                f"carousel_post slides missing for item {scored_item.source_index}; run text generation first"
            )
        context = build_post_context(scored_item)
        image_paths, background_paths = generate_carousel_images(
            scored_item,
            carousel_image_prompt_template,
            context,
            slides,
            image_client,
            output_dir=output_dir,
            model=image_model,
            provider=image_provider,
            max_tokens=image_max_tokens,
            apply_logo_overlay_enabled=apply_logo_overlay_enabled,
            logo_path=logo_path,
        )
        item = replace(
            scored_item.item,
            carousel_image_paths=[str(path) for path in image_paths],
            carousel_image_background_paths=[str(path) for path in background_paths],
        )
        return replace(scored_item, item=item)

    caption = scored_item.evaluation.get("post_caption")
    if not isinstance(caption, dict):
        raise ValueError(
            f"post_caption missing for item {scored_item.source_index}; run text generation first"
        )
    context = build_post_context(scored_item)
    image_context = {
        **context,
        "image_headline_fa": caption["image_headline_fa"],
        "image_subline_fa": caption["image_subline_fa"],
        "category_label_fa": caption["category_label_fa"],
    }
    image_path = generate_post_image(
        scored_item,
        image_prompt_template,
        image_context,
        image_client,
        output_dir=output_dir,
        model=image_model,
        provider=image_provider,
        max_tokens=image_max_tokens,
        apply_logo_overlay_enabled=apply_logo_overlay_enabled,
        logo_path=logo_path,
    )
    background_path = ensure_post_image_background_path(scored_item, output_dir)
    item = replace(
        scored_item.item,
        post_image_path=str(image_path),
        post_image_background_path=str(background_path),
    )
    return replace(scored_item, item=item)


def generate_carousel_content(
    scored_item: ScoredItem,
    *,
    content_prompt_template: str,
    image_prompt_template: str,
    caption_client: OpenRouterClient,
    image_client: OpenRouterClient,
    output_dir: Path,
    image_model: str,
    image_provider: str,
    caption_max_tokens: int,
    image_max_tokens: int | None,
    apply_logo_overlay_enabled: bool = True,
    logo_path: Path = DEFAULT_LOGO_PATH,
    generate_images: bool = False,
) -> ScoredItem:
    context = build_post_context(scored_item)
    carousel = generate_carousel_plan(
        content_prompt_template,
        context,
        caption_client,
        max_tokens=max(caption_max_tokens, 1400),
    )
    slides = normalize_carousel_slides(carousel.get("slides"))
    item = replace(
        scored_item.item,
        post_caption_fa=str(carousel.get("caption_fa") or ""),
    )
    evaluation = {
        **scored_item.evaluation,
        "carousel_post": {
            **carousel,
            "slides": slides,
        },
    }
    updated = replace(scored_item, item=item, evaluation=evaluation)
    if not generate_images:
        return updated

    image_paths, background_paths = generate_carousel_images(
        updated,
        image_prompt_template,
        context,
        slides,
        image_client,
        output_dir=output_dir,
        model=image_model,
        provider=image_provider,
        max_tokens=image_max_tokens,
        apply_logo_overlay_enabled=apply_logo_overlay_enabled,
        logo_path=logo_path,
    )
    item = replace(
        updated.item,
        carousel_image_paths=[str(path) for path in image_paths],
        carousel_image_background_paths=[str(path) for path in background_paths],
    )
    return replace(updated, item=item)


def build_post_context(scored_item: ScoredItem) -> dict[str, Any]:
    item = scored_item.item
    return {
        "format_selected": scored_item.format_selected,
        "title": item.title,
        "description": item.description,
        "date": item.date,
        "article_content": item.article_content,
        "category": scored_item.evaluation.get("category"),
        "overall_score": scored_item.overall_score,
        "persian_angle": scored_item.evaluation.get("persian_angle"),
        "reason_en": scored_item.evaluation.get("reason_en"),
        "selection_gate_reasons": scored_item.evaluation.get("selection_gate_reasons"),
        "editorial_adjustment_reasons": scored_item.evaluation.get("editorial_adjustment_reasons"),
    }


def _leading_caption_marker(text: str) -> tuple[str | None, str]:
    stripped = text.lstrip()
    for marker in CAPTION_BULLET_MARKERS:
        if stripped.startswith(marker):
            remainder = stripped[len(marker) :].lstrip()
            return marker, remainder
    return None, stripped


def _split_dense_caption_body(body: str, *, target_points: int = 4) -> str:
    """Turn a single long caption paragraph into 3-5 Instagram bullet blocks."""
    first_marker, remainder = _leading_caption_marker(body)
    sentences = [part.strip() for part in re.split(r"(?<=[\.۔!\?])\s+", remainder) if part.strip()]
    if len(sentences) <= 1:
        return body

    chunk_size = max(1, (len(sentences) + target_points - 1) // target_points)
    chunks: list[str] = []
    for index in range(0, len(sentences), chunk_size):
        chunk = " ".join(sentences[index : index + chunk_size]).strip()
        if chunk:
            chunks.append(chunk)

    point_markers = ["📌", "✅", "🗓️", "📍", "🔎"]
    lines: list[str] = []
    for index, chunk in enumerate(chunks):
        marker = first_marker if index == 0 and first_marker else point_markers[min(index, len(point_markers) - 1)]
        lines.append(f"{marker} {chunk}")
    return "\n\n".join(lines)


def normalize_caption_fa(caption: str) -> str:
    """Ensure blank lines between Instagram caption bullet blocks and before hashtags."""
    text = caption.strip().replace("\\n\\n", "\n\n").replace("\\n", "\n")
    if not text:
        return text

    hashtag_index = text.find("#")
    if hashtag_index >= 0:
        body = text[:hashtag_index].rstrip()
        hashtags = text[hashtag_index:].strip()
    else:
        body = text
        hashtags = ""

    for marker in CAPTION_BULLET_MARKERS:
        body = re.sub(rf"(?<!\n)\s*({re.escape(marker)})", r"\n\n\1", body)

    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    bullet_count = sum(body.count(marker) for marker in CAPTION_BULLET_MARKERS)
    if bullet_count <= 1 and len(body) > 180:
        body = _split_dense_caption_body(body)

    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if hashtags:
        return f"{body}\n\n{hashtags}" if body else hashtags
    return body


def generate_post_caption(
    prompt_template: str,
    context: dict[str, Any],
    client: OpenRouterClient,
    *,
    max_tokens: int,
) -> dict[str, str]:
    prompt = prompt_template.replace("{{POST_CONTEXT}}", json.dumps(context, ensure_ascii=False, indent=2))
    try:
        raw_response = client.ask(
            prompt,
            temperature=0.4,
            max_tokens=max_tokens,
            extra_body={
                "response_format": caption_response_format(),
                "provider": {
                    "require_parameters": True,
                },
            },
        )
    except OpenRouterError as exc:
        if not is_unsupported_structured_output_error(exc):
            raise
        raw_response = client.ask(prompt, temperature=0.4, max_tokens=max_tokens)
    parsed = parse_json_object(raw_response)
    result = {key: str(parsed.get(key) or "") for key in CAPTION_RESPONSE_SCHEMA["required"]}
    result["caption_fa"] = normalize_caption_fa(result["caption_fa"])
    return result


def generate_carousel_plan(
    prompt_template: str,
    context: dict[str, Any],
    client: OpenRouterClient,
    *,
    max_tokens: int,
) -> dict[str, Any]:
    prompt = prompt_template.replace("{{POST_CONTEXT}}", json.dumps(context, ensure_ascii=False, indent=2))
    try:
        raw_response = client.ask(
            prompt,
            temperature=0.35,
            max_tokens=max_tokens,
            extra_body={
                "response_format": carousel_response_format(),
                "provider": {
                    "require_parameters": True,
                },
            },
        )
    except OpenRouterError as exc:
        if not is_unsupported_structured_output_error(exc):
            raise
        raw_response = client.ask(prompt, temperature=0.35, max_tokens=max_tokens)
    parsed = parse_json_object(raw_response)
    return {
        "caption_fa": normalize_caption_fa(str(parsed.get("caption_fa") or "")),
        "short_alt_text_fa": str(parsed.get("short_alt_text_fa") or ""),
        "slides": normalize_carousel_slides(parsed.get("slides")),
    }


def normalize_carousel_slides(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f"Carousel slides must be a list: {value!r}")
    slides: list[dict[str, str]] = []
    for raw_slide in value:
        if not isinstance(raw_slide, dict):
            continue
        slide = {
            "headline_fa": str(raw_slide.get("headline_fa") or "").strip(),
            "body_fa": str(raw_slide.get("body_fa") or "").strip(),
            "category_label_fa": str(raw_slide.get("category_label_fa") or "").strip(),
            "visual_direction": str(raw_slide.get("visual_direction") or "").strip(),
        }
        if slide["headline_fa"] and slide["body_fa"]:
            slides.append(slide)
    if not 3 <= len(slides) <= 6:
        raise ValueError(f"Carousel must have 3-6 usable slides, got {len(slides)}")
    return slides


def build_carousel_image_context(
    context: dict[str, Any],
    slide: dict[str, str],
    *,
    slide_number: int,
    slide_count: int,
) -> dict[str, Any]:
    """Image-model context without JSON field names that leak into rendered text."""
    image_context: dict[str, Any] = {
        "slide_number": slide_number,
        "slide_count": slide_count,
        "headline": slide["headline_fa"],
        "body": slide["body_fa"],
    }
    if slide_number == 1 and slide["category_label_fa"]:
        image_context["upper_right_badge_text"] = slide["category_label_fa"]
    if slide["visual_direction"]:
        image_context["scene_notes"] = slide["visual_direction"]
    image_context["is_first_slide"] = slide_number == 1
    image_context["show_upper_right_badge"] = slide_number == 1 and bool(slide["category_label_fa"])
    topic: dict[str, Any] = {
        "title": context.get("title"),
        "persian_angle": context.get("persian_angle"),
    }
    return {"topic": topic, "slide": image_context}


def carousel_slide_background_path_for(
    scored_item: ScoredItem,
    slide_number: int,
    output_dir: Path,
    *,
    extension: str,
) -> Path:
    return output_dir / f"{carousel_slide_filename_stem(scored_item, slide_number)}-bg.{extension}"


def carousel_slide_final_path_for(
    scored_item: ScoredItem,
    slide_number: int,
    output_dir: Path,
    *,
    extension: str = "jpg",
) -> Path:
    return output_dir / f"{carousel_slide_filename_stem(scored_item, slide_number)}.{extension}"


def post_image_background_path_for(scored_item: ScoredItem, output_dir: Path, *, extension: str) -> Path:
    return output_dir / f"{post_image_filename_stem(scored_item)}-bg.{extension}"


def post_image_final_path_for(scored_item: ScoredItem, output_dir: Path, *, extension: str = "jpg") -> Path:
    return output_dir / f"{post_image_filename_stem(scored_item)}.{extension}"


def post_overlay_text_from_context(context: dict[str, Any]) -> OverlayText:
    return OverlayText(
        kicker=str(context.get("category_label_fa") or "").strip(),
        title=str(context.get("image_headline_fa") or "").strip(),
        body=str(context.get("image_subline_fa") or "").strip(),
    )


def post_overlay_text_from_item(scored_item: ScoredItem) -> OverlayText | None:
    caption = scored_item.evaluation.get("post_caption")
    if not isinstance(caption, dict):
        return None
    overlay = post_overlay_text_from_context(caption)
    if not overlay.title:
        return None
    return overlay


def composite_post_image_from_background(
    background_path: Path,
    output_path: Path,
    overlay: OverlayText,
    *,
    apply_logo_overlay_enabled: bool,
    logo_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not overlay.title:
        shutil.copyfile(background_path, output_path)
    else:
        render_overlay(background_path, output_path, overlay, show_kicker=bool(overlay.kicker))
    if apply_logo_overlay_enabled:
        apply_logo_overlay(output_path, logo_path=logo_path)
    return output_path


def ensure_post_image_background_path(scored_item: ScoredItem, output_dir: Path) -> Path:
    raw_background = scored_item.item.post_image_background_path
    if raw_background:
        existing = Path(raw_background)
        if existing.is_file():
            return existing.resolve()
    for extension in ("jpg", "jpeg", "png", "webp"):
        candidate = post_image_background_path_for(scored_item, output_dir, extension=extension)
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError(
        f"Post image background is missing for item {scored_item.source_index}. "
        "Regenerate the post image first."
    )


def refresh_post_image_overlay(
    scored_item: ScoredItem,
    *,
    output_dir: Path,
    apply_logo_overlay_enabled: bool,
    logo_path: Path,
) -> tuple[Path, Path]:
    overlay = post_overlay_text_from_item(scored_item)
    if overlay is None:
        raise ValueError("Post overlay text is missing. Regenerate text first.")

    background_path = ensure_post_image_background_path(scored_item, output_dir)
    if scored_item.item.post_image_path:
        final_path = Path(scored_item.item.post_image_path)
    else:
        final_path = post_image_final_path_for(scored_item, output_dir)
    composite_post_image_from_background(
        background_path,
        final_path,
        overlay,
        apply_logo_overlay_enabled=apply_logo_overlay_enabled,
        logo_path=logo_path,
    )
    return final_path, background_path


def carousel_overlay_text_from_slide(
    slide: dict[str, str],
    *,
    slide_number: int,
    scored_item: ScoredItem,
) -> OverlayText:
    slide = slide_for_carousel_image(scored_item, slide, slide_number=slide_number)
    kicker = ""
    if slide_number == 1:
        kicker = str(slide.get("category_label_fa") or "").strip()
    return OverlayText(
        kicker=kicker,
        title=str(slide.get("headline_fa") or "").strip(),
        body=str(slide.get("body_fa") or "").strip(),
    )


def composite_carousel_slide_from_background(
    scored_item: ScoredItem,
    slide: dict[str, str],
    *,
    slide_number: int,
    background_path: Path,
    output_path: Path,
    apply_logo_overlay_enabled: bool,
    logo_path: Path,
) -> Path:
    overlay = carousel_overlay_text_from_slide(slide, slide_number=slide_number, scored_item=scored_item)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not overlay.title:
        shutil.copyfile(background_path, output_path)
    else:
        render_overlay(
            background_path,
            output_path,
            overlay,
            show_kicker=slide_number == 1 and bool(overlay.kicker),
        )
    if apply_logo_overlay_enabled:
        apply_logo_overlay(output_path, logo_path=logo_path)
    return output_path


def ensure_carousel_slide_background_path(
    scored_item: ScoredItem,
    slide_number: int,
    output_dir: Path,
) -> Path:
    background_paths = scored_item.item.carousel_image_background_paths or []
    if slide_number - 1 < len(background_paths):
        existing = Path(background_paths[slide_number - 1])
        if existing.is_file():
            return existing.resolve()
    for extension in ("jpg", "jpeg", "png", "webp"):
        candidate = carousel_slide_background_path_for(
            scored_item,
            slide_number,
            output_dir,
            extension=extension,
        )
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError(
        f"Carousel slide {slide_number} background is missing for item {scored_item.source_index}. "
        "Regenerate the slide image first."
    )


def refresh_carousel_image_overlays(
    scored_item: ScoredItem,
    *,
    output_dir: Path,
    apply_logo_overlay_enabled: bool,
    logo_path: Path,
) -> tuple[list[Path], list[Path]]:
    carousel_eval = scored_item.evaluation.get("carousel_post") or {}
    slides = normalize_carousel_slides(carousel_eval.get("slides"))
    if not slides:
        raise ValueError("Carousel slide text is missing. Regenerate text first.")

    existing_final_paths = [Path(path) for path in (scored_item.item.carousel_image_paths or []) if path]
    final_paths: list[Path] = []
    background_paths: list[Path] = []
    for index, slide in enumerate(slides):
        slide_number = index + 1
        background_path = ensure_carousel_slide_background_path(scored_item, slide_number, output_dir)
        if index < len(existing_final_paths):
            final_path = existing_final_paths[index]
        else:
            final_path = carousel_slide_final_path_for(scored_item, slide_number, output_dir)
        composite_carousel_slide_from_background(
            scored_item,
            slide,
            slide_number=slide_number,
            background_path=background_path,
            output_path=final_path,
            apply_logo_overlay_enabled=apply_logo_overlay_enabled,
            logo_path=logo_path,
        )
        background_paths.append(background_path)
        final_paths.append(final_path)
    return final_paths, background_paths


def generate_carousel_images(
    scored_item: ScoredItem,
    prompt_template: str,
    context: dict[str, Any],
    slides: list[dict[str, str]],
    client: OpenRouterClient,
    *,
    output_dir: Path,
    model: str,
    provider: str,
    max_tokens: int | None,
    apply_logo_overlay_enabled: bool,
    logo_path: Path,
) -> tuple[list[Path], list[Path]]:
    final_results: list[Path | None] = [None] * len(slides)
    background_results: list[Path | None] = [None] * len(slides)

    def generate_indexed_slide(index: int, slide: dict[str, str]) -> tuple[int, Path, Path]:
        background_path, final_path = generate_carousel_slide_image(
            scored_item,
            prompt_template,
            context,
            slide,
            slide_number=index + 1,
            slide_count=len(slides),
            client=client,
            output_dir=output_dir,
            model=model,
            provider=provider,
            max_tokens=max_tokens,
            apply_logo_overlay_enabled=apply_logo_overlay_enabled,
            logo_path=logo_path,
        )
        return index, background_path, final_path

    max_workers = max(1, min(len(slides), 4))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(generate_indexed_slide, index, slide): index
            for index, slide in enumerate(slides)
        }
        for future in concurrent.futures.as_completed(futures):
            index, background_path, final_path = future.result()
            background_results[index] = background_path
            final_results[index] = final_path

    if any(path is None for path in final_results):
        raise ValueError(f"Carousel image generation incomplete for item {scored_item.source_index}")
    return final_results, background_results  # type: ignore[return-value]


def slide_for_carousel_image(
    scored_item: ScoredItem,
    slide: dict[str, str],
    *,
    slide_number: int,
) -> dict[str, str]:
    if slide_number != 1:
        return slide
    caption = scored_item.evaluation.get("post_caption")
    if not isinstance(caption, dict):
        return slide
    headline = str(caption.get("image_headline_fa") or "").strip()
    if not headline:
        return slide
    return {
        **slide,
        "headline_fa": headline,
        "body_fa": str(caption.get("image_subline_fa") or slide.get("body_fa") or "").strip(),
        "category_label_fa": str(caption.get("category_label_fa") or slide.get("category_label_fa") or "").strip(),
    }


def generate_carousel_slide_image(
    scored_item: ScoredItem,
    prompt_template: str,
    context: dict[str, Any],
    slide: dict[str, str],
    *,
    slide_number: int,
    slide_count: int,
    client: OpenRouterClient,
    output_dir: Path,
    model: str,
    provider: str,
    max_tokens: int | None,
    apply_logo_overlay_enabled: bool,
    logo_path: Path,
) -> tuple[Path, Path]:
    slide = slide_for_carousel_image(scored_item, slide, slide_number=slide_number)
    slide_context = build_carousel_image_context(
        context,
        slide,
        slide_number=slide_number,
        slide_count=slide_count,
    )
    prompt = prompt_template.replace("{{CAROUSEL_CONTEXT}}", json.dumps(slide_context, ensure_ascii=False, indent=2))
    if provider == "gemini":
        response = post_gemini_image_request_with_config(
            prompt,
            model=model,
            timeout=client.timeout,
            aspect_ratio="4:5",
        )
        inline_data, assistant_text = extract_gemini_inline_image(response)
        extension = extension_for_mime_type(inline_data["mime_type"])
        background_path = carousel_slide_background_path_for(
            scored_item,
            slide_number,
            output_dir,
            extension=extension,
        )
        background_path.parent.mkdir(parents=True, exist_ok=True)
        background_path.write_bytes(base64.b64decode(inline_data["data"]))
        final_path = carousel_slide_final_path_for(scored_item, slide_number, output_dir, extension="jpg")
        composite_carousel_slide_from_background(
            scored_item,
            slide,
            slide_number=slide_number,
            background_path=background_path,
            output_path=final_path,
            apply_logo_overlay_enabled=apply_logo_overlay_enabled,
            logo_path=logo_path,
        )
        write_carousel_slide_summary(
            final_path,
            scored_item,
            model,
            slide,
            slide_number,
            slide_count,
            response.get("usageMetadata"),
            assistant_text,
            background_path=background_path,
        )
        return background_path, final_path

    if provider != "openrouter":
        raise ValueError(f"Unsupported carousel image provider: {provider}")

    body = build_openrouter_image_request_body(model=model, prompt=prompt, aspect_ratio="4:5")
    response = post_openrouter_image_request(client, body)
    message = response.get("choices", [{}])[0].get("message", {})
    images = message.get("images") or []
    if not images:
        raise OpenRouterError(f"OpenRouter returned no carousel slide images: {response}")
    image_url = images[0].get("image_url", {}).get("url")
    if not isinstance(image_url, str):
        raise OpenRouterError(f"OpenRouter returned unexpected carousel image payload: {images[0]!r}")
    mime, payload = parse_data_url(image_url)
    extension = extension_for_mime_type(mime)
    background_path = carousel_slide_background_path_for(
        scored_item,
        slide_number,
        output_dir,
        extension=extension,
    )
    background_path.parent.mkdir(parents=True, exist_ok=True)
    background_path.write_bytes(base64.b64decode(payload))
    final_path = carousel_slide_final_path_for(scored_item, slide_number, output_dir, extension="jpg")
    composite_carousel_slide_from_background(
        scored_item,
        slide,
        slide_number=slide_number,
        background_path=background_path,
        output_path=final_path,
        apply_logo_overlay_enabled=apply_logo_overlay_enabled,
        logo_path=logo_path,
    )
    write_carousel_slide_summary(
        final_path,
        scored_item,
        model,
        slide,
        slide_number,
        slide_count,
        response.get("usage"),
        message.get("content"),
        background_path=background_path,
    )
    return background_path, final_path


def generate_post_image(
    scored_item: ScoredItem,
    prompt_template: str,
    context: dict[str, Any],
    client: OpenRouterClient,
    *,
    output_dir: Path,
    model: str = DEFAULT_STORY_IMAGE_MODEL,
    provider: str = DEFAULT_STORY_IMAGE_PROVIDER,
    max_tokens: int | None = 12000,
    apply_logo_overlay_enabled: bool = True,
    logo_path: Path = DEFAULT_LOGO_PATH,
) -> Path:
    prompt = prompt_template.replace("{{POST_CONTEXT}}", json.dumps(context, ensure_ascii=False, indent=2))
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay = post_overlay_text_from_context(context)
    if provider == "gemini":
        response = post_gemini_image_request_with_config(
            prompt,
            model=model,
            timeout=client.timeout,
            aspect_ratio="4:5",
        )
        inline_data, assistant_text = extract_gemini_inline_image(response)
        extension = extension_for_mime_type(inline_data["mime_type"])
        background_path = post_image_background_path_for(scored_item, output_dir, extension=extension)
        background_path.write_bytes(base64.b64decode(inline_data["data"]))
        final_path = post_image_final_path_for(scored_item, output_dir, extension="jpg")
        composite_post_image_from_background(
            background_path,
            final_path,
            overlay,
            apply_logo_overlay_enabled=apply_logo_overlay_enabled,
            logo_path=logo_path,
        )
        write_post_image_summary(
            final_path,
            scored_item,
            model,
            response.get("usageMetadata"),
            assistant_text,
            background_path=background_path,
        )
        return final_path

    if provider != "openrouter":
        raise ValueError(f"Unsupported post image provider: {provider}")

    body = build_openrouter_image_request_body(model=model, prompt=prompt, aspect_ratio="4:5")
    response = post_openrouter_image_request(client, body)
    message = response.get("choices", [{}])[0].get("message", {})
    images = message.get("images") or []
    if not images:
        raise OpenRouterError(f"OpenRouter returned no post images: {response}")
    image_url = images[0].get("image_url", {}).get("url")
    if not isinstance(image_url, str):
        raise OpenRouterError(f"OpenRouter returned unexpected post image payload: {images[0]!r}")
    mime, payload = parse_data_url(image_url)
    extension = extension_for_mime_type(mime)
    background_path = post_image_background_path_for(scored_item, output_dir, extension=extension)
    background_path.write_bytes(base64.b64decode(payload))
    final_path = post_image_final_path_for(scored_item, output_dir, extension="jpg")
    composite_post_image_from_background(
        background_path,
        final_path,
        overlay,
        apply_logo_overlay_enabled=apply_logo_overlay_enabled,
        logo_path=logo_path,
    )
    write_post_image_summary(
        final_path,
        scored_item,
        model,
        response.get("usage"),
        message.get("content"),
        background_path=background_path,
    )
    return final_path


def write_post_image_summary(
    image_path: Path,
    scored_item: ScoredItem,
    model: str,
    usage: Any,
    assistant_content: str | None,
    *,
    background_path: Path | None = None,
) -> None:
    image_path.with_suffix(".response_summary.json").write_text(
        json.dumps(
            {
                "model": model,
                "source_index": scored_item.source_index,
                "title": scored_item.item.title,
                "post_image_path": str(image_path),
                "post_image_background_path": str(background_path) if background_path else None,
                "usage": usage,
                "assistant_content": assistant_content,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def write_carousel_slide_summary(
    image_path: Path,
    scored_item: ScoredItem,
    model: str,
    slide: dict[str, str],
    slide_number: int,
    slide_count: int,
    usage: Any,
    assistant_content: str | None,
    *,
    background_path: Path | None = None,
) -> None:
    image_path.with_suffix(".response_summary.json").write_text(
        json.dumps(
            {
                "model": model,
                "source_index": scored_item.source_index,
                "title": scored_item.item.title,
                "carousel_slide_image_path": str(image_path),
                "carousel_slide_background_path": str(background_path) if background_path else None,
                "slide_number": slide_number,
                "slide_count": slide_count,
                "slide": slide,
                "usage": usage,
                "assistant_content": assistant_content,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def post_image_filename_stem(scored_item: ScoredItem) -> str:
    title = scored_item.item.title or "post"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:70].strip("-") or "post"
    return f"post-{scored_item.source_index}-{slug}"


def carousel_slide_filename_stem(scored_item: ScoredItem, slide_number: int) -> str:
    title = scored_item.item.title or "carousel"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:62].strip("-") or "carousel"
    return f"carousel-{scored_item.source_index}-{slide_number:02d}-{slug}"

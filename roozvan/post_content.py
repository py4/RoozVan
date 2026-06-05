"""Post image and caption generation for selected RoozVan post items."""

from __future__ import annotations

import base64
import concurrent.futures
import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from openrouter_client import OpenRouterClient, OpenRouterError
from roozvan.logo_overlay import DEFAULT_LOGO_PATH, apply_logo_overlay
from roozvan.models import ScoredItem
from roozvan.scoring import is_unsupported_structured_output_error, parse_json_object
from roozvan.story_images import (
    DEFAULT_GEMINI_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_MODEL,
    build_openrouter_image_request_body,
    extension_for_mime_type,
    extract_gemini_inline_image,
    parse_data_url,
    post_gemini_image_request_with_config,
    post_openrouter_image_request,
)

# Instagram-friendly bullets the caption formatter recognizes.
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


def generate_post_content_for_scored_items(
    items: list[ScoredItem],
    *,
    image_prompt_template: str,
    caption_prompt_template: str,
    carousel_content_prompt_template: str,
    carousel_image_prompt_template: str,
    caption_client: OpenRouterClient,
    image_client: OpenRouterClient,
    output_dir: Path,
    image_model: str = DEFAULT_STORY_IMAGE_MODEL,
    image_provider: str = "gemini",
    caption_max_tokens: int = 900,
    image_max_tokens: int | None = 12000,
    workers: int = 4,
    apply_logo_overlay_enabled: bool = True,
    logo_path: Path = DEFAULT_LOGO_PATH,
    generate_images: bool = False,
    generate_carousel_content: bool = False,
) -> list[ScoredItem]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[ScoredItem | None] = [None] * len(items)

    def generate_indexed_post(index: int, scored_item: ScoredItem) -> tuple[int, ScoredItem]:
        if scored_item.format_selected not in {"post", "carousel_post"}:
            return index, scored_item
        if scored_item.format_selected == "carousel_post" and not generate_carousel_content:
            return index, scored_item
        completed = generate_post_content(
            scored_item,
            image_prompt_template=image_prompt_template,
            caption_prompt_template=caption_prompt_template,
            carousel_content_prompt_template=carousel_content_prompt_template,
            carousel_image_prompt_template=carousel_image_prompt_template,
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
        return index, completed

    max_workers = max(1, min(workers, len(items) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(generate_indexed_post, index, scored_item): (index, scored_item)
            for index, scored_item in enumerate(items)
        }
        for future in concurrent.futures.as_completed(futures):
            index, scored_item = futures[future]
            try:
                completed_index, completed_item = future.result()
            except (OpenRouterError, ValueError, json.JSONDecodeError) as exc:
                print(
                    f"warning: failed to generate post content for item {scored_item.source_index} "
                    f"({scored_item.item.title}): {exc}",
                    file=sys.stderr,
                )
                results[index] = scored_item
            except Exception as exc:  # noqa: BLE001 - pipeline should continue on one failed post.
                print(
                    f"warning: unexpected failure generating post content for item {scored_item.source_index} "
                    f"({scored_item.item.title}): {exc}",
                    file=sys.stderr,
                )
                results[index] = scored_item
            else:
                results[completed_index] = completed_item

    return [item for item in results if item is not None]


def generate_post_images_for_scored_items(
    items: list[ScoredItem],
    *,
    image_prompt_template: str,
    carousel_image_prompt_template: str,
    image_client: OpenRouterClient,
    output_dir: Path,
    image_model: str = DEFAULT_STORY_IMAGE_MODEL,
    image_provider: str = "gemini",
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
    item = replace(updated.item, post_image_path=str(image_path))
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
        image_paths = generate_carousel_images(
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
    item = replace(scored_item.item, post_image_path=str(image_path))
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

    image_paths = generate_carousel_images(
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
) -> list[Path]:
    results: list[Path | None] = [None] * len(slides)

    def generate_indexed_slide(index: int, slide: dict[str, str]) -> tuple[int, Path]:
        return index, generate_carousel_slide_image(
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

    max_workers = max(1, min(len(slides), 4))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(generate_indexed_slide, index, slide): index
            for index, slide in enumerate(slides)
        }
        for future in concurrent.futures.as_completed(futures):
            index, path = future.result()
            results[index] = path

    return [path for path in results if path is not None]


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
) -> Path:
    slide_context = build_carousel_image_context(
        context,
        slide,
        slide_number=slide_number,
        slide_count=slide_count,
    )
    prompt = prompt_template.replace("{{CAROUSEL_CONTEXT}}", json.dumps(slide_context, ensure_ascii=False, indent=2))
    output_path = output_dir / f"{carousel_slide_filename_stem(scored_item, slide_number)}"
    if provider == "gemini":
        response = post_gemini_image_request_with_config(
            prompt,
            model=model,
            timeout=client.timeout,
            aspect_ratio="4:5",
        )
        inline_data, assistant_text = extract_gemini_inline_image(response)
        extension = extension_for_mime_type(inline_data["mime_type"])
        final_path = output_path.with_suffix(f".{extension}")
        final_path.write_bytes(base64.b64decode(inline_data["data"]))
        write_carousel_slide_summary(
            final_path,
            scored_item,
            model,
            slide,
            slide_number,
            slide_count,
            response.get("usageMetadata"),
            assistant_text,
        )
        if apply_logo_overlay_enabled:
            apply_logo_overlay(final_path, logo_path=logo_path)
        return final_path

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
    final_path = output_path.with_suffix(f".{extension}")
    final_path.write_bytes(base64.b64decode(payload))
    write_carousel_slide_summary(
        final_path,
        scored_item,
        model,
        slide,
        slide_number,
        slide_count,
        response.get("usage"),
        message.get("content"),
    )
    if apply_logo_overlay_enabled:
        apply_logo_overlay(final_path, logo_path=logo_path)
    return final_path


def generate_post_image(
    scored_item: ScoredItem,
    prompt_template: str,
    context: dict[str, Any],
    client: OpenRouterClient,
    *,
    output_dir: Path,
    model: str = DEFAULT_STORY_IMAGE_MODEL,
    provider: str = "gemini",
    max_tokens: int | None = 12000,
    apply_logo_overlay_enabled: bool = True,
    logo_path: Path = DEFAULT_LOGO_PATH,
) -> Path:
    prompt = prompt_template.replace("{{POST_CONTEXT}}", json.dumps(context, ensure_ascii=False, indent=2))
    output_path = output_dir / f"{post_image_filename_stem(scored_item)}"
    if provider == "gemini":
        response = post_gemini_image_request_with_config(
            prompt,
            model=model,
            timeout=client.timeout,
            aspect_ratio="4:5",
        )
        inline_data, assistant_text = extract_gemini_inline_image(response)
        extension = extension_for_mime_type(inline_data["mime_type"])
        final_path = output_path.with_suffix(f".{extension}")
        final_path.write_bytes(base64.b64decode(inline_data["data"]))
        write_post_image_summary(final_path, scored_item, model, response.get("usageMetadata"), assistant_text)
        if apply_logo_overlay_enabled:
            apply_logo_overlay(final_path, logo_path=logo_path)
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
    final_path = output_path.with_suffix(f".{extension}")
    final_path.write_bytes(base64.b64decode(payload))
    write_post_image_summary(final_path, scored_item, model, response.get("usage"), message.get("content"))
    if apply_logo_overlay_enabled:
        apply_logo_overlay(final_path, logo_path=logo_path)
    return final_path


def write_post_image_summary(
    image_path: Path,
    scored_item: ScoredItem,
    model: str,
    usage: Any,
    assistant_content: str | None,
) -> None:
    image_path.with_suffix(".response_summary.json").write_text(
        json.dumps(
            {
                "model": model,
                "source_index": scored_item.source_index,
                "title": scored_item.item.title,
                "post_image_path": str(image_path),
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
) -> None:
    image_path.with_suffix(".response_summary.json").write_text(
        json.dumps(
            {
                "model": model,
                "source_index": scored_item.source_index,
                "title": scored_item.item.title,
                "carousel_slide_image_path": str(image_path),
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

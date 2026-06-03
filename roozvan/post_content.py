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
from roozvan.models import ScoredItem
from roozvan.scoring import is_unsupported_structured_output_error, parse_json_object
from roozvan.story_images import (
    DEFAULT_GEMINI_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_MODEL,
    extension_for_mime_type,
    extract_gemini_inline_image,
    parse_data_url,
    post_gemini_image_request_with_config,
    post_openrouter_image_request,
)


CAPTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "caption_fa": {"type": "string"},
        "short_alt_text_fa": {"type": "string"},
        "image_headline_fa": {"type": "string"},
        "image_subline_fa": {"type": "string"},
        "category_label_fa": {"type": "string"},
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


def caption_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "instagram_post_caption",
            "strict": True,
            "schema": CAPTION_RESPONSE_SCHEMA,
        },
    }


def generate_post_content_for_scored_items(
    items: list[ScoredItem],
    *,
    image_prompt_template: str,
    caption_prompt_template: str,
    caption_client: OpenRouterClient,
    image_client: OpenRouterClient,
    output_dir: Path,
    image_model: str = DEFAULT_STORY_IMAGE_MODEL,
    image_provider: str = "openrouter",
    caption_max_tokens: int = 900,
    image_max_tokens: int | None = 12000,
    workers: int = 4,
) -> list[ScoredItem]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[ScoredItem | None] = [None] * len(items)

    def generate_indexed_post(index: int, scored_item: ScoredItem) -> tuple[int, ScoredItem]:
        if scored_item.format_selected != "post":
            return index, scored_item
        completed = generate_post_content(
            scored_item,
            image_prompt_template=image_prompt_template,
            caption_prompt_template=caption_prompt_template,
            caption_client=caption_client,
            image_client=image_client,
            output_dir=output_dir,
            image_model=image_model,
            image_provider=image_provider,
            caption_max_tokens=caption_max_tokens,
            image_max_tokens=image_max_tokens,
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


def generate_post_content(
    scored_item: ScoredItem,
    *,
    image_prompt_template: str,
    caption_prompt_template: str,
    caption_client: OpenRouterClient,
    image_client: OpenRouterClient,
    output_dir: Path,
    image_model: str,
    image_provider: str,
    caption_max_tokens: int,
    image_max_tokens: int | None,
) -> ScoredItem:
    context = build_post_context(scored_item)
    caption = generate_post_caption(
        caption_prompt_template,
        context,
        caption_client,
        max_tokens=caption_max_tokens,
    )
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
    )
    item = replace(
        scored_item.item,
        post_image_path=str(image_path),
        post_caption_fa=caption["caption_fa"],
    )
    evaluation = {
        **scored_item.evaluation,
        "post_caption": caption,
    }
    return replace(scored_item, item=item, evaluation=evaluation)


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
    return {key: str(parsed.get(key) or "") for key in CAPTION_RESPONSE_SCHEMA["required"]}


def generate_post_image(
    scored_item: ScoredItem,
    prompt_template: str,
    context: dict[str, Any],
    client: OpenRouterClient,
    *,
    output_dir: Path,
    model: str = DEFAULT_STORY_IMAGE_MODEL,
    provider: str = "openrouter",
    max_tokens: int | None = 12000,
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
        return final_path

    if provider != "openrouter":
        raise ValueError(f"Unsupported post image provider: {provider}")

    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
        "image_config": {
            "aspect_ratio": "4:5",
            "image_size": "1K",
        },
        "stream": False,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
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


def post_image_filename_stem(scored_item: ScoredItem) -> str:
    title = scored_item.item.title or "post"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:70].strip("-") or "post"
    return f"post-{scored_item.source_index}-{slug}"

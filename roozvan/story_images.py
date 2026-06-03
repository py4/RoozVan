"""Story image generation for selected RoozVan articles."""

from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

from openrouter_client import OpenRouterClient, OpenRouterError, load_default_env_files
from roozvan.models import NewsItem, ScoredItem


DEFAULT_STORY_IMAGE_MODEL = "openai/gpt-5.4-image-2"
DEFAULT_GEMINI_STORY_IMAGE_MODEL = "gemini-3.1-flash-image"


def build_story_image_prompt(prompt_template: str, item: NewsItem) -> str:
    replacements = {
        "{{TITLE}}": item.title or "",
        "{{DESCRIPTION}}": item.description or "",
        "{{ARTICLE}}": item.article_content or "",
    }
    prompt = prompt_template
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    return prompt


def generate_story_images_for_scored_items(
    items: list[ScoredItem],
    prompt_template: str,
    client: OpenRouterClient,
    *,
    output_dir: Path,
    model: str = DEFAULT_STORY_IMAGE_MODEL,
    provider: str = "openrouter",
    max_tokens: int | None = 12000,
    workers: int = 4,
) -> list[ScoredItem]:
    """Generate story images in parallel and return items with story_image_path set."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[ScoredItem | None] = [None] * len(items)

    def generate_indexed_image(index: int, scored_item: ScoredItem) -> tuple[int, ScoredItem]:
        path = generate_story_image(
            scored_item,
            prompt_template,
            client,
            output_dir=output_dir,
            model=model,
            provider=provider,
            max_tokens=max_tokens,
        )
        item = replace(scored_item.item, story_image_path=str(path))
        return index, replace(scored_item, item=item)

    max_workers = max(1, min(workers, len(items) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(generate_indexed_image, index, scored_item): (index, scored_item)
            for index, scored_item in enumerate(items)
        }
        for future in concurrent.futures.as_completed(futures):
            index, scored_item = futures[future]
            try:
                completed_index, completed_item = future.result()
            except (OpenRouterError, ValueError, json.JSONDecodeError) as exc:
                print(
                    f"warning: failed to generate story image for item {scored_item.source_index} "
                    f"({scored_item.item.title}): {exc}",
                    file=sys.stderr,
                )
                results[index] = scored_item
            except Exception as exc:  # noqa: BLE001 - pipeline should continue on one failed image.
                print(
                    f"warning: unexpected failure generating story image for item {scored_item.source_index} "
                    f"({scored_item.item.title}): {exc}",
                    file=sys.stderr,
                )
                results[index] = scored_item
            else:
                results[completed_index] = completed_item

    return [item for item in results if item is not None]


def generate_story_image(
    scored_item: ScoredItem,
    prompt_template: str,
    client: OpenRouterClient,
    *,
    output_dir: Path,
    model: str = DEFAULT_STORY_IMAGE_MODEL,
    provider: str = "openrouter",
    max_tokens: int | None = 12000,
) -> Path:
    prompt = build_story_image_prompt(prompt_template, scored_item.item)
    if provider == "gemini":
        return generate_story_image_with_gemini(
            scored_item,
            prompt,
            output_dir=output_dir,
            model=model,
            timeout=client.timeout,
        )
    if provider != "openrouter":
        raise ValueError(f"Unsupported story image provider: {provider}")

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
        "image_config": {
            "aspect_ratio": "9:16",
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
        raise OpenRouterError(f"OpenRouter returned no images: {response}")

    image_url = images[0].get("image_url", {}).get("url")
    if not isinstance(image_url, str):
        raise OpenRouterError(f"OpenRouter returned unexpected image payload: {images[0]!r}")

    mime, payload = parse_data_url(image_url)
    extension = extension_for_mime_type(mime)
    output_path = output_dir / f"{story_image_filename_stem(scored_item)}.{extension}"
    output_path.write_bytes(base64.b64decode(payload))

    summary_path = output_dir / f"{story_image_filename_stem(scored_item)}.response_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "model": model,
                "source_index": scored_item.source_index,
                "title": scored_item.item.title,
                "story_image_path": str(output_path),
                "usage": response.get("usage"),
                "id": response.get("id"),
                "assistant_content": message.get("content"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output_path


def generate_story_image_with_gemini(
    scored_item: ScoredItem,
    prompt: str,
    *,
    output_dir: Path,
    model: str = DEFAULT_GEMINI_STORY_IMAGE_MODEL,
    timeout: int = 300,
) -> Path:
    response = post_gemini_image_request(prompt, model=model, timeout=timeout)
    inline_data, assistant_text = extract_gemini_inline_image(response)
    mime = inline_data["mime_type"]
    payload = inline_data["data"]
    extension = extension_for_mime_type(mime)
    output_path = output_dir / f"{story_image_filename_stem(scored_item)}.{extension}"
    output_path.write_bytes(base64.b64decode(payload))

    summary_path = output_dir / f"{story_image_filename_stem(scored_item)}.response_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "provider": "gemini",
                "model": model,
                "source_index": scored_item.source_index,
                "title": scored_item.item.title,
                "story_image_path": str(output_path),
                "usage": response.get("usageMetadata"),
                "assistant_content": assistant_text,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output_path


def post_gemini_image_request(prompt: str, *, model: str, timeout: int) -> dict[str, Any]:
    load_default_env_files()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise OpenRouterError("Missing GEMINI_API_KEY.")
    model_name = model.removeprefix("models/")
    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
            "imageConfig": {
                "aspectRatio": "9:16",
                "imageSize": "1K",
            },
        },
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_response = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise OpenRouterError(f"Gemini HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise OpenRouterError(f"Failed to call Gemini: {exc}") from exc

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"Gemini returned invalid JSON: {raw_response}") from exc
    if not isinstance(parsed, dict):
        raise OpenRouterError(f"Gemini returned unexpected JSON: {parsed!r}")
    if "error" in parsed:
        raise OpenRouterError(f"Gemini error: {parsed['error']}")
    return parsed

def extract_gemini_inline_image(response: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    assistant_text = None
    candidates = response.get("candidates") or []
    for candidate in candidates:
        parts = candidate.get("content", {}).get("parts") or []
        for part in parts:
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                assistant_text = text
            inline_data = part.get("inlineData") or part.get("inline_data")
            if isinstance(inline_data, dict):
                mime_type = inline_data.get("mimeType") or inline_data.get("mime_type")
                data = inline_data.get("data")
                if isinstance(mime_type, str) and isinstance(data, str):
                    return {"mime_type": mime_type, "data": data}, assistant_text
    raise OpenRouterError(f"Gemini returned no inline image: {response}")


def post_openrouter_image_request(client: OpenRouterClient, body: dict[str, Any]) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {client.api_key}",
        "Content-Type": "application/json",
    }
    if client.site_url:
        headers["HTTP-Referer"] = client.site_url
    if client.app_name:
        headers["X-Title"] = client.app_name

    request = urllib.request.Request(
        client.base_url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=client.timeout) as response:
            raw_response = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise OpenRouterError(f"OpenRouter HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise OpenRouterError(f"Failed to call OpenRouter: {exc}") from exc

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(f"OpenRouter returned invalid JSON: {raw_response}") from exc
    if not isinstance(parsed, dict):
        raise OpenRouterError(f"OpenRouter returned unexpected JSON: {parsed!r}")
    if "error" in parsed:
        raise OpenRouterError(f"OpenRouter error: {parsed['error']}")
    return parsed


def parse_data_url(value: str) -> tuple[str, str]:
    match = re.match(r"data:(image/[^;]+);base64,(.*)", value, re.S)
    if not match:
        raise OpenRouterError(f"Unexpected image URL format: {value[:120]}")
    return match.group(1), match.group(2)


def extension_for_mime_type(mime_type: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
        "image/svg+xml": "svg",
    }.get(mime_type, "img")


def story_image_filename_stem(scored_item: ScoredItem) -> str:
    title = scored_item.item.title or "story"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:70].strip("-") or "story"
    return f"story-{scored_item.source_index}-{slug}"

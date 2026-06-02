"""Instagram format selection for selected RoozVan items."""

from __future__ import annotations

import concurrent.futures
import json
import sys
from dataclasses import replace
from typing import Any

from openrouter_client import OpenRouterClient, OpenRouterError
from roozvan.models import NewsItem, ScoredItem
from roozvan.scoring import parse_json_object


ALLOWED_SELECTED_FORMATS = {"post", "story", "carousel_post"}

FORMAT_SELECTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "format": {"type": "string", "enum": sorted(ALLOWED_SELECTED_FORMATS)},
    },
    "required": ["format"],
    "additionalProperties": False,
}


def format_selection_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "instagram_format_selection",
            "strict": True,
            "schema": FORMAT_SELECTION_RESPONSE_SCHEMA,
        },
    }


def build_format_selection_prompt(instruction: str, item: NewsItem) -> str:
    candidate = {
        "title": item.title,
        "caption": item.description,
        "article_content": item.article_content,
    }
    return (
        f"{instruction.strip()}\n\n"
        "Classify this candidate:\n"
        f"{json.dumps(candidate, ensure_ascii=False, indent=2)}\n\n"
        "Return only one valid JSON object matching the schema."
    )


def select_format(
    client: OpenRouterClient,
    instruction: str,
    item: NewsItem,
    *,
    max_tokens: int,
) -> str:
    raw_response = client.ask(
        build_format_selection_prompt(instruction, item),
        temperature=0,
        max_tokens=max_tokens,
        extra_body={
            "response_format": format_selection_response_format(),
            "provider": {
                "require_parameters": True,
            },
        },
    )
    selected = parse_json_object(raw_response).get("format")
    if selected not in ALLOWED_SELECTED_FORMATS:
        raise ValueError(f"Invalid selected format: {selected!r}")
    return selected


def select_formats_for_scored_items(
    items: list[ScoredItem],
    instruction: str,
    client: OpenRouterClient,
    *,
    max_tokens: int,
    workers: int,
) -> list[ScoredItem]:
    if not items:
        return []

    results: list[ScoredItem | None] = [None] * len(items)
    worker_count = max(1, min(workers, len(items)))

    def select_indexed_format(index: int, scored_item: ScoredItem) -> tuple[int, ScoredItem]:
        selected = select_format(client, instruction, scored_item.item, max_tokens=max_tokens)
        return index, replace(scored_item, format_selected=selected)

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(select_indexed_format, index, scored_item): (index, scored_item)
            for index, scored_item in enumerate(items)
        }

        for future in concurrent.futures.as_completed(futures):
            index, scored_item = futures[future]
            try:
                result_index, selected_item = future.result()
                results[result_index] = selected_item
            except (OpenRouterError, ValueError, json.JSONDecodeError) as exc:
                print(
                    f"warning: failed to select format for item {scored_item.source_index} "
                    f"({scored_item.item.title}): {exc}",
                    file=sys.stderr,
                )
                results[index] = scored_item
            except Exception as exc:
                print(
                    f"warning: unexpected failure selecting format for item {scored_item.source_index} "
                    f"({scored_item.item.title}): {exc}",
                    file=sys.stderr,
                )
                results[index] = scored_item

    return [item for item in results if item is not None]

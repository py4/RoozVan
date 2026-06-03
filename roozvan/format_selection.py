"""Instagram format selection for selected RoozVan items."""

from __future__ import annotations

import concurrent.futures
import json
import sys
from dataclasses import replace
from typing import Any

from openrouter_client import OpenRouterClient, OpenRouterError
from roozvan.models import ScoredItem
from roozvan.scoring import is_unsupported_structured_output_error, parse_json_object


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


SCORING_CONTEXT_PLACEHOLDER = "{{SCORING_CONTEXT}}"


def build_format_selection_prompt(instruction: str, scored_item: ScoredItem) -> str:
    item = scored_item.item
    candidate = {
        "title": item.title,
        "caption": item.description,
        "article_content": item.article_content,
    }
    scoring_context = {
        "overall_score": scored_item.overall_score,
        "category": scored_item.evaluation.get("category"),
        "base_score": scored_item.evaluation.get("base_score"),
        "editorial_adjustment": scored_item.evaluation.get("editorial_adjustment"),
        "editorial_adjustment_reasons": scored_item.evaluation.get("editorial_adjustment_reasons"),
        "selection_gate_passed": scored_item.evaluation.get("selection_gate_passed"),
        "selection_gate_reasons": scored_item.evaluation.get("selection_gate_reasons"),
        "local_relevance": scored_item.evaluation.get("local_relevance"),
        "practical_usefulness": scored_item.evaluation.get("practical_usefulness"),
        "immigrant_relevance": scored_item.evaluation.get("immigrant_relevance"),
        "urgency": scored_item.evaluation.get("urgency"),
        "share_save_potential": scored_item.evaluation.get("share_save_potential"),
        "trustworthiness": scored_item.evaluation.get("trustworthiness"),
        "actionability": scored_item.evaluation.get("actionability"),
        "originality": scored_item.evaluation.get("originality"),
        "reason_en": scored_item.evaluation.get("reason_en"),
        "persian_angle": scored_item.evaluation.get("persian_angle"),
    }
    scoring_context_text = json.dumps(scoring_context, ensure_ascii=False, indent=2)
    instruction_with_context = instruction.replace(SCORING_CONTEXT_PLACEHOLDER, scoring_context_text)
    return (
        f"{instruction_with_context.strip()}\n\n"
        "Classify this candidate:\n"
        f"{json.dumps(candidate, ensure_ascii=False, indent=2)}\n\n"
        "Return only one valid JSON object matching the schema."
    )


def select_format(
    client: OpenRouterClient,
    instruction: str,
    scored_item: ScoredItem,
    *,
    max_tokens: int,
) -> str:
    prompt = build_format_selection_prompt(instruction, scored_item)
    try:
        raw_response = client.ask(
            prompt,
            temperature=0,
            max_tokens=max_tokens,
            extra_body={
                "response_format": format_selection_response_format(),
                "provider": {
                    "require_parameters": True,
                },
            },
        )
    except OpenRouterError as exc:
        if not is_unsupported_structured_output_error(exc):
            raise
        raw_response = client.ask(prompt, temperature=0, max_tokens=max_tokens)
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
        selected = select_format(client, instruction, scored_item, max_tokens=max_tokens)
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

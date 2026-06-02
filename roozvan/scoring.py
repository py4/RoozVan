"""Editorial scoring and ranking for extracted RoozVan news items."""

from __future__ import annotations

import concurrent.futures
import json
import re
import sys
from typing import Any

from openrouter_client import OpenRouterClient, OpenRouterError
from roozvan.models import NewsItem, ScoredItem


REQUIRED_NUMERIC_FIELDS = (
    "local_relevance",
    "practical_usefulness",
    "immigrant_relevance",
    "urgency",
    "share_save_potential",
    "trustworthiness",
    "actionability",
    "originality",
)

ALLOWED_CATEGORIES = {
    "urgent_alert",
    "government_policy",
    "immigration",
    "housing",
    "transit",
    "weather",
    "money_tax",
    "healthcare",
    "community_event",
    "local_business",
    "lifestyle",
    "jobs",
    "crime_safety",
    "other",
}

ALLOWED_FORMATS = {"post", "carousel", "story", "no_post"}
ALLOWED_DECISIONS = {"post", "maybe", "skip"}


SCORING_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "local_relevance": {"type": "integer", "minimum": 0, "maximum": 5},
        "practical_usefulness": {"type": "integer", "minimum": 0, "maximum": 5},
        "immigrant_relevance": {"type": "integer", "minimum": 0, "maximum": 5},
        "urgency": {"type": "integer", "minimum": 0, "maximum": 5},
        "share_save_potential": {"type": "integer", "minimum": 0, "maximum": 5},
        "trustworthiness": {"type": "integer", "minimum": 0, "maximum": 5},
        "actionability": {"type": "integer", "minimum": 0, "maximum": 5},
        "originality": {"type": "integer", "minimum": 0, "maximum": 5},
        "category": {"type": "string", "enum": sorted(ALLOWED_CATEGORIES)},
        "overall_score": {"type": "number"},
        "reason_en": {"type": "string"},
        "persian_angle": {"type": "string"},
    },
    "required": [
        "local_relevance",
        "practical_usefulness",
        "immigrant_relevance",
        "urgency",
        "share_save_potential",
        "trustworthiness",
        "actionability",
        "originality",
        "category",
        "overall_score",
        "reason_en",
        "persian_angle",
    ],
    "additionalProperties": False,
}


def scoring_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "rss_editorial_score",
            "strict": True,
            "schema": SCORING_RESPONSE_SCHEMA,
        },
    }


def calculate_overall_score(score: dict[str, Any]) -> float:
    return round(
        1.5 * score["practical_usefulness"]
        + 1.3 * score["local_relevance"]
        + 1.2 * score["immigrant_relevance"]
        + 1.1 * score["actionability"]
        + 1.0 * score["urgency"]
        + 1.0 * score["share_save_potential"]
        + 0.8 * score["trustworthiness"]
        + 0.5 * score["originality"]
        - 1.5 * score["risk"],
        2,
    )


def build_prompt(base_prompt: str, item: NewsItem | dict[str, Any]) -> str:
    item_dict = scoring_item_dict(item)
    return (
        f"{base_prompt.strip()}\n\n"
        "Candidate item:\n"
        f"{json.dumps(item_dict, ensure_ascii=False, indent=2)}\n\n"
        "Return only one valid JSON object. Do not include markdown, code fences, comments, or extra text."
    )


def scoring_item_dict(item: NewsItem | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, NewsItem):
        return item.to_scoring_dict()
    return {
        "title": item.get("title"),
        "description": item.get("description"),
        "date": item.get("date"),
        "url": item.get("url"),
        "image_url": item.get("image_url"),
    }


def parse_json_object(raw_response: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_response, flags=re.DOTALL)
        if not match:
            raise ValueError(f"LLM response was not JSON: {raw_response!r}")
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise ValueError(f"LLM response must be a JSON object: {parsed!r}")
    return parsed


def clamp_score(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number from 0 to 5, not boolean")
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number from 0 to 5: {value!r}") from exc
    return max(0, min(5, number))


def normalize_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(evaluation)

    for field in REQUIRED_NUMERIC_FIELDS:
        normalized[field] = clamp_score(normalized.get(field), field)

    if normalized.get("category") not in ALLOWED_CATEGORIES:
        normalized["category"] = "other"

    normalized["risk"] = infer_risk(normalized)
    normalized["recommended_format"] = infer_recommended_format(normalized)
    normalized["reason_en"] = str(normalized.get("reason_en") or "")
    normalized["persian_angle"] = str(normalized.get("persian_angle") or "")
    normalized["overall_score"] = calculate_overall_score(normalized)
    normalized["post_decision"] = infer_post_decision(normalized)
    return normalized


def infer_risk(score: dict[str, Any]) -> int:
    risk = 0
    if score["trustworthiness"] <= 2:
        risk += 2
    if score["category"] in {"healthcare", "money_tax", "immigration", "crime_safety"}:
        risk += 1
    if score["category"] == "other" and score["actionability"] <= 1:
        risk += 1
    return max(0, min(5, risk))


def infer_recommended_format(score: dict[str, Any]) -> str:
    if calculate_overall_score(score) < 12:
        return "no_post"
    if score["urgency"] >= 4 and score["actionability"] >= 4:
        return "carousel"
    if score["share_save_potential"] >= 4 and score["actionability"] >= 3:
        return "post"
    return "story"


def infer_post_decision(score: dict[str, Any]) -> str:
    overall_score = calculate_overall_score(score)
    if score["recommended_format"] == "no_post" or overall_score < 12:
        return "skip"
    if overall_score >= 24 and score["risk"] <= 2:
        return "post"
    return "maybe"


def score_item(
    client: OpenRouterClient,
    prompt_template: str,
    item: NewsItem | dict[str, Any],
    *,
    max_tokens: int,
) -> dict[str, Any]:
    raw_response = client.ask(
        build_prompt(prompt_template, item),
        temperature=0,
        max_tokens=max_tokens,
        extra_body={
            "response_format": scoring_response_format(),
            "provider": {
                "require_parameters": True,
            },
        },
    )
    return normalize_evaluation(parse_json_object(raw_response))


def score_news_items(
    items: list[NewsItem],
    prompt_template: str,
    client: OpenRouterClient,
    *,
    max_tokens: int,
    workers: int,
) -> list[ScoredItem]:
    results = []
    if not items:
        return results

    worker_count = max(1, min(workers, len(items)))

    def score_indexed_item(index: int, item: NewsItem) -> ScoredItem:
        evaluation = score_item(client, prompt_template, item, max_tokens=max_tokens)
        return ScoredItem(
            source_index=index,
            item=item,
            evaluation=evaluation,
            overall_score=evaluation["overall_score"],
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(score_indexed_item, index, item): (index, item)
            for index, item in enumerate(items, start=1)
        }

        for future in concurrent.futures.as_completed(futures):
            index, item = futures[future]
            try:
                results.append(future.result())
            except (OpenRouterError, ValueError, json.JSONDecodeError) as exc:
                print(f"warning: failed to score item {index} ({item.title}): {exc}", file=sys.stderr)
            except Exception as exc:
                print(f"warning: unexpected failure scoring item {index} ({item.title}): {exc}", file=sys.stderr)

    return rank_scored_items(results)


def score_items(
    items: list[dict[str, Any]],
    prompt_template: str,
    client: OpenRouterClient,
    *,
    max_tokens: int,
    workers: int,
) -> list[dict[str, Any]]:
    news_items = [NewsItem.from_dict(item) for item in items]
    return [item.to_dict() for item in score_news_items(news_items, prompt_template, client, max_tokens=max_tokens, workers=workers)]


def score_items_sequential(
    items: list[dict[str, Any]],
    prompt_template: str,
    client: OpenRouterClient,
    *,
    max_tokens: int,
) -> list[dict[str, Any]]:
    return score_items(items, prompt_template, client, max_tokens=max_tokens, workers=1)


def rank_scored_items(items: list[ScoredItem]) -> list[ScoredItem]:
    return sorted(items, key=lambda item: (-item.overall_score, item.source_index))

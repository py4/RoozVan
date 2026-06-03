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
HIGH_PRIORITY_CATEGORIES = {
    "urgent_alert",
    "immigration",
    "housing",
    "transit",
    "weather",
    "money_tax",
    "healthcare",
}
OUTSIDE_METRO_KEYWORDS = (
    "nanaimo",
    "northern b.c.",
    "northern bc",
    "kitimat",
    "kamloops",
    "lumby",
    "victoria",
    "highway of tears",
    "west moberly",
)
DIRECT_IMPACT_KEYWORDS = (
    "surcharge",
    "fee",
    "fare",
    "tax",
    "rent",
    "rebate",
    "benefit",
    "deadline",
    "increase",
    "decrease",
    "ban",
    "restriction",
    "closure",
    "warning",
    "alert",
)


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


def normalize_evaluation(evaluation: dict[str, Any], item: NewsItem | dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = dict(evaluation)

    for field in REQUIRED_NUMERIC_FIELDS:
        normalized[field] = clamp_score(normalized.get(field), field)

    if normalized.get("category") not in ALLOWED_CATEGORIES:
        normalized["category"] = "other"

    normalized["risk"] = infer_risk(normalized)
    normalized["reason_en"] = str(normalized.get("reason_en") or "")
    normalized["persian_angle"] = str(normalized.get("persian_angle") or "")
    normalized["base_score"] = calculate_overall_score(normalized)
    adjustment, adjustment_reasons = editorial_adjustment(normalized, item)
    normalized["editorial_adjustment"] = adjustment
    normalized["editorial_adjustment_reasons"] = adjustment_reasons
    normalized["overall_score"] = round(normalized["base_score"] + adjustment, 2)
    normalized["recommended_format"] = infer_recommended_format(normalized)
    normalized["post_decision"] = infer_post_decision(normalized)
    normalized["selection_gate_passed"] = passes_selection_gate(normalized)
    normalized["selection_gate_reasons"] = selection_gate_reasons(normalized)
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
    overall_score = score.get("overall_score", calculate_overall_score(score))
    if overall_score < 12:
        return "no_post"
    if score["urgency"] >= 4 and score["actionability"] >= 4:
        return "carousel"
    if score["share_save_potential"] >= 4 and score["actionability"] >= 3:
        return "post"
    return "story"


def infer_post_decision(score: dict[str, Any]) -> str:
    overall_score = score.get("overall_score", calculate_overall_score(score))
    if score.get("recommended_format") == "no_post" or overall_score < 12:
        return "skip"
    if overall_score >= 24 and score["risk"] <= 2:
        return "post"
    return "maybe"


def editorial_adjustment(
    score: dict[str, Any],
    item: NewsItem | dict[str, Any] | None = None,
) -> tuple[float, list[str]]:
    title = item_title(item).lower()
    adjustment = 0.0
    reasons = []

    if has_direct_impact_signal(title) and score["practical_usefulness"] >= 3 and score["actionability"] >= 2:
        adjustment += 4
        reasons.append("direct_cost_deadline_or_rule_impact")

    if score["category"] in HIGH_PRIORITY_CATEGORIES and score["practical_usefulness"] >= 2:
        adjustment += 3
        reasons.append("high_priority_roozvan_category")

    if (
        score["category"] == "government_policy"
        and score["practical_usefulness"] >= 2
        and score["actionability"] >= 2
    ):
        adjustment += 2
        reasons.append("actionable_government_policy")

    if score["local_relevance"] >= 4 and score["urgency"] >= 3 and score["actionability"] >= 2:
        adjustment += 2
        reasons.append("urgent_local_practical_notice")

    if score["category"] == "crime_safety" and score["actionability"] <= 1:
        adjustment -= 4
        reasons.append("crime_without_actionable_safety_guidance")

    if score["category"] == "other" and score["practical_usefulness"] <= 1:
        adjustment -= 3
        reasons.append("other_category_low_practical_value")

    if score["practical_usefulness"] <= 1 and score["actionability"] <= 1 and score["urgency"] <= 2:
        adjustment -= 3
        reasons.append("low_usefulness_actionability_and_urgency")

    if outside_metro_signal(title) and score["practical_usefulness"] < 3:
        adjustment -= 3
        reasons.append("outside_metro_without_broad_practical_value")

    return max(-8, min(8, adjustment)), reasons


def item_title(item: NewsItem | dict[str, Any] | None) -> str:
    if item is None:
        return ""
    if isinstance(item, NewsItem):
        return item.title or ""
    return str(item.get("title") or "")


def has_direct_impact_signal(title: str) -> bool:
    return any(keyword in title for keyword in DIRECT_IMPACT_KEYWORDS)


def outside_metro_signal(title: str) -> bool:
    return any(keyword in title for keyword in OUTSIDE_METRO_KEYWORDS)


def passes_selection_gate(score: dict[str, Any]) -> bool:
    if score.get("post_decision") == "post":
        return True
    if score["category"] == "crime_safety" and score["actionability"] <= 1:
        return False
    if score["category"] == "other" and score["practical_usefulness"] <= 1:
        return False
    return (
        score["practical_usefulness"] >= 2
        or score["actionability"] >= 2
        or score["urgency"] >= 3
        or score["share_save_potential"] >= 3
        or score["category"] in HIGH_PRIORITY_CATEGORIES
        or (
            score["category"] == "government_policy"
            and score["practical_usefulness"] >= 2
            and score["actionability"] >= 2
        )
    )


def selection_gate_reasons(score: dict[str, Any]) -> list[str]:
    reasons = []
    if score["category"] == "crime_safety" and score["actionability"] <= 1:
        reasons.append("blocked_crime_without_actionable_safety_guidance")
        return reasons
    if score["category"] == "other" and score["practical_usefulness"] <= 1:
        reasons.append("blocked_other_category_low_practical_value")
        return reasons
    if score.get("post_decision") == "post":
        reasons.append("strong_post_decision")
    if score["practical_usefulness"] >= 2:
        reasons.append("practical_usefulness_at_least_2")
    if score["actionability"] >= 2:
        reasons.append("actionability_at_least_2")
    if score["urgency"] >= 3:
        reasons.append("urgency_at_least_3")
    if score["share_save_potential"] >= 3:
        reasons.append("share_save_potential_at_least_3")
    if score["category"] in HIGH_PRIORITY_CATEGORIES:
        reasons.append("high_priority_category")
    if (
        score["category"] == "government_policy"
        and score["practical_usefulness"] >= 2
        and score["actionability"] >= 2
    ):
        reasons.append("actionable_government_policy")
    if not reasons:
        reasons.append("blocked_by_low_practical_value_gate")
    return reasons


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
    return normalize_evaluation(parse_json_object(raw_response), item)


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

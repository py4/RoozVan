"""Editorial scoring and ranking for extracted RoozVan news items."""

from __future__ import annotations

import concurrent.futures
import json
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from openrouter_client import OpenRouterClient, OpenRouterError
from roozvan.models import NewsItem, ScoredItem
from roozvan.progress import ProgressLogger, log_progress, short_title


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

HIGH_PRIORITY_CATEGORIES = {
    "urgent_alert",
    "immigration",
    "housing",
    "transit",
    "weather",
    "money_tax",
    "healthcare",
}
# Evergreen Instagram growth topics — save/DM/share more than read-once headlines.
EVERGREEN_GROWTH_CATEGORIES = {
    "immigration",
    "housing",
    "money_tax",
    "healthcare",
    "government_policy",
    "transit",
}
EVERGREEN_UTILITY_KEYWORDS = (
    "msp",
    "medical services plan",
    "renter",
    "rental",
    "tenancy",
    "tenant",
    "cra",
    "canada revenue",
    "newcomer",
    "immigrant",
    "immigration",
    "ircc",
    "permanent resident",
    "pr card",
    "grocery",
    "groceries",
    "cheapest",
    "icbc",
    "insurance corporation",
    "transit",
    "translink",
    "compass card",
    "camping",
    "fishing",
    "travel",
    "healthcare",
    "health care",
    "tax",
    "taxes",
    "bylaw",
    "hidden law",
)
# Headline-only recency: cap RSS age boost unless the story is utility- or alert-worthy.
RECENCY_LIMITED_MAX_BOOST = 1.0
FYI_STORY_CATEGORIES = {
    "community_event",
    "lifestyle",
    "local_business",
    "transit",
    "weather",
}
OUTSIDE_METRO_KEYWORDS = (
    "northern b.c.",
    "northern bc",
    "kitimat",
    "kamloops",
    "lumby",
    "victoria",
    "highway of tears",
    "west moberly",
)
LIFESTYLE_FYI_KEYWORDS = (
    "camp",
    "camping",
    "hike",
    "hiking",
    "trail",
    "park",
    "parks",
    "beach",
    "cycling",
    "bike",
    "biking",
    "paddleboard",
    "paddleboarding",
    "lake",
    "ferry",
    "ferries",
    "nanaimo",
    "squamish",
    "whistler",
    "vancouver island",
    "brewery",
    "breweries",
    "restaurant",
    "restaurants",
    "cafe",
    "coffee",
    "food",
    "market",
    "festival",
    "weekend",
)
# Extra overall_score points by article age (RSS pubDate). Applied after editorial_adjustment.
RECENCY_BOOST_TIERS_HOURS = (
    (12, 4.0),
    (24, 3.0),
    (48, 2.0),
    (72, 1.0),
)
# Extra overall_score for uplifting local stories — RoozVan should not feel like crisis-only news.
FEEL_GOOD_BOOST = 3.0
FEEL_GOOD_CATEGORIES = {
    "community_event",
    "lifestyle",
    "local_business",
}
# Categories that are usually stress/cost news unless the headline is clearly uplifting.
FEEL_GOOD_EXCLUDED_CATEGORIES = {
    "crime_safety",
    "urgent_alert",
    "money_tax",
    "government_policy",
    "healthcare",
    "immigration",
    "housing",
}
FEEL_GOOD_KEYWORDS = (
    "free",
    "celebrat",
    "festival",
    "fun",
    "fun things",
    "joy",
    "amazing",
    "beloved",
    "iconic",
    "heartwarming",
    "inspiring",
    "volunteer",
    "donat",
    "charity",
    "pride",
    "family",
    "all-ages",
    "all ages",
    "kids",
    "teen",
    "summer",
    "watch party",
    "launch",
    "launches",
    "returns",
    "coming back",
    "giveaway",
    "opening",
    "opens",
    "anniversary",
    "limited-edition",
    "souvenir",
    "membership",
    "things to do",
    "weekend",
    "street party",
    "block party",
    "food truck",
    "art",
    "theatre",
    "theater",
    "music",
    "dance",
    "parade",
)
NEGATIVE_TONE_KEYWORDS = (
    "death",
    "dead",
    "killed",
    "murder",
    "assault",
    "harass",
    "crash",
    "collision",
    "layoff",
    "closure",
    "closes",
    "closing",
    "shut down",
    "shuts down",
    "lament",
    "fraud",
    "scam",
    "sanction",
    "victim",
    "missing person",
    "arrested",
    "charged with",
    "lawsuit",
    "outrage",
    "protest against",
    "urine",
    "feces",
    "overdose",
    "shooting",
    "stabbing",
    "robbery",
    "homeless encampment",
    "banned from",
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
        + 0.85 * score["urgency"]
        + 1.4 * score["share_save_potential"]
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


def normalize_evaluation(
    evaluation: dict[str, Any],
    item: NewsItem | dict[str, Any] | None = None,
    *,
    recency_boost_enabled: bool = True,
    feel_good_boost_enabled: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
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

    published_at = item_published_at(item)
    age_hours = item_age_hours(item, now=now)
    recency_boost, recency_reason = recency_score_adjustment(
        item,
        score=normalized,
        enabled=recency_boost_enabled,
        now=now,
    )
    normalized["published_at"] = published_at.isoformat() if published_at else None
    normalized["age_hours"] = round(age_hours, 2) if age_hours is not None else None
    normalized["recency_boost"] = recency_boost
    if recency_reason:
        normalized["recency_boost_reason"] = recency_reason

    feel_good_boost, feel_good_reason = feel_good_score_adjustment(
        normalized,
        item,
        enabled=feel_good_boost_enabled,
    )
    normalized["feel_good_boost"] = feel_good_boost
    if feel_good_reason:
        normalized["feel_good_boost_reason"] = feel_good_reason

    normalized["overall_score"] = round(
        normalized["base_score"] + adjustment + recency_boost + feel_good_boost,
        2,
    )
    normalized["selection_gate_passed"] = passes_selection_gate(normalized, item)
    normalized["selection_gate_reasons"] = selection_gate_reasons(normalized, item)
    return normalized


def item_published_at(item: NewsItem | dict[str, Any] | None) -> datetime | None:
    if item is None:
        return None
    raw_date = item.date if isinstance(item, NewsItem) else item.get("date")
    if not raw_date:
        return None
    try:
        published = parsedate_to_datetime(str(raw_date).strip())
    except (TypeError, ValueError):
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published.astimezone(timezone.utc)


def item_age_hours(item: NewsItem | dict[str, Any] | None, *, now: datetime | None = None) -> float | None:
    published_at = item_published_at(item)
    if published_at is None:
        return None
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    age_seconds = (reference.astimezone(timezone.utc) - published_at).total_seconds()
    return max(0.0, age_seconds / 3600)


def qualifies_for_full_recency_boost(score: dict[str, Any]) -> bool:
    if score["share_save_potential"] >= 3 or score["practical_usefulness"] >= 4:
        return True
    if score["urgency"] >= 4 and score["actionability"] >= 4:
        return True
    return False


def recency_score_adjustment(
    item: NewsItem | dict[str, Any] | None,
    *,
    score: dict[str, Any] | None = None,
    enabled: bool = True,
    now: datetime | None = None,
) -> tuple[float, str | None]:
    if not enabled:
        return 0.0, None
    age_hours = item_age_hours(item, now=now)
    if age_hours is None:
        return 0.0, None
    for max_hours, tier_boost in RECENCY_BOOST_TIERS_HOURS:
        if age_hours <= max_hours:
            boost = tier_boost
            reason = f"published_within_{max_hours}h"
            if score is not None and not qualifies_for_full_recency_boost(score):
                if boost > RECENCY_LIMITED_MAX_BOOST:
                    boost = RECENCY_LIMITED_MAX_BOOST
                    reason = f"{reason}_utility_gated"
            return boost, reason
    return 0.0, None


def has_negative_tone_signal(text: str) -> bool:
    return contains_keyword(text, NEGATIVE_TONE_KEYWORDS)


def has_feel_good_signal(text: str) -> bool:
    return contains_keyword(text, FEEL_GOOD_KEYWORDS)


def is_feel_good_local_story(score: dict[str, Any], item: NewsItem | dict[str, Any] | None = None) -> bool:
    """Uplifting Metro Vancouver stories worth balancing against heavy news."""
    text = item_text(item).lower()
    if has_negative_tone_signal(text):
        return False
    if has_direct_impact_signal(text) and not has_feel_good_signal(text):
        return False
    if score["category"] in FEEL_GOOD_EXCLUDED_CATEGORIES and not has_feel_good_signal(text):
        return False
    if score.get("risk", 0) >= 2:
        return False
    if score["trustworthiness"] < 4 or score["local_relevance"] < 2:
        return False
    # Breaking crisis vibe — not feel-good even if local.
    if score["urgency"] >= 4 and score["actionability"] <= 2:
        return False

    if has_feel_good_signal(text):
        return True
    if (
        score["category"] in FEEL_GOOD_CATEGORIES
        and score["share_save_potential"] >= 3
        and score["urgency"] <= 3
    ):
        return True
    if (
        is_lifestyle_or_outdoor_signal(item)
        and has_feel_good_signal(text)
        and score["share_save_potential"] >= 3
        and score["urgency"] <= 3
    ):
        return True
    return False


def feel_good_score_adjustment(
    score: dict[str, Any],
    item: NewsItem | dict[str, Any] | None,
    *,
    enabled: bool = True,
) -> tuple[float, str | None]:
    if not enabled:
        return 0.0, None
    if is_feel_good_local_story(score, item):
        return FEEL_GOOD_BOOST, "feel_good_local_story"
    return 0.0, None


def item_published_timestamp(item: ScoredItem | NewsItem | dict[str, Any]) -> float:
    if isinstance(item, ScoredItem):
        published_at = item_published_at(item.item)
    else:
        published_at = item_published_at(item)
    if published_at is None:
        return 0.0
    return published_at.timestamp()


def infer_risk(score: dict[str, Any]) -> int:
    risk = 0
    if score["trustworthiness"] <= 2:
        risk += 2
    if score["category"] in {"healthcare", "money_tax", "immigration", "crime_safety"}:
        risk += 1
    if score["category"] == "other" and score["actionability"] <= 1:
        risk += 1
    return max(0, min(5, risk))


def editorial_adjustment(
    score: dict[str, Any],
    item: NewsItem | dict[str, Any] | None = None,
) -> tuple[float, list[str]]:
    text = item_text(item).lower()
    adjustment = 0.0
    reasons = []

    if has_direct_impact_signal(text) and score["practical_usefulness"] >= 3 and score["actionability"] >= 2:
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

    if is_interesting_fyi_story(score, item):
        adjustment += 2
        reasons.append("interesting_local_fyi_story")

    if is_lifestyle_or_outdoor_signal(item) and score["local_relevance"] >= 2:
        adjustment += 2
        reasons.append("outdoor_lifestyle_or_local_experience_relevance")

    if is_evergreen_utility_story(score, item):
        adjustment += 2
        reasons.append("evergreen_utility_growth_topic")

    if score["category"] == "crime_safety" and score["actionability"] <= 1:
        adjustment -= 4
        reasons.append("crime_without_actionable_safety_guidance")

    if (
        score["category"] == "other"
        and score["practical_usefulness"] <= 1
        and not is_interesting_fyi_story(score, item)
        and not is_lifestyle_or_outdoor_signal(item)
    ):
        adjustment -= 3
        reasons.append("other_category_low_practical_value")

    if (
        score["practical_usefulness"] <= 1
        and score["actionability"] <= 1
        and score["urgency"] <= 2
        and not is_interesting_fyi_story(score, item)
        and not is_lifestyle_or_outdoor_signal(item)
    ):
        adjustment -= 3
        reasons.append("low_usefulness_actionability_and_urgency")

    if outside_metro_signal(text) and score["practical_usefulness"] < 3:
        adjustment -= 3
        reasons.append("outside_metro_without_broad_practical_value")

    return max(-8, min(8, adjustment)), reasons


def item_title(item: NewsItem | dict[str, Any] | None) -> str:
    if item is None:
        return ""
    if isinstance(item, NewsItem):
        return item.title or ""
    return str(item.get("title") or "")


def item_text(item: NewsItem | dict[str, Any] | None) -> str:
    if item is None:
        return ""
    if isinstance(item, NewsItem):
        values = (item.title, item.description)
    else:
        values = (item.get("title"), item.get("description"))
    return " ".join(str(value or "") for value in values)


def has_direct_impact_signal(title: str) -> bool:
    return contains_keyword(title, DIRECT_IMPACT_KEYWORDS)


def outside_metro_signal(title: str) -> bool:
    return contains_keyword(title, OUTSIDE_METRO_KEYWORDS)


def is_evergreen_utility_story(score: dict[str, Any], item: NewsItem | dict[str, Any] | None = None) -> bool:
    text = item_text(item).lower()
    if score["category"] in EVERGREEN_GROWTH_CATEGORIES and score["practical_usefulness"] >= 2:
        return True
    return (
        contains_keyword(text, EVERGREEN_UTILITY_KEYWORDS)
        and score["share_save_potential"] >= 2
        and score["practical_usefulness"] >= 2
    )


def is_lifestyle_or_outdoor_signal(item: NewsItem | dict[str, Any] | None) -> bool:
    text = item_text(item).lower()
    return contains_keyword(text, LIFESTYLE_FYI_KEYWORDS)


def contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords)


def is_interesting_fyi_story(score: dict[str, Any], item: NewsItem | dict[str, Any] | None = None) -> bool:
    if score["category"] == "crime_safety" and score["actionability"] <= 1:
        return False
    if score["local_relevance"] < 3 or score["trustworthiness"] < 4:
        return False
    if score["share_save_potential"] < 2 and score["originality"] < 3:
        return False
    return (
        score["category"] in FYI_STORY_CATEGORIES
        or score["practical_usefulness"] >= 2
        or is_lifestyle_or_outdoor_signal(item)
    )


def passes_selection_gate(score: dict[str, Any], item: NewsItem | dict[str, Any] | None = None) -> bool:
    if score["category"] == "crime_safety" and score["actionability"] <= 1:
        return False
    if is_interesting_fyi_story(score, item):
        return True
    if (
        score["category"] == "other"
        and score["practical_usefulness"] <= 1
        and not is_lifestyle_or_outdoor_signal(item)
    ):
        return False
    return (
        score["practical_usefulness"] >= 2
        or score["actionability"] >= 2
        or score["share_save_potential"] >= 2
        or passes_urgency_selection_gate(score)
        or score["category"] in HIGH_PRIORITY_CATEGORIES
        or (
            score["category"] == "government_policy"
            and score["practical_usefulness"] >= 2
            and score["actionability"] >= 2
        )
    )


def passes_urgency_selection_gate(score: dict[str, Any]) -> bool:
    if score["urgency"] >= 4 and score["actionability"] >= 4:
        return True
    if score["urgency"] >= 3:
        return (
            score["share_save_potential"] >= 2
            or score["practical_usefulness"] >= 3
            or score["actionability"] >= 3
        )
    return False


def selection_gate_reasons(score: dict[str, Any], item: NewsItem | dict[str, Any] | None = None) -> list[str]:
    reasons = []
    if score["category"] == "crime_safety" and score["actionability"] <= 1:
        reasons.append("blocked_crime_without_actionable_safety_guidance")
        return reasons
    if is_interesting_fyi_story(score, item):
        reasons.append("interesting_local_fyi_story")
        if is_lifestyle_or_outdoor_signal(item):
            reasons.append("outdoor_lifestyle_or_local_experience_relevance")
        return reasons
    if (
        score["category"] == "other"
        and score["practical_usefulness"] <= 1
        and not is_lifestyle_or_outdoor_signal(item)
    ):
        reasons.append("blocked_other_category_low_practical_value")
        return reasons
    if score["practical_usefulness"] >= 2:
        reasons.append("practical_usefulness_at_least_2")
    if score["actionability"] >= 2:
        reasons.append("actionability_at_least_2")
    if score["share_save_potential"] >= 2:
        reasons.append("share_save_potential_at_least_2")
    if passes_urgency_selection_gate(score):
        reasons.append("urgency_with_save_utility_or_alert")
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
    recency_boost_enabled: bool = True,
    feel_good_boost_enabled: bool = True,
) -> dict[str, Any]:
    prompt = build_prompt(prompt_template, item)
    try:
        raw_response = client.ask(
            prompt,
            temperature=0,
            max_tokens=max_tokens,
            extra_body={
                "response_format": scoring_response_format(),
                "provider": {
                    "require_parameters": True,
                },
            },
        )
    except OpenRouterError as exc:
        if not is_unsupported_structured_output_error(exc):
            raise
        raw_response = client.ask(prompt, temperature=0, max_tokens=max_tokens)
    return normalize_evaluation(
        parse_json_object(raw_response),
        item,
        recency_boost_enabled=recency_boost_enabled,
        feel_good_boost_enabled=feel_good_boost_enabled,
    )


def is_unsupported_structured_output_error(exc: OpenRouterError) -> bool:
    return "No endpoints found that can handle the requested parameters" in str(exc)


def score_news_items(
    items: list[NewsItem],
    prompt_template: str,
    client: OpenRouterClient,
    *,
    max_tokens: int,
    workers: int,
    recency_boost_enabled: bool = True,
    feel_good_boost_enabled: bool = True,
    errors: list[str] | None = None,
    progress_log: ProgressLogger | None = None,
) -> list[ScoredItem]:
    results = []
    if not items:
        return results

    total = len(items)
    completed = 0
    worker_count = max(1, min(workers, len(items)))

    def score_indexed_item(index: int, item: NewsItem) -> ScoredItem:
        evaluation = score_item(
            client,
            prompt_template,
            item,
            max_tokens=max_tokens,
            recency_boost_enabled=recency_boost_enabled,
            feel_good_boost_enabled=feel_good_boost_enabled,
        )
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
            completed += 1
            try:
                scored = future.result()
                results.append(scored)
                log_progress(
                    progress_log,
                    f"score: {completed}/{total} [{scored.overall_score}] {short_title(item.title)}",
                )
            except (OpenRouterError, ValueError, json.JSONDecodeError) as exc:
                message = f"failed to score item {index} ({item.title}): {exc}"
                log_progress(progress_log, f"score: {completed}/{total} failed — {short_title(item.title)}")
                if errors is not None:
                    errors.append(message)
                else:
                    print(f"warning: {message}", file=sys.stderr)
            except Exception as exc:
                message = f"unexpected failure scoring item {index} ({item.title}): {exc}"
                log_progress(progress_log, f"score: {completed}/{total} failed — {short_title(item.title)}")
                if errors is not None:
                    errors.append(message)
                else:
                    print(f"warning: {message}", file=sys.stderr)

    return rank_scored_items(results)


def score_items(
    items: list[dict[str, Any]],
    prompt_template: str,
    client: OpenRouterClient,
    *,
    max_tokens: int,
    workers: int,
    recency_boost_enabled: bool = True,
    feel_good_boost_enabled: bool = True,
) -> list[dict[str, Any]]:
    news_items = [NewsItem.from_dict(item) for item in items]
    return [
        item.to_dict()
        for item in score_news_items(
            news_items,
            prompt_template,
            client,
            max_tokens=max_tokens,
            workers=workers,
            recency_boost_enabled=recency_boost_enabled,
            feel_good_boost_enabled=feel_good_boost_enabled,
        )
    ]


def score_items_sequential(
    items: list[dict[str, Any]],
    prompt_template: str,
    client: OpenRouterClient,
    *,
    max_tokens: int,
) -> list[dict[str, Any]]:
    return score_items(items, prompt_template, client, max_tokens=max_tokens, workers=1)


def rank_scored_items(items: list[ScoredItem]) -> list[ScoredItem]:
    return sorted(
        items,
        key=lambda item: (
            -item.overall_score,
            -item_published_timestamp(item),
            item.source_index,
        ),
    )

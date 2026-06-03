#!/usr/bin/env python3
"""Score RSS items with OpenRouter and print ranked JSON results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openrouter_client import OpenRouterClient
from roozvan.feeds import collect_items
from roozvan.scoring import (
    ALLOWED_CATEGORIES,
    REQUIRED_NUMERIC_FIELDS,
    SCORING_RESPONSE_SCHEMA,
    build_prompt,
    calculate_overall_score,
    clamp_score,
    normalize_evaluation,
    parse_json_object,
    score_item,
    score_items,
    score_items_sequential,
    scoring_response_format,
)

__all__ = [
    "ALLOWED_CATEGORIES",
    "REQUIRED_NUMERIC_FIELDS",
    "SCORING_RESPONSE_SCHEMA",
    "build_prompt",
    "calculate_overall_score",
    "clamp_score",
    "normalize_evaluation",
    "parse_json_object",
    "score_item",
    "score_items",
    "score_items_sequential",
    "scoring_response_format",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Score RSS items for a Persian Vancouver Instagram page.")
    parser.add_argument("--sources", default="sources.txt", help="File containing RSS/Atom URLs or paths, one per line.")
    parser.add_argument("--prompt", default="scoring_prompt.md", help="Editorial scoring prompt file.")
    parser.add_argument(
        "--model",
        default="openrouter/owl-alpha",
        help="OpenRouter model name.",
    )
    parser.add_argument("--timeout", type=int, default=60, help="Network timeout in seconds.")
    parser.add_argument("--max-items", type=int, default=None, help="Optional limit for scoring only the first N RSS items.")
    parser.add_argument("--max-tokens", type=int, default=600, help="Maximum output tokens for each LLM response.")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel OpenRouter scoring requests.")
    args = parser.parse_args()

    prompt_template = Path(args.prompt).read_text(encoding="utf-8")
    items = collect_items(Path(args.sources), args.timeout)
    if args.max_items is not None:
        items = items[: args.max_items]

    client = OpenRouterClient(model=args.model, timeout=args.timeout, app_name="RoozVan")
    results = score_items(items, prompt_template, client, max_tokens=args.max_tokens, workers=args.workers)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

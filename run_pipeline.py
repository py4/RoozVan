#!/usr/bin/env python3
"""Run the RoozVan editorial pipeline and print selected post candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from roozvan.pipeline import PipelineConfig, build_default_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RoozVan sources -> select pipeline.")
    parser.add_argument("--sources", default="sources.txt", help="File containing RSS/Atom URLs or paths, one per line.")
    parser.add_argument("--prompt", default="scoring_prompt.md", help="Editorial scoring prompt file.")
    parser.add_argument("--model", default="openrouter/owl-alpha", help="OpenRouter model name.")
    parser.add_argument("--timeout", type=int, default=60, help="Network and OpenRouter timeout in seconds.")
    parser.add_argument("--max-items", type=int, default=None, help="Optional limit for scoring only the first N RSS items.")
    parser.add_argument("--max-tokens", type=int, default=600, help="Maximum output tokens for each LLM response.")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel OpenRouter scoring requests.")
    parser.add_argument("--selection-limit", type=int, default=5, help="Maximum candidates to select.")
    parser.add_argument("--minimum-score", type=float, default=12, help="Minimum overall score for selected candidates.")
    parser.add_argument("--post-only", action="store_true", help="Exclude maybe decisions from selected candidates.")
    parser.add_argument("--skip-article-fetch", action="store_true", help="Score RSS summaries without opening article URLs.")
    parser.add_argument("--article-max-chars", type=int, default=6000, help="Maximum article text characters sent to scoring.")
    parser.add_argument("--json", action="store_true", help="Print selected candidates as JSON.")
    args = parser.parse_args()

    config = PipelineConfig(
        sources_path=Path(args.sources),
        scoring_prompt_path=Path(args.prompt),
        model=args.model,
        timeout=args.timeout,
        max_items=args.max_items,
        max_tokens=args.max_tokens,
        workers=args.workers,
        selection_limit=args.selection_limit,
        minimum_score=args.minimum_score,
        include_maybe=not args.post_only,
        fetch_articles=not args.skip_article_fetch,
        article_max_chars=args.article_max_chars,
    )
    result = build_default_pipeline().run(config)

    if args.json:
        print(json.dumps(result.selected_as_dicts(), ensure_ascii=False, indent=2))
        return 0

    print(f"Extracted: {len(result.items)}")
    print(f"Readable without JS: {sum(1 for item in result.items if item.article_readable_without_js)}")
    print(f"Scored: {len(result.scored_items)}")
    print(f"Deduped: {len(result.deduped_items)}")
    print(f"Selected: {len(result.selected_items)}")
    print()
    for index, item in enumerate(result.selected_items, start=1):
        evaluation = item.evaluation
        news = item.item
        print(f"{index}. [{item.overall_score}] {evaluation.get('post_decision')} / {evaluation.get('recommended_format')}")
        print(f"   {news.title}")
        print(f"   {evaluation.get('persian_angle')}")
        print(f"   readable_without_js={news.article_readable_without_js}")
        print(f"   {news.url}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

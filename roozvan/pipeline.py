"""Composable pipeline stages for RoozVan."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from openrouter_client import OpenRouterClient
from roozvan.articles import enrich_items_with_articles
from roozvan.feeds import collect_news_items
from roozvan.models import NewsItem, PostDraft, ScoredItem
from roozvan.scoring import rank_scored_items, score_news_items


@dataclass(frozen=True)
class PipelineConfig:
    sources_path: Path = Path("sources.txt")
    scoring_prompt_path: Path = Path("scoring_prompt.md")
    model: str = "openrouter/owl-alpha"
    timeout: int = 60
    max_items: int | None = None
    max_tokens: int = 600
    workers: int = 4
    selection_limit: int = 5
    minimum_score: float = 12
    include_maybe: bool = True


@dataclass
class PipelineResult:
    items: list[NewsItem] = field(default_factory=list)
    scored_items: list[ScoredItem] = field(default_factory=list)
    ranked_items: list[ScoredItem] = field(default_factory=list)
    deduped_items: list[ScoredItem] = field(default_factory=list)
    selected_items: list[ScoredItem] = field(default_factory=list)
    post_drafts: list[PostDraft] = field(default_factory=list)

    def selected_as_dicts(self) -> list[dict]:
        return [item.to_dict() for item in self.selected_items]


class PipelineStage(Protocol):
    name: str

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        ...


class Pipeline:
    def __init__(self, stages: list[PipelineStage]) -> None:
        self.stages = stages

    def run(self, config: PipelineConfig) -> PipelineResult:
        result = PipelineResult()
        for stage in self.stages:
            result = stage.run(result, config)
        return result


class RecentNewsExtractionStage:
    name = "recent_news_extraction"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        items = collect_news_items(config.sources_path, config.timeout)
        if config.max_items is not None:
            items = items[: config.max_items]
        result.items = items
        return result


class EditorialScoringStage:
    name = "score"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        prompt_template = config.scoring_prompt_path.read_text(encoding="utf-8")
        client = OpenRouterClient(model=config.model, timeout=config.timeout, app_name="RoozVan")
        result.scored_items = score_news_items(
            result.items,
            prompt_template,
            client,
            max_tokens=config.max_tokens,
            workers=config.workers,
        )
        return result


class ArticleExtractionStage:
    name = "article_extraction"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        enriched_items = enrich_items_with_articles(
            [item.item for item in result.selected_items],
            timeout=config.timeout,
            max_chars=6000,
        )
        result.selected_items = [
            replace(scored_item, item=enriched_item)
            for scored_item, enriched_item in zip(result.selected_items, enriched_items)
        ]
        return result


class RankingStage:
    name = "rank"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        source_items = result.scored_items or result.ranked_items
        result.ranked_items = rank_scored_items(source_items)
        return result


class DeduplicationStage:
    name = "dedup"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        seen = set()
        deduped = []
        for scored_item in result.ranked_items:
            key = dedup_key(scored_item.item)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(scored_item)
        result.deduped_items = deduped
        return result


class SelectionStage:
    name = "select"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        allowed_decisions = {"post", "maybe"} if config.include_maybe else {"post"}
        selected = []
        for scored_item in result.deduped_items:
            decision = scored_item.evaluation.get("post_decision")
            if decision not in allowed_decisions:
                continue
            if scored_item.overall_score < config.minimum_score:
                continue
            selected.append(scored_item)
            if len(selected) >= config.selection_limit:
                break
        result.selected_items = selected
        return result


class DraftPlaceholderStage:
    name = "draft_placeholders"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        result.post_drafts = [PostDraft(scored_item=item) for item in result.selected_items]
        return result


def dedup_key(item: NewsItem) -> str:
    if item.url:
        return f"url:{item.url.strip().lower()}"
    title = (item.title or "").strip().casefold()
    date = (item.date or "").strip().casefold()
    return f"title:{title}|date:{date}"


def build_default_pipeline() -> Pipeline:
    return Pipeline(
        [
            RecentNewsExtractionStage(),
            EditorialScoringStage(),
            RankingStage(),
            DeduplicationStage(),
            SelectionStage(),
            ArticleExtractionStage(),
            DraftPlaceholderStage(),
        ]
    )

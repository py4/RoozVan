"""Composable pipeline stages for RoozVan."""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from openrouter_client import OpenRouterClient
from roozvan.articles import enrich_items_with_articles
from roozvan.feeds import collect_news_items
from roozvan.format_selection import select_formats_for_scored_items
from roozvan.models import NewsItem, PostDraft, ScoredItem
from roozvan.post_content import generate_post_content_for_scored_items
from roozvan.scoring import rank_scored_items, score_news_items
from roozvan.story_images import (
    DEFAULT_GEMINI_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_MODEL,
    generate_story_images_for_scored_items,
)


@dataclass(frozen=True)
class PipelineConfig:
    sources_path: Path = Path("sources.txt")
    scoring_prompt_path: Path = Path("scoring_prompt.md")
    format_selection_instruction_path: Path = Path("format_selection_instruction.md")
    story_image_prompt_path: Path = Path("prompts/story_image_generation.md")
    post_image_prompt_path: Path = Path("prompts/post_image_generation.md")
    post_caption_prompt_path: Path = Path("prompts/post_caption_generation.md")
    model: str = "openrouter/owl-alpha"
    story_image_model: str = DEFAULT_STORY_IMAGE_MODEL
    gemini_story_image_model: str = DEFAULT_GEMINI_STORY_IMAGE_MODEL
    story_image_provider: str = "gemini"
    timeout: int = 60
    story_image_timeout: int = 300
    max_items: int | None = None
    max_tokens: int = 600
    format_selection_max_tokens: int = 80
    story_image_max_tokens: int | None = 12000
    post_caption_max_tokens: int = 900
    post_image_max_tokens: int | None = 12000
    workers: int = 4
    selection_limit: int = 5
    minimum_score: float = 12
    generate_story_images: bool = True
    generate_post_content: bool = True
    story_image_output_dir: Path = Path("generated_story_images")
    post_image_output_dir: Path = Path("generated_post_images")


@dataclass
class PipelineResult:
    items: list[NewsItem] = field(default_factory=list)
    scored_items: list[ScoredItem] = field(default_factory=list)
    ranked_items: list[ScoredItem] = field(default_factory=list)
    deduped_items: list[ScoredItem] = field(default_factory=list)
    selected_items: list[ScoredItem] = field(default_factory=list)
    post_drafts: list[PostDraft] = field(default_factory=list)
    stage_timings: list[tuple[str, float]] = field(default_factory=list)

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
            started_at = time.perf_counter()
            result = stage.run(result, config)
            result.stage_timings.append((stage.name, time.perf_counter() - started_at))
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


class FormatSelectionStage:
    name = "format_selection"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        instruction = config.format_selection_instruction_path.read_text(encoding="utf-8")
        client = OpenRouterClient(model=config.model, timeout=config.timeout, app_name="RoozVan")
        result.selected_items = select_formats_for_scored_items(
            result.selected_items,
            instruction,
            client,
            max_tokens=config.format_selection_max_tokens,
            workers=config.workers,
        )
        return result


class StoryImageGenerationStage:
    name = "story_image_generation"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        if not config.generate_story_images or not result.selected_items:
            return result
        prompt_template = config.story_image_prompt_path.read_text(encoding="utf-8")
        story_image_model = (
            config.gemini_story_image_model
            if config.story_image_provider == "gemini"
            else config.story_image_model
        )
        client = OpenRouterClient(
            model=story_image_model,
            timeout=config.story_image_timeout,
            app_name="RoozVan",
        )
        result.selected_items = generate_story_images_for_scored_items(
            result.selected_items,
            prompt_template,
            client,
            output_dir=config.story_image_output_dir,
            model=story_image_model,
            provider=config.story_image_provider,
            max_tokens=config.story_image_max_tokens,
            workers=config.workers,
        )
        return result


class PostContentGenerationStage:
    name = "post_content_generation"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        if not config.generate_post_content or not result.selected_items:
            return result
        image_prompt_template = config.post_image_prompt_path.read_text(encoding="utf-8")
        caption_prompt_template = config.post_caption_prompt_path.read_text(encoding="utf-8")
        image_model = (
            config.gemini_story_image_model
            if config.story_image_provider == "gemini"
            else config.story_image_model
        )
        image_client = OpenRouterClient(
            model=image_model,
            timeout=config.story_image_timeout,
            app_name="RoozVan",
        )
        caption_client = OpenRouterClient(model=config.model, timeout=config.timeout, app_name="RoozVan")
        result.selected_items = generate_post_content_for_scored_items(
            result.selected_items,
            image_prompt_template=image_prompt_template,
            caption_prompt_template=caption_prompt_template,
            caption_client=caption_client,
            image_client=image_client,
            output_dir=config.post_image_output_dir,
            image_model=image_model,
            image_provider=config.story_image_provider,
            caption_max_tokens=config.post_caption_max_tokens,
            image_max_tokens=config.post_image_max_tokens,
            workers=config.workers,
        )
        return result


class VisualContentGenerationStage:
    name = "visual_content_generation"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        if not result.selected_items:
            return result

        post_indexed_items = [
            (index, item)
            for index, item in enumerate(result.selected_items)
            if item.format_selected == "post"
        ]
        story_indexed_items = [
            (index, item)
            for index, item in enumerate(result.selected_items)
            if item.format_selected == "story"
        ]
        updated_items: list[ScoredItem] = list(result.selected_items)

        def generate_post_items() -> list[tuple[int, ScoredItem]]:
            if not config.generate_post_content or not post_indexed_items:
                return []
            image_prompt_template = config.post_image_prompt_path.read_text(encoding="utf-8")
            caption_prompt_template = config.post_caption_prompt_path.read_text(encoding="utf-8")
            image_model = (
                config.gemini_story_image_model
                if config.story_image_provider == "gemini"
                else config.story_image_model
            )
            image_client = OpenRouterClient(
                model=image_model,
                timeout=config.story_image_timeout,
                app_name="RoozVan",
            )
            caption_client = OpenRouterClient(model=config.model, timeout=config.timeout, app_name="RoozVan")
            generated = generate_post_content_for_scored_items(
                [item for _, item in post_indexed_items],
                image_prompt_template=image_prompt_template,
                caption_prompt_template=caption_prompt_template,
                caption_client=caption_client,
                image_client=image_client,
                output_dir=config.post_image_output_dir,
                image_model=image_model,
                image_provider=config.story_image_provider,
                caption_max_tokens=config.post_caption_max_tokens,
                image_max_tokens=config.post_image_max_tokens,
                workers=config.workers,
            )
            return [(index, item) for (index, _), item in zip(post_indexed_items, generated)]

        def generate_story_items() -> list[tuple[int, ScoredItem]]:
            if not config.generate_story_images or not story_indexed_items:
                return []
            prompt_template = config.story_image_prompt_path.read_text(encoding="utf-8")
            story_image_model = (
                config.gemini_story_image_model
                if config.story_image_provider == "gemini"
                else config.story_image_model
            )
            client = OpenRouterClient(
                model=story_image_model,
                timeout=config.story_image_timeout,
                app_name="RoozVan",
            )
            generated = generate_story_images_for_scored_items(
                [item for _, item in story_indexed_items],
                prompt_template,
                client,
                output_dir=config.story_image_output_dir,
                model=story_image_model,
                provider=config.story_image_provider,
                max_tokens=config.story_image_max_tokens,
                workers=config.workers,
            )
            return [(index, item) for (index, _), item in zip(story_indexed_items, generated)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(generate_post_items),
                executor.submit(generate_story_items),
            ]
            for future in concurrent.futures.as_completed(futures):
                for index, item in future.result():
                    updated_items[index] = item

        result.selected_items = updated_items
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
        selected = []
        for scored_item in result.deduped_items:
            if scored_item.overall_score < config.minimum_score:
                continue
            if not scored_item.evaluation.get("selection_gate_passed", True):
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
            FormatSelectionStage(),
            VisualContentGenerationStage(),
            DraftPlaceholderStage(),
        ]
    )

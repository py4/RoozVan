"""Composable pipeline stages for RoozVan."""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from openrouter_client import DEFAULT_TEXT_MODEL, OpenRouterClient
from roozvan.progress import ProgressLogger, log_progress, short_title
from roozvan.articles import enrich_items_with_articles
from roozvan.feeds import collect_news_items
from roozvan.models import NewsItem, PostDraft, ScoredItem
from roozvan.post_content import (
    generate_instagram_content_for_scored_items,
    generate_post_images_for_scored_items,
)
from roozvan.scoring import rank_scored_items, score_news_items
from roozvan.logo_overlay import DEFAULT_LOGO_PATH
from roozvan.story_images import (
    DEFAULT_GEMINI_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_PROVIDER,
    generate_story_images_for_scored_items,
)


@dataclass(frozen=True)
class PipelineConfig:
    sources_path: Path = Path("sources.txt")
    scoring_prompt_path: Path = Path("scoring_prompt.md")
    instagram_content_prompt_path: Path = Path("prompts/instagram_content_generation.md")
    story_image_prompt_path: Path = Path("prompts/story_image_generation.md")
    post_image_prompt_path: Path = Path("prompts/post_image_generation.md")
    post_caption_prompt_path: Path = Path("prompts/post_caption_generation.md")
    carousel_content_prompt_path: Path = Path("prompts/carousel_content_generation.md")
    carousel_image_prompt_path: Path = Path("prompts/carousel_image_background_generation.md")
    model: str = DEFAULT_TEXT_MODEL
    story_image_model: str = DEFAULT_STORY_IMAGE_MODEL
    gemini_story_image_model: str = DEFAULT_GEMINI_STORY_IMAGE_MODEL
    story_image_provider: str = DEFAULT_STORY_IMAGE_PROVIDER
    timeout: int = 60
    story_image_timeout: int = 300
    max_items: int | None = None
    max_tokens: int = 600
    story_image_max_tokens: int | None = 1400
    post_caption_max_tokens: int = 900
    post_image_max_tokens: int | None = 1400
    workers: int = 16
    selection_limit: int = 20
    minimum_score: float = 12
    recency_boost_enabled: bool = True
    feel_good_boost_enabled: bool = True
    generate_story_images: bool = False
    generate_post_content: bool = True
    generate_post_images: bool = False
    story_image_output_dir: Path = Path("generated_story_images")
    post_image_output_dir: Path = Path("generated_post_images")
    logo_path: Path = DEFAULT_LOGO_PATH
    apply_logo_overlay: bool = True
    progress_log: ProgressLogger | None = field(default=None, compare=False, hash=False)


@dataclass
class PipelineResult:
    items: list[NewsItem] = field(default_factory=list)
    scored_items: list[ScoredItem] = field(default_factory=list)
    ranked_items: list[ScoredItem] = field(default_factory=list)
    deduped_items: list[ScoredItem] = field(default_factory=list)
    selected_items: list[ScoredItem] = field(default_factory=list)
    post_drafts: list[PostDraft] = field(default_factory=list)
    stage_timings: list[tuple[str, float]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

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
            log_pipeline_progress(config, f"stage {stage.name}: started")
            result = stage.run(result, config)
            elapsed = time.perf_counter() - started_at
            result.stage_timings.append((stage.name, elapsed))
            log_pipeline_progress(config, f"stage {stage.name}: finished in {elapsed:.1f}s")
        return result


def log_pipeline_progress(config: PipelineConfig, message: str) -> None:
    log_progress(config.progress_log, message)


class RecentNewsExtractionStage:
    name = "recent_news_extraction"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        log_pipeline_progress(config, f"extract: reading feeds from {config.sources_path}")
        items = collect_news_items(
            config.sources_path,
            config.timeout,
            errors=result.errors,
            progress_log=config.progress_log,
        )
        if config.max_items is not None:
            items = items[: config.max_items]
            log_pipeline_progress(config, f"extract: limited to first {len(items)} items")
        result.items = items
        log_pipeline_progress(config, f"extract: {len(items)} RSS items ready")
        if not items and not result.errors:
            result.errors.append("No RSS items were extracted from sources.txt")
        return result


class EditorialScoringStage:
    name = "score"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        prompt_template = config.scoring_prompt_path.read_text(encoding="utf-8")
        client = OpenRouterClient(model=config.model, timeout=config.timeout, app_name="RoozVan")
        log_pipeline_progress(config, f"score: scoring {len(result.items)} items with {config.model}")
        result.scored_items = score_news_items(
            result.items,
            prompt_template,
            client,
            max_tokens=config.max_tokens,
            workers=config.workers,
            recency_boost_enabled=config.recency_boost_enabled,
            feel_good_boost_enabled=config.feel_good_boost_enabled,
            errors=result.errors,
            progress_log=config.progress_log,
        )
        log_pipeline_progress(config, f"score: {len(result.scored_items)} items scored")
        if result.items and not result.scored_items:
            result.errors.append(
                f"Scoring produced 0/{len(result.items)} items. Check text model ({config.model}) and API key."
            )
        return result


class ArticleExtractionStage:
    name = "article_extraction"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        log_pipeline_progress(config, f"article_extraction: fetching {len(result.selected_items)} articles")
        enriched_items = enrich_items_with_articles(
            [item.item for item in result.selected_items],
            timeout=config.timeout,
            max_chars=6000,
            progress_log=config.progress_log,
        )
        log_pipeline_progress(
            config,
            f"article_extraction: {sum(1 for item in enriched_items if item.article_readable_without_js)} readable without JS",
        )
        result.selected_items = [
            replace(scored_item, item=enriched_item)
            for scored_item, enriched_item in zip(result.selected_items, enriched_items)
        ]
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
            apply_logo_overlay_enabled=config.apply_logo_overlay,
            logo_path=config.logo_path,
        )
        return result


class VisualContentGenerationStage:
    name = "visual_content_generation"

    def run(self, result: PipelineResult, config: PipelineConfig) -> PipelineResult:
        if not result.selected_items:
            log_pipeline_progress(config, "visual_content_generation: skipped (no selected items)")
            return result

        needs_content = (
            config.generate_post_content
            or config.generate_story_images
            or config.generate_post_images
        )
        if not needs_content:
            log_pipeline_progress(config, "visual_content_generation: skipped (no content or image flags)")
            return result

        updated_items: list[ScoredItem] = list(result.selected_items)
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
        image_prompt_template = config.post_image_prompt_path.read_text(encoding="utf-8")
        carousel_image_prompt_template = config.carousel_image_prompt_path.read_text(encoding="utf-8")

        if config.generate_post_content or config.generate_story_images or config.generate_post_images:
            content_prompt_template = config.instagram_content_prompt_path.read_text(encoding="utf-8")
            log_pipeline_progress(
                config,
                f"instagram_content: choosing format and generating text for {len(updated_items)} items",
            )
            updated_items = generate_instagram_content_for_scored_items(
                updated_items,
                content_prompt_template=content_prompt_template,
                image_prompt_template=image_prompt_template,
                carousel_image_prompt_template=carousel_image_prompt_template,
                caption_client=caption_client,
                image_client=image_client,
                output_dir=config.post_image_output_dir,
                image_model=image_model,
                image_provider=config.story_image_provider,
                caption_max_tokens=config.post_caption_max_tokens,
                image_max_tokens=config.post_image_max_tokens,
                workers=config.workers,
                apply_logo_overlay_enabled=config.apply_logo_overlay,
                logo_path=config.logo_path,
                generate_images=config.generate_post_images and config.generate_post_content,
                progress_log=config.progress_log,
            )

        story_indexed_items = [
            (index, item)
            for index, item in enumerate(updated_items)
            if item.format_selected == "story"
        ]
        post_indexed_items = [
            (index, item)
            for index, item in enumerate(updated_items)
            if item.format_selected in {"post", "carousel_post"}
        ]

        def generate_story_items() -> list[tuple[int, ScoredItem]]:
            if not config.generate_story_images or not story_indexed_items:
                return []
            prompt_template = config.story_image_prompt_path.read_text(encoding="utf-8")
            generated = generate_story_images_for_scored_items(
                [item for _, item in story_indexed_items],
                prompt_template,
                image_client,
                output_dir=config.story_image_output_dir,
                model=image_model,
                provider=config.story_image_provider,
                max_tokens=config.story_image_max_tokens,
                workers=config.workers,
                apply_logo_overlay_enabled=config.apply_logo_overlay,
                logo_path=config.logo_path,
            )
            return [(index, item) for (index, _), item in zip(story_indexed_items, generated)]

        def generate_post_images() -> list[tuple[int, ScoredItem]]:
            if not config.generate_post_images or not post_indexed_items:
                return []
            if config.generate_post_content:
                return []
            post_items = generate_post_images_for_scored_items(
                [item for _, item in post_indexed_items],
                image_prompt_template=image_prompt_template,
                carousel_image_prompt_template=carousel_image_prompt_template,
                image_client=image_client,
                output_dir=config.post_image_output_dir,
                image_model=image_model,
                image_provider=config.story_image_provider,
                image_max_tokens=config.post_image_max_tokens,
                workers=config.workers,
                apply_logo_overlay_enabled=config.apply_logo_overlay,
                logo_path=config.logo_path,
            )
            return [(index, item) for (index, _), item in zip(post_indexed_items, post_items)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(generate_story_items),
                executor.submit(generate_post_images),
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
        if result.ranked_items:
            top = result.ranked_items[0]
            log_pipeline_progress(
                config,
                f"rank: top score {top.overall_score} — {short_title(top.item.title)}",
            )
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
        log_pipeline_progress(config, f"dedup: {len(result.ranked_items)} -> {len(deduped)} items")
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
        log_pipeline_progress(
            config,
            f"select: kept {len(selected)} items (min score {config.minimum_score}, limit {config.selection_limit})",
        )
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
            VisualContentGenerationStage(),
            DraftPlaceholderStage(),
        ]
    )

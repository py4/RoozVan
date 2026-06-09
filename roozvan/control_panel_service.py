"""Business logic for the RoozVan review control panel."""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any


def panel_log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)

from openrouter_client import DEFAULT_TEXT_MODEL, OpenRouterClient, load_default_env_files
from roozvan.instagram import (
    publish_local_carousel_to_instagram_with_r2,
    publish_local_image_to_instagram_with_r2,
    publish_local_story_image_to_instagram_with_r2,
)
from roozvan.models import ScoredItem
from roozvan.pipeline import PipelineConfig, build_default_pipeline
from roozvan.post_content import (
    build_post_context,
    generate_carousel_slide_image,
    generate_post_image,
    ensure_post_image_background_path,
    normalize_carousel_slides,
    refresh_post_image_overlay,
    refresh_carousel_image_overlays,
    regenerate_instagram_content,
)
from roozvan.story_images import (
    DEFAULT_GEMINI_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_MODEL,
    DEFAULT_STORY_IMAGE_PROVIDER,
    generate_story_image,
    refresh_story_image_overlay,
)
from run_pipeline import build_pipeline_status, load_pipeline_status, write_debug_dump, write_html_report, write_json


class ControlPanelError(RuntimeError):
    """Raised when a control panel action cannot be completed."""


class ControlPanelService:
    def __init__(self, *, dump_dir: Path, repo_root: Path | None = None) -> None:
        load_default_env_files()
        self.dump_dir = dump_dir.resolve()
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self._lock = threading.Lock()

    def reingest(self) -> dict[str, Any]:
        panel_log("reingest: waiting for lock…")
        with self._lock:
            panel_log("reingest: started")
            config = self._reingest_config()
            panel_log(
                "reingest: running pipeline "
                f"(model={config.model}, post_content={config.generate_post_content}, "
                f"max_items={config.max_items or 'all'})"
            )
            started_at = time.perf_counter()
            result = build_default_pipeline().run(config)
            total_elapsed = time.perf_counter() - started_at
            panel_log(
                "reingest: pipeline finished "
                f"(extracted={len(result.items)}, scored={len(result.scored_items)}, "
                f"selected={len(result.selected_items)}, errors={len(result.errors)}, "
                f"elapsed={total_elapsed:.1f}s)"
            )
            if result.errors:
                for error in result.errors[:5]:
                    panel_log(f"reingest: warning: {error}")
                if len(result.errors) > 5:
                    panel_log(f"reingest: …and {len(result.errors) - 5} more warnings")
            write_debug_dump(self.dump_dir, result, config, total_elapsed)
            panel_log(f"reingest: wrote debug dump to {self.dump_dir}")
            stats = build_pipeline_status(result, total_elapsed)
            return {
                "ok": True,
                "selected_count": len(result.selected_items),
                "elapsed_seconds": round(total_elapsed, 2),
                "stats": stats,
                "errors": result.errors[:20],
                "error_count": len(result.errors),
            }

    def status(self) -> dict[str, Any]:
        data = load_pipeline_status(self.dump_dir)
        if data is None:
            return {"ok": True, "status": None}
        return {"ok": True, "status": data}

    def regenerate_text(self, source_index: int) -> dict[str, Any]:
        panel_log(f"regenerate-text: source_index={source_index}")
        with self._lock:
            items = load_selected_items(self.dump_dir)
            item = self._find_item(items, source_index)
            updated, warnings = self._regenerate_text_item(item)
            self._save_items(items, updated)
            return {
                "ok": True,
                "source_index": source_index,
                "format": updated.format_selected,
                "warnings": warnings,
            }

    def regenerate_image(
        self,
        source_index: int,
        *,
        slide: int | None = None,
    ) -> dict[str, Any]:
        panel_log(f"regenerate-image: source_index={source_index} slide={slide}")
        with self._lock:
            items = load_selected_items(self.dump_dir)
            item = self._find_item(items, source_index)
            updated = self._regenerate_image_item(item, slide=slide)
            self._save_items(items, updated)
            return {"ok": True, "source_index": source_index, "slide": slide}

    def publish(self, source_index: int) -> dict[str, Any]:
        panel_log(f"publish: source_index={source_index}")
        with self._lock:
            items = load_selected_items(self.dump_dir)
            item = self._find_item(items, source_index)
            result = self._publish_item(item)
            return {"ok": True, "source_index": source_index, "publish": result.to_dict()}

    def _reingest_config(self) -> PipelineConfig:
        config = load_pipeline_config(self.dump_dir)
        return replace(
            config,
            model=DEFAULT_TEXT_MODEL,
            story_image_model=DEFAULT_STORY_IMAGE_MODEL,
            gemini_story_image_model=DEFAULT_GEMINI_STORY_IMAGE_MODEL,
            max_items=None,
            generate_story_images=False,
            generate_post_images=False,
            generate_post_content=True,
            progress_log=lambda message: panel_log(f"pipeline: {message}"),
        )

    def _save_items(self, items: list[ScoredItem], updated: ScoredItem) -> None:
        merged = [updated if row.source_index == updated.source_index else row for row in items]
        save_selected_items(self.dump_dir, merged)
        write_html_report(self.dump_dir / "index.html", merged)

    def _find_item(self, items: list[ScoredItem], source_index: int) -> ScoredItem:
        for item in items:
            if item.source_index == source_index:
                return item
        raise ControlPanelError(f"No selected item with source_index={source_index}")

    def _caption_client(self, config: PipelineConfig) -> OpenRouterClient:
        return OpenRouterClient(model=config.model, timeout=config.timeout, app_name="RoozVan")

    def _image_client(self, config: PipelineConfig) -> OpenRouterClient:
        image_model = (
            config.gemini_story_image_model
            if config.story_image_provider == "gemini"
            else config.story_image_model
        )
        return OpenRouterClient(
            model=image_model,
            timeout=config.story_image_timeout,
            app_name="RoozVan",
        )

    def _regenerate_text_item(self, item: ScoredItem) -> tuple[ScoredItem, list[str]]:
        config = load_pipeline_config(self.dump_dir)
        caption_client = self._caption_client(config)
        content_prompt = config.instagram_content_prompt_path.read_text(encoding="utf-8")
        panel_log(
            f"regenerate-text: unified content for source_index={item.source_index} "
            f"format={item.format_selected}"
        )
        try:
            updated, warnings = regenerate_instagram_content(
                item,
                content_prompt,
                caption_client,
                max_tokens=max(config.post_caption_max_tokens, 1400),
            )
        except ValueError as exc:
            raise ControlPanelError(str(exc)) from exc

        if updated.format_selected == "story":
            try:
                final_path, background_path = refresh_story_image_overlay(
                    updated,
                    output_dir=config.story_image_output_dir,
                    apply_logo_overlay_enabled=config.apply_logo_overlay,
                    logo_path=config.logo_path,
                )
                updated = replace(
                    updated,
                    item=replace(
                        updated.item,
                        story_image_background_path=str(background_path),
                        story_image_path=str(final_path),
                    ),
                )
            except ValueError as exc:
                warnings.append(f"story overlay refresh skipped: {exc}")

        if updated.format_selected == "carousel_post":
            existing_paths = [path for path in (updated.item.carousel_image_paths or []) if path]
            if existing_paths:
                try:
                    panel_log(
                        f"regenerate-text: refreshing carousel overlays for source_index={updated.source_index}"
                    )
                    final_paths, background_paths = refresh_carousel_image_overlays(
                        updated,
                        output_dir=config.post_image_output_dir,
                        apply_logo_overlay_enabled=config.apply_logo_overlay,
                        logo_path=config.logo_path,
                    )
                    updated = replace(
                        updated,
                        item=replace(
                            updated.item,
                            carousel_image_paths=[str(path) for path in final_paths],
                            carousel_image_background_paths=[str(path) for path in background_paths],
                        ),
                    )
                except ValueError as exc:
                    warnings.append(f"carousel overlay refresh skipped: {exc}")
        if updated.format_selected == "post" and updated.item.post_image_path:
            try:
                panel_log(
                    f"regenerate-text: refreshing post overlay for source_index={updated.source_index}"
                )
                final_path, background_path = refresh_post_image_overlay(
                    updated,
                    output_dir=config.post_image_output_dir,
                    apply_logo_overlay_enabled=config.apply_logo_overlay,
                    logo_path=config.logo_path,
                )
                updated = replace(
                    updated,
                    item=replace(
                        updated.item,
                        post_image_path=str(final_path),
                        post_image_background_path=str(background_path),
                    ),
                )
            except ValueError as exc:
                warnings.append(f"post overlay refresh skipped: {exc}")
        return updated, warnings

    def _regenerate_image_item(self, item: ScoredItem, *, slide: int | None) -> ScoredItem:
        config = load_pipeline_config(self.dump_dir)
        image_client = self._image_client(config)
        image_model = (
            config.gemini_story_image_model
            if config.story_image_provider == "gemini"
            else config.story_image_model
        )

        if item.format_selected == "story":
            story_prompt = config.story_image_prompt_path.read_text(encoding="utf-8")
            background_path, final_path = generate_story_image(
                item,
                story_prompt,
                image_client,
                output_dir=config.story_image_output_dir,
                model=image_model,
                provider=config.story_image_provider,
                max_tokens=config.story_image_max_tokens,
                apply_logo_overlay_enabled=config.apply_logo_overlay,
                logo_path=config.logo_path,
            )
            news = replace(
                item.item,
                story_image_background_path=str(background_path),
                story_image_path=str(final_path),
            )
            return replace(item, item=news)

        if item.format_selected == "post":
            caption = item.evaluation.get("post_caption")
            if not isinstance(caption, dict):
                raise ControlPanelError("Generate post caption/image text before generating the image")
            context = build_post_context(item)
            image_context = {
                **context,
                "image_headline_fa": caption["image_headline_fa"],
                "image_subline_fa": caption["image_subline_fa"],
                "category_label_fa": caption["category_label_fa"],
            }
            post_prompt = config.post_image_prompt_path.read_text(encoding="utf-8")
            path = generate_post_image(
                item,
                post_prompt,
                image_context,
                image_client,
                output_dir=config.post_image_output_dir,
                model=image_model,
                provider=config.story_image_provider,
                max_tokens=config.post_image_max_tokens,
                apply_logo_overlay_enabled=config.apply_logo_overlay,
                logo_path=config.logo_path,
            )
            background_path = ensure_post_image_background_path(item, config.post_image_output_dir)
            news = replace(
                item.item,
                post_image_path=str(path),
                post_image_background_path=str(background_path),
            )
            return replace(item, item=news)

        if item.format_selected == "carousel_post":
            if slide is None:
                raise ControlPanelError("Carousel image regeneration requires slide number")
            carousel_eval = item.evaluation.get("carousel_post") or {}
            slides = normalize_carousel_slides(carousel_eval.get("slides"))
            if slide < 1 or slide > len(slides):
                raise ControlPanelError(f"Invalid carousel slide {slide}; expected 1-{len(slides)}")
            context = build_post_context(item)
            carousel_prompt = config.carousel_image_prompt_path.read_text(encoding="utf-8")
            background_path, path = generate_carousel_slide_image(
                item,
                carousel_prompt,
                context,
                slides[slide - 1],
                slide_number=slide,
                slide_count=len(slides),
                client=image_client,
                output_dir=config.post_image_output_dir,
                model=image_model,
                provider=config.story_image_provider,
                max_tokens=config.post_image_max_tokens,
                apply_logo_overlay_enabled=config.apply_logo_overlay,
                logo_path=config.logo_path,
            )
            paths = list(item.item.carousel_image_paths or [])
            background_paths = list(item.item.carousel_image_background_paths or [])
            while len(paths) < len(slides):
                paths.append("")
            while len(background_paths) < len(slides):
                background_paths.append("")
            paths[slide - 1] = str(path)
            background_paths[slide - 1] = str(background_path)
            news = replace(
                item.item,
                carousel_image_paths=paths,
                carousel_image_background_paths=background_paths,
            )
            return replace(item, item=news)

        raise ControlPanelError(f"Image regeneration is not supported for format {item.format_selected!r}")

    def _publish_item(self, item: ScoredItem):
        news = item.item
        if item.format_selected == "story":
            if not news.story_image_path:
                raise ControlPanelError("Story image is missing")
            return publish_local_story_image_to_instagram_with_r2(
                image_path=news.story_image_path,
            )

        if item.format_selected == "post":
            if not news.post_image_path:
                raise ControlPanelError("Post image is missing")
            if not news.post_caption_fa:
                raise ControlPanelError("Post caption is missing")
            return publish_local_image_to_instagram_with_r2(
                image_path=news.post_image_path,
                caption=news.post_caption_fa,
            )

        if item.format_selected == "carousel_post":
            paths = [path for path in (news.carousel_image_paths or []) if path]
            slides = (item.evaluation.get("carousel_post") or {}).get("slides") or []
            if len(paths) < len(slides):
                raise ControlPanelError("Generate all carousel images before publishing")
            if not news.post_caption_fa:
                raise ControlPanelError("Carousel caption is missing")
            return publish_local_carousel_to_instagram_with_r2(
                image_paths=paths,
                caption=news.post_caption_fa,
            )

        raise ControlPanelError(f"Publishing is not supported for format {item.format_selected!r}")


def load_selected_items(dump_dir: Path) -> list[ScoredItem]:
    selected_path = dump_dir / "selected.json"
    if not selected_path.exists():
        raise ControlPanelError(f"Missing {selected_path}; run reingest or the pipeline first.")
    data = json.loads(selected_path.read_text(encoding="utf-8"))
    return [ScoredItem.from_dict(item) for item in data]


def ensure_preview_html(dump_dir: Path) -> Path:
    """Return index.html, regenerating a preview shell when the file was deleted."""
    index_path = dump_dir / "index.html"
    if index_path.is_file():
        return index_path

    dump_dir.mkdir(parents=True, exist_ok=True)
    selected_path = dump_dir / "selected.json"
    if selected_path.exists():
        data = json.loads(selected_path.read_text(encoding="utf-8"))
        items = [ScoredItem.from_dict(item) for item in data]
    else:
        items = []
    write_html_report(index_path, items)
    panel_log(f"regenerated missing preview HTML at {index_path}")
    return index_path


def save_selected_items(dump_dir: Path, items: list[ScoredItem]) -> None:
    write_json(dump_dir / "selected.json", [item.to_dict() for item in items])
    drafts_path = dump_dir / "post_drafts.json"
    if drafts_path.exists():
        drafts = json.loads(drafts_path.read_text(encoding="utf-8"))
        by_index = {item.source_index: item for item in items}
        for draft in drafts:
            scored = draft.get("scored_item", draft)
            source_index = scored.get("source_index")
            if source_index in by_index:
                if "scored_item" in draft:
                    draft["scored_item"] = by_index[source_index].to_dict()
                else:
                    draft.update(by_index[source_index].to_dict())
        write_json(drafts_path, drafts)


def normalize_story_image_provider(provider: str | None) -> str:
    normalized = (provider or DEFAULT_STORY_IMAGE_PROVIDER).strip().lower()
    if normalized == "gemini":
        return DEFAULT_STORY_IMAGE_PROVIDER
    if normalized in {"openrouter", "gemini"}:
        return normalized
    return DEFAULT_STORY_IMAGE_PROVIDER


def load_pipeline_config(dump_dir: Path) -> PipelineConfig:
    config_path = dump_dir / "config.json"
    if not config_path.exists():
        return PipelineConfig()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return PipelineConfig(
        sources_path=Path(data.get("sources_path", "sources.txt")),
        scoring_prompt_path=Path(data.get("scoring_prompt_path", "scoring_prompt.md")),
        instagram_content_prompt_path=Path(
            data.get("instagram_content_prompt_path", "prompts/instagram_content_generation.md")
        ),
        story_image_prompt_path=Path(data.get("story_image_prompt_path", "prompts/story_image_generation.md")),
        post_image_prompt_path=Path(data.get("post_image_prompt_path", "prompts/post_image_generation.md")),
        post_caption_prompt_path=Path(data.get("post_caption_prompt_path", "prompts/post_caption_generation.md")),
        carousel_content_prompt_path=Path(
            data.get("carousel_content_prompt_path", "prompts/carousel_content_generation.md")
        ),
        carousel_image_prompt_path=Path(
            data.get("carousel_image_prompt_path", "prompts/carousel_image_background_generation.md")
        ),
        model=data.get("model", DEFAULT_TEXT_MODEL),
        story_image_model=data.get("story_image_model", DEFAULT_STORY_IMAGE_MODEL),
        gemini_story_image_model=data.get("gemini_story_image_model", DEFAULT_GEMINI_STORY_IMAGE_MODEL),
        story_image_provider=normalize_story_image_provider(data.get("story_image_provider")),
        timeout=int(data.get("timeout", 60)),
        story_image_timeout=int(data.get("story_image_timeout", 300)),
        max_items=data.get("max_items"),
        max_tokens=int(data.get("max_tokens", 600)),
        story_image_max_tokens=data.get("story_image_max_tokens"),
        post_caption_max_tokens=int(data.get("post_caption_max_tokens", 900)),
        post_image_max_tokens=data.get("post_image_max_tokens"),
        workers=int(data.get("workers", 16)),
        selection_limit=int(data.get("selection_limit", 20)),
        minimum_score=float(data.get("minimum_score", 12)),
        recency_boost_enabled=bool(data.get("recency_boost_enabled", True)),
        feel_good_boost_enabled=bool(data.get("feel_good_boost_enabled", True)),
        generate_story_images=bool(data.get("generate_story_images", False)),
        generate_post_content=bool(data.get("generate_post_content", True)),
        generate_post_images=bool(data.get("generate_post_images", False)),
        story_image_output_dir=Path(data.get("story_image_output_dir", "generated_story_images")),
        post_image_output_dir=Path(data.get("post_image_output_dir", "generated_post_images")),
        logo_path=Path(data.get("logo_path", "assets/logo.png")),
        apply_logo_overlay=bool(data.get("apply_logo_overlay", True)),
    )

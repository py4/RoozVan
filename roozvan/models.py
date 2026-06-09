"""Shared data models for the RoozVan pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NewsItem:
    title: str | None
    description: str | None
    date: str | None
    url: str | None
    image_url: str | None
    source_url: str | None = None
    article_content: str | None = None
    article_readable_without_js: bool | None = None
    story_image_path: str | None = None
    story_image_background_path: str | None = None
    post_image_path: str | None = None
    post_image_background_path: str | None = None
    carousel_image_paths: list[str] | None = None
    carousel_image_background_paths: list[str] | None = None
    post_caption_fa: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NewsItem":
        return cls(
            title=optional_text(data.get("title")),
            description=optional_text(data.get("description")),
            date=optional_text(data.get("date")),
            url=optional_text(data.get("url")),
            image_url=optional_text(data.get("image_url")),
            source_url=optional_text(data.get("source_url")),
            article_content=optional_text(data.get("article_content")),
            article_readable_without_js=optional_bool(data.get("article_readable_without_js")),
            story_image_path=optional_text(data.get("story_image_path")),
            story_image_background_path=optional_text(data.get("story_image_background_path")),
            post_image_path=optional_text(data.get("post_image_path")),
            post_image_background_path=optional_text(data.get("post_image_background_path")),
            carousel_image_paths=optional_text_list(data.get("carousel_image_paths")),
            carousel_image_background_paths=optional_text_list(data.get("carousel_image_background_paths")),
            post_caption_fa=optional_text(data.get("post_caption_fa")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "date": self.date,
            "url": self.url,
            "image_url": self.image_url,
            "source_url": self.source_url,
            "article_content": self.article_content,
            "article_readable_without_js": self.article_readable_without_js,
            "story_image_path": self.story_image_path,
            "story_image_background_path": self.story_image_background_path,
            "post_image_path": self.post_image_path,
            "post_image_background_path": self.post_image_background_path,
            "carousel_image_paths": self.carousel_image_paths,
            "carousel_image_background_paths": self.carousel_image_background_paths,
            "post_caption_fa": self.post_caption_fa,
        }

    def to_scoring_dict(self) -> dict[str, str | None]:
        return {
            "title": self.title,
            "description": self.description,
            "date": self.date,
            "url": self.url,
            "image_url": self.image_url,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class ScoredItem:
    source_index: int
    item: NewsItem
    evaluation: dict[str, Any]
    overall_score: float
    format_selected: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScoredItem":
        return cls(
            source_index=int(data["source_index"]),
            item=NewsItem.from_dict(data["item"]),
            evaluation=dict(data["evaluation"]),
            overall_score=float(data["overall_score"]),
            format_selected=optional_text(data.get("format_selected")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_index": self.source_index,
            "item": self.item.to_dict(),
            "evaluation": self.evaluation,
            "overall_score": self.overall_score,
            "format_selected": self.format_selected,
        }


@dataclass(frozen=True)
class PostDraft:
    scored_item: ScoredItem
    image_prompt_fa: str | None = None
    caption_fa: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scored_item": self.scored_item.to_dict(),
            "image_prompt_fa": self.image_prompt_fa,
            "caption_fa": self.caption_fa or self.scored_item.item.post_caption_fa,
        }


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return bool(value)


def optional_text_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    output = [text for item in value if (text := optional_text(item))]
    return output or None

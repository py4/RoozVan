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
    article_content: str | None = None
    article_readable_without_js: bool | None = None
    story_image_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NewsItem":
        return cls(
            title=optional_text(data.get("title")),
            description=optional_text(data.get("description")),
            date=optional_text(data.get("date")),
            url=optional_text(data.get("url")),
            image_url=optional_text(data.get("image_url")),
            article_content=optional_text(data.get("article_content")),
            article_readable_without_js=optional_bool(data.get("article_readable_without_js")),
            story_image_path=optional_text(data.get("story_image_path")),
        )

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "title": self.title,
            "description": self.description,
            "date": self.date,
            "url": self.url,
            "image_url": self.image_url,
            "article_content": self.article_content,
            "article_readable_without_js": self.article_readable_without_js,
            "story_image_path": self.story_image_path,
        }

    def to_scoring_dict(self) -> dict[str, str | None]:
        return {
            "title": self.title,
            "description": self.description,
            "date": self.date,
            "url": self.url,
            "image_url": self.image_url,
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
            "caption_fa": self.caption_fa,
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

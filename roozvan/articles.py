"""Article page fetching and static-content extraction."""

from __future__ import annotations

import html
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from html.parser import HTMLParser

from roozvan.models import NewsItem
from roozvan.progress import ProgressLogger, log_progress, short_title
from roozvan.progress import ProgressLogger, log_progress, short_title


MIN_READABLE_CHARS = 500


@dataclass(frozen=True)
class ArticleExtraction:
    content: str | None
    readable_without_js: bool


class CBCArticleParser(HTMLParser):
    """Extract visible paragraph text from CBC's static story body."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._div_stack: list[bool] = []
        self._blocked_stack: list[bool] = []
        self._capture_tag: str | None = None
        self._capture_parts: list[str] = []
        self.paragraphs: list[str] = []
        self.meta_description: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "meta":
            name = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            content = attrs_dict.get("content")
            if name in {"description", "og:description"} and content and not self.meta_description:
                self.meta_description = content.strip()
            return

        if tag == "div":
            classes = set((attrs_dict.get("class") or "").split())
            blocked_classes = {"mediaEmbed", "player-placeholder-ui-container"}
            parent_blocked = self._blocked_stack[-1] if self._blocked_stack else False
            self._blocked_stack.append(parent_blocked or bool(classes & blocked_classes))
            parent_in_story = self._div_stack[-1] if self._div_stack else False
            self._div_stack.append(parent_in_story or "story" in classes)
            return

        if self.in_story and not self.in_blocked_content and tag in {"p", "li", "h2", "h3"}:
            self._capture_tag = tag
            self._capture_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == self._capture_tag:
            text = normalize_text(" ".join(self._capture_parts))
            if text and not looks_like_media_chrome(text):
                self.paragraphs.append(text)
            self._capture_tag = None
            self._capture_parts = []

        if tag == "div" and self._div_stack:
            self._div_stack.pop()
        if tag == "div" and self._blocked_stack:
            self._blocked_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._capture_tag and not self.in_blocked_content:
            self._capture_parts.append(data)

    @property
    def in_story(self) -> bool:
        return bool(self._div_stack and self._div_stack[-1])

    @property
    def in_blocked_content(self) -> bool:
        return bool(self._blocked_stack and self._blocked_stack[-1])


def fetch_article_html(url: str, timeout: int) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "roozvan/1.0 (+https://example.local)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_article_content(html_text: str) -> ArticleExtraction:
    parser = CBCArticleParser()
    parser.feed(html_text)

    content = "\n\n".join(dedup_preserving_order(parser.paragraphs))
    if len(content) >= MIN_READABLE_CHARS:
        return ArticleExtraction(content=content, readable_without_js=True)

    fallback = extract_json_ld_description(html_text) or parser.meta_description
    fallback = normalize_text(fallback or "")
    return ArticleExtraction(content=fallback or None, readable_without_js=False)


def fetch_and_extract_article(url: str, timeout: int, max_chars: int | None = None) -> ArticleExtraction:
    html_text = fetch_article_html(url, timeout)
    extraction = extract_article_content(html_text)
    if extraction.content and max_chars is not None:
        return ArticleExtraction(
            content=truncate_text(extraction.content, max_chars),
            readable_without_js=extraction.readable_without_js,
        )
    return extraction


def enrich_items_with_articles(
    items: list[NewsItem],
    timeout: int,
    max_chars: int | None = None,
    *,
    progress_log: ProgressLogger | None = None,
) -> list[NewsItem]:
    enriched = []
    total = len(items)
    for index, item in enumerate(items, start=1):
        if not item.url:
            enriched.append(item)
            log_progress(progress_log, f"article: {index}/{total} skipped (no URL)")
            continue

        log_progress(progress_log, f"article: {index}/{total} fetching — {short_title(item.title)}")
        try:
            extraction = fetch_and_extract_article(item.url, timeout, max_chars=max_chars)
        except (OSError, urllib.error.URLError, ValueError) as exc:
            print(f"warning: failed to fetch article {item.url}: {exc}", file=sys.stderr)
            log_progress(progress_log, f"article: {index}/{total} failed — {short_title(item.title)}")
            enriched.append(replace(item, article_readable_without_js=False))
            continue

        enriched.append(
            replace(
                item,
                article_content=extraction.content,
                article_readable_without_js=extraction.readable_without_js,
            )
        )
        readable = "readable" if extraction.readable_without_js else "partial"
        log_progress(progress_log, f"article: {index}/{total} {readable} — {short_title(item.title)}")
    return enriched


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def looks_like_media_chrome(value: str) -> bool:
    lowered = value.lower()
    media_markers = (
        "duration ",
        "close captions available",
        "watch |",
        "listen to this article",
    )
    return any(marker in lowered for marker in media_markers)


def dedup_preserving_order(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def extract_json_ld_description(html_text: str) -> str | None:
    match = re.search(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None

    description_match = re.search(r'"description"\s*:\s*"((?:\\.|[^"\\])*)"', match.group(1))
    if not description_match:
        return None
    return bytes(description_match.group(1), "utf-8").decode("unicode_escape")


def truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rsplit(" ", 1)[0].rstrip() + "..."

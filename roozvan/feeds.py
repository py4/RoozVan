"""RSS/Atom extraction for RoozVan news sources."""

from __future__ import annotations

import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from roozvan.models import NewsItem
from roozvan.progress import ProgressLogger, log_progress
from roozvan.vancouver_is_awesome import collect_vancouver_is_awesome_items, is_vancouver_is_awesome_source


NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
}
DEFAULT_MAX_ITEM_AGE_DAYS = 2


class FirstImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.src: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.src or tag.lower() != "img":
            return
        attrs_dict = dict(attrs)
        self.src = attrs_dict.get("src") or attrs_dict.get("data-src")


def read_sources(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def read_feed(source: str, timeout: int) -> bytes:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in {"http", "https"}:
        request = urllib.request.Request(
            source,
            headers={"User-Agent": "roozvan/1.0 (+https://example.local)"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    return Path(source).read_bytes()


def text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def find_child(item: ET.Element, name: str) -> ET.Element | None:
    element = item.find(name, NS)
    if element is not None:
        return element

    expected = name.split(":", 1)[-1]
    for child in item:
        if local_name(child.tag) == expected:
            return child
    return None


def find_children(item: ET.Element, name: str) -> list[ET.Element]:
    elements = item.findall(name, NS)
    if elements:
        return elements

    expected = name.split(":", 1)[-1]
    return [child for child in item if local_name(child.tag) == expected]


def child_text(item: ET.Element, names: Iterable[str]) -> str | None:
    for name in names:
        value = text(find_child(item, name))
        if value:
            return value
    return None


def atom_link(item: ET.Element) -> str | None:
    fallback = None
    for link in find_children(item, "atom:link"):
        href = link.attrib.get("href")
        if not href:
            continue
        rel = link.attrib.get("rel", "alternate")
        if rel == "alternate":
            return href
        fallback = fallback or href
    return fallback


def html_first_image(html: str | None, base_url: str | None) -> str | None:
    if not html:
        return None
    parser = FirstImageParser()
    parser.feed(html)
    if not parser.src:
        return None
    return urllib.parse.urljoin(base_url or "", parser.src)


def image_url(item: ET.Element, base_url: str | None) -> str | None:
    media_content = find_child(item, "media:content")
    if media_content is not None:
        url = media_content.attrib.get("url")
        medium = media_content.attrib.get("medium")
        mime = media_content.attrib.get("type", "")
        if url and (medium == "image" or mime.startswith("image/") or not mime):
            return urllib.parse.urljoin(base_url or "", url)

    for path in ("media:thumbnail", "itunes:image"):
        element = find_child(item, path)
        if element is not None:
            url = element.attrib.get("url") or element.attrib.get("href")
            if url:
                return urllib.parse.urljoin(base_url or "", url)

    for enclosure in find_children(item, "enclosure"):
        url = enclosure.attrib.get("url")
        mime = enclosure.attrib.get("type", "")
        if url and mime.startswith("image/"):
            return urllib.parse.urljoin(base_url or "", url)

    html = child_text(item, ["content:encoded", "description", "summary", "atom:content", "atom:summary"])
    return html_first_image(html, base_url)


def rss_items(root: ET.Element) -> list[ET.Element]:
    channel = find_child(root, "channel")
    if channel is not None:
        return find_children(channel, "item")
    return find_children(root, "item")


def entry_date(item: ET.Element) -> str | None:
    return child_text(item, ["pubDate", "date", "dc:date", "atom:published", "atom:updated"])


def atom_items(root: ET.Element) -> list[ET.Element]:
    """Return article entries, including nested Google PCN rundown items."""
    direct = root.findall("atom:entry", NS)
    nested = [
        entry
        for entry in root.iter()
        if local_name(entry.tag) == "entry" and child_text(entry, ["title", "atom:title"])
    ]
    if len(nested) > len(direct):
        return nested
    return [entry for entry in direct if child_text(entry, ["title", "atom:title"])] or direct


def wrapper_entry_date(root: ET.Element, item: ET.Element) -> str | None:
    for wrapper in root.findall("atom:entry", NS):
        if item in wrapper.iter():
            date = entry_date(wrapper)
            if date:
                return date
    return entry_date(root)


def parse_feed(data: bytes, source: str) -> list[NewsItem]:
    root = ET.fromstring(data)
    is_atom = root.tag.endswith("feed")
    items = atom_items(root) if is_atom else rss_items(root)
    results = []

    for item in items:
        post_url = child_text(item, ["link"]) or atom_link(item)
        title = child_text(item, ["title", "atom:title"])
        if not title or not post_url:
            continue
        date = entry_date(item)
        if is_atom and not date:
            date = wrapper_entry_date(root, item)
        results.append(
            NewsItem(
                title=title,
                description=child_text(item, ["description", "summary", "atom:summary", "content:encoded", "atom:content"]),
                date=date,
                url=post_url,
                image_url=image_url(item, post_url or source),
                source_url=source,
            )
        )

    return results


def item_published_at(item: NewsItem) -> datetime | None:
    if not item.date:
        return None
    raw_date = item.date.strip()
    try:
        published = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError, IndexError, AttributeError):
        try:
            published = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published.astimezone(timezone.utc)


def is_recent_enough(
    item: NewsItem,
    *,
    max_age_days: int | None = DEFAULT_MAX_ITEM_AGE_DAYS,
    now: datetime | None = None,
) -> bool:
    if max_age_days is None:
        return True
    published_at = item_published_at(item)
    if published_at is None:
        return True
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = reference - timedelta(days=max_age_days)
    return published_at >= cutoff


def filter_recent_items(
    items: list[NewsItem],
    *,
    max_age_days: int | None = DEFAULT_MAX_ITEM_AGE_DAYS,
    now: datetime | None = None,
) -> list[NewsItem]:
    return [item for item in items if is_recent_enough(item, max_age_days=max_age_days, now=now)]


def collect_news_items(
    sources_path: Path,
    timeout: int,
    *,
    max_item_age_days: int | None = DEFAULT_MAX_ITEM_AGE_DAYS,
    errors: list[str] | None = None,
    progress_log: ProgressLogger | None = None,
) -> list[NewsItem]:
    output = []
    for source in read_sources(sources_path):
        log_progress(progress_log, f"extract: fetching {source}")
        try:
            if is_vancouver_is_awesome_source(source):
                parsed = collect_vancouver_is_awesome_items(source, timeout)
            else:
                parsed = parse_feed(read_feed(source, timeout), source)
            recent = filter_recent_items(parsed, max_age_days=max_item_age_days)
            output.extend(recent)
            skipped = len(parsed) - len(recent)
            if skipped:
                log_progress(
                    progress_log,
                    f"extract: {source} -> {len(recent)} items ({skipped} older than {max_item_age_days}d skipped)",
                )
            else:
                log_progress(progress_log, f"extract: {source} -> {len(recent)} items")
        except (OSError, ET.ParseError, urllib.error.URLError) as exc:
            message = f"failed to read {source}: {exc}"
            log_progress(progress_log, f"extract: failed {source} — {exc}")
            if errors is not None:
                errors.append(message)
            else:
                print(f"warning: {message}", file=sys.stderr)
    return output


def collect_items(sources_path: Path, timeout: int) -> list[dict[str, Any]]:
    return [item.to_dict() for item in collect_news_items(sources_path, timeout)]

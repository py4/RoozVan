"""RSS/Atom extraction for RoozVan news sources."""

from __future__ import annotations

import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from roozvan.models import NewsItem


NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
}


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


def atom_items(root: ET.Element) -> list[ET.Element]:
    return root.findall("atom:entry", NS)


def parse_feed(data: bytes, source: str) -> list[NewsItem]:
    root = ET.fromstring(data)
    is_atom = root.tag.endswith("feed")
    items = atom_items(root) if is_atom else rss_items(root)
    results = []

    for item in items:
        post_url = child_text(item, ["link"]) or atom_link(item)
        results.append(
            NewsItem(
                title=child_text(item, ["title", "atom:title"]),
                description=child_text(item, ["description", "summary", "atom:summary", "content:encoded", "atom:content"]),
                date=child_text(item, ["pubDate", "date", "dc:date", "atom:published", "atom:updated"]),
                url=post_url,
                image_url=image_url(item, post_url or source),
            )
        )

    return results


def collect_news_items(sources_path: Path, timeout: int) -> list[NewsItem]:
    output = []
    for source in read_sources(sources_path):
        try:
            output.extend(parse_feed(read_feed(source, timeout), source))
        except (OSError, ET.ParseError, urllib.error.URLError) as exc:
            print(f"warning: failed to read {source}: {exc}", file=sys.stderr)
    return output


def collect_items(sources_path: Path, timeout: int) -> list[dict[str, str | None]]:
    return [item.to_dict() for item in collect_news_items(sources_path, timeout)]

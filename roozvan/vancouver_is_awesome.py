"""Browser-backed extraction for Vancouver Is Awesome listing pages."""

from __future__ import annotations

import html
import re
import shutil
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser

from roozvan.models import NewsItem


DEFAULT_LOCAL_NEWS_TEMPLATE = "https://www.vancouverisawesome.com/local-news?page=PAGE_NUMBER"
PAGE_TOKEN = "PAGE_NUMBER"
SOURCE_HOST = "vancouverisawesome.com"
MIN_ARTICLE_CHARS = 300


class VancouverIsAwesomeError(OSError):
    """Raised when the Vancouver Is Awesome scraper cannot run."""


@dataclass(frozen=True)
class ListingArticle:
    title: str
    url: str


class LinkTextParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._href_stack: list[str | None] = []
        self._parts: list[str] = []
        self.links: list[ListingArticle] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        absolute = urllib.parse.urljoin(self.base_url, href) if href else None
        self._href_stack.append(absolute)
        self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href_stack:
            return
        href = self._href_stack.pop()
        text = normalize_text(" ".join(self._parts))
        self._parts = []
        if href and text and is_article_url(href):
            self.links.append(ListingArticle(title=text, url=href))

    def handle_data(self, data: str) -> None:
        if self._href_stack:
            self._parts.append(data)


class ArticlePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.description: str | None = None
        self.date: str | None = None
        self.image_url: str | None = None
        self._in_title_tag = False
        self._in_article = 0
        self._capture_tag: str | None = None
        self._capture_parts: list[str] = []
        self._title_parts: list[str] = []
        self.article_parts: list[str] = []
        self.fallback_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag == "meta":
            self._handle_meta(attrs_dict)
            return
        if tag == "time" and not self.date:
            self.date = attrs_dict.get("datetime")

        if tag == "article" or "articlebody" in normalized_attr(attrs_dict.get("itemprop")):
            self._in_article += 1
        if tag == "h1":
            self._in_title_tag = True
            self._title_parts = []
        if tag in {"p", "li", "h2", "h3"}:
            self._capture_tag = tag
            self._capture_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "h1" and self._in_title_tag:
            title = normalize_text(" ".join(self._title_parts))
            self.title = self.title or title or None
            self._in_title_tag = False
            self._title_parts = []

        if tag == self._capture_tag:
            text = normalize_text(" ".join(self._capture_parts))
            if text and not looks_like_page_chrome(text):
                if self._in_article:
                    self.article_parts.append(text)
                else:
                    self.fallback_parts.append(text)
            self._capture_tag = None
            self._capture_parts = []

        if tag == "article" and self._in_article:
            self._in_article -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title_tag:
            self._title_parts.append(data)
        if self._capture_tag:
            self._capture_parts.append(data)

    def _handle_meta(self, attrs: dict[str, str | None]) -> None:
        name = (attrs.get("name") or attrs.get("property") or "").lower()
        content = normalize_text(attrs.get("content") or "")
        if not content:
            return
        if name in {"description", "og:description"} and not self.description:
            self.description = content
        elif name in {"og:title", "twitter:title"} and not self.title:
            self.title = strip_site_suffix(content)
        elif name in {"article:published_time", "date", "datepublished"} and not self.date:
            self.date = content
        elif name in {"og:image", "twitter:image"} and not self.image_url:
            self.image_url = content


def collect_vancouver_is_awesome_items(source: str, timeout: int, pages: int = 3) -> list[NewsItem]:
    """Extract listing items and full article text from the first Vancouver Is Awesome pages."""
    with BrowserSession(timeout=timeout) as browser:
        listing_articles: list[ListingArticle] = []
        seen_listing_urls: set[str] = set()
        for page_number in range(1, pages + 1):
            page_url = page_url_for(source, page_number)
            html_text = browser.open(page_url)
            if is_cloudflare_challenge(html_text):
                raise VancouverIsAwesomeError(f"Cloudflare challenge blocked {page_url}")
            for article in parse_listing_articles(html_text, page_url):
                if article.url in seen_listing_urls:
                    continue
                seen_listing_urls.add(article.url)
                listing_articles.append(article)

        items: list[NewsItem] = []
        for listing_article in listing_articles:
            html_text = browser.open(listing_article.url)
            if is_cloudflare_challenge(html_text):
                raise VancouverIsAwesomeError(f"Cloudflare challenge blocked {listing_article.url}")
            items.append(parse_article_page(html_text, listing_article, source))
        return items


def is_vancouver_is_awesome_source(source: str) -> bool:
    parsed = urllib.parse.urlparse(source)
    host = parsed.netloc.lower()
    return host == SOURCE_HOST or host.endswith(f".{SOURCE_HOST}")


def page_url_for(source: str, page_number: int) -> str:
    if PAGE_TOKEN in source:
        return source.replace(PAGE_TOKEN, str(page_number))

    parsed = urllib.parse.urlparse(source)
    if parsed.path.startswith("/local-news"):
        query = urllib.parse.parse_qs(parsed.query)
        query["page"] = [str(page_number)]
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))

    return DEFAULT_LOCAL_NEWS_TEMPLATE.replace(PAGE_TOKEN, str(page_number))


def parse_listing_articles(html_text: str, base_url: str) -> list[ListingArticle]:
    parser = LinkTextParser(base_url)
    parser.feed(html_text)
    output: list[ListingArticle] = []
    seen_urls: set[str] = set()
    for article in parser.links:
        if article.url in seen_urls:
            continue
        seen_urls.add(article.url)
        output.append(article)
    return output


def parse_article_page(html_text: str, listing_article: ListingArticle, source: str) -> NewsItem:
    parser = ArticlePageParser()
    parser.feed(html_text)
    article_parts = parser.article_parts if joined_length(parser.article_parts) >= MIN_ARTICLE_CHARS else parser.fallback_parts
    article_content = "\n\n".join(dedup_preserving_order(article_parts))
    return NewsItem(
        title=parser.title or listing_article.title,
        description=parser.description,
        date=parser.date,
        url=listing_article.url,
        image_url=parser.image_url,
        source_url=source,
        article_content=article_content or parser.description,
        article_readable_without_js=bool(article_content),
    )


def is_article_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if not is_vancouver_is_awesome_source(url):
        return False
    path = parsed.path.rstrip("/")
    if not path.startswith("/local-news/"):
        return False
    slug = path.rsplit("/", 1)[-1]
    return bool(re.search(r"\d{5,}$", slug))


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def is_cloudflare_challenge(html_text: str) -> bool:
    lowered = html_text[:4000].lower()
    return "just a moment" in lowered and "challenges.cloudflare.com" in lowered


def normalized_attr(value: str | None) -> str:
    return (value or "").strip().lower()


def strip_site_suffix(value: str) -> str:
    return re.sub(r"\s+-\s+Vancouver Is Awesome\s*$", "", value, flags=re.IGNORECASE).strip()


def looks_like_page_chrome(value: str) -> bool:
    lowered = value.lower()
    if len(value) < 35:
        return True
    chrome_markers = (
        "sign in or register",
        "subscribe",
        "follow us",
        "advertisement",
        "share by email",
        "listen to this article",
        "more local news",
        "vancouver is awesome",
    )
    return any(marker in lowered for marker in chrome_markers)


def joined_length(values: list[str]) -> int:
    return sum(len(value) for value in values)


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


class BrowserSession:
    def __init__(self, timeout: int) -> None:
        self.timeout_ms = timeout * 1000
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "BrowserSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise VancouverIsAwesomeError(
                "Vancouver Is Awesome scraping requires Playwright: "
                "python3 -m pip install playwright && python3 -m playwright install chromium"
            ) from exc

        self._playwright = sync_playwright().start()
        try:
            chrome_path = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
            launch_options = {"headless": True}
            if chrome_path:
                launch_options["executable_path"] = chrome_path
            self._browser = self._playwright.chromium.launch(**launch_options)
            self._page = self._browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                locale="en-CA",
            )
        except Exception as exc:
            self.__exit__(None, None, None)
            raise VancouverIsAwesomeError(f"failed to start Playwright browser: {exc}") from exc
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def open(self, url: str) -> str:
        if self._page is None:
            raise VancouverIsAwesomeError("browser session was not started")
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            deadline_ms = max(self.timeout_ms, 2_000)
            waited_ms = 0
            while waited_ms < deadline_ms:
                self._page.wait_for_timeout(2_000)
                waited_ms += 2_000
                html_text = self._page.content()
                if not is_cloudflare_challenge(html_text):
                    return html_text
            return self._page.content()
        except Exception as exc:
            raise VancouverIsAwesomeError(f"failed to open {url}: {exc}") from exc

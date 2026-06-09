from datetime import datetime, timezone

from roozvan.feeds import filter_recent_items, item_published_at, parse_feed
from roozvan.models import NewsItem, ScoredItem
from roozvan.scoring import rank_scored_items


GLOBAL_NEWS_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
    xmlns:content="http://purl.org/rss/1.0/modules/content/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title> : BC</title>
    <link>https://globalnews.ca</link>
    <description></description>
    <item>
      <title>&#8216;Billionaire greed&#8217;: Some Vancouver businesses concerned about FIFA World Cup</title>
      <link>https://globalnews.ca/news/11895199/vancouver-businesses-concerned-fifa-world-cup/</link>
      <dc:creator><![CDATA[Amy Judd]]></dc:creator>
      <pubDate>Mon, 08 Jun 2026 23:14:33 +0000</pubDate>
      <guid isPermaLink="false">https://globalnews.ca/?p=11895199</guid>
      <description><![CDATA[The owners and operators of three Vancouver businesses are already experiencing challenges with the influence that the World Cup has on the city.]]></description>
      <content:encoded><![CDATA[The owners and operators of three Vancouver businesses are already experiencing challenges with the influence that the World Cup has on the city.]]></content:encoded>
      <enclosure url="https://globalnews.ca/wp-content/uploads/2026/06/WEB-FIFA-STILL.png?w=720&amp;h=480&amp;crop=1" length="95315000" type="image/jpeg"/>
      <media:thumbnail url="https://globalnews.ca/wp-content/uploads/2026/06/WEB-FIFA-STILL.png" />
      <media:content url="https://globalnews.ca/wp-content/uploads/2026/06/WEB-FIFA-STILL.png" medium="image">
        <media:title type="html">WEB FIFA STILL</media:title>
      </media:content>
    </item>
    <item>
      <title>Metro Vancouver enters Stage 3 water restrictions as snowpack melts a month early</title>
      <link>https://globalnews.ca/news/11895241/metro-vancouver-stage-3-water-restriction/</link>
      <pubDate>Tue, 09 Jun 2026 01:24:08 +0000</pubDate>
      <description><![CDATA[The First Narrows Crossing is expected to be back in service at the end of July and water restrictions will be reassessed then, according to Metro Vancouver.]]></description>
      <media:content url="https://globalnews.ca/wp-content/uploads/2023/08/Chilliwack-golden-lawn.png" medium="image" />
      <media:content url="https://globalnews.ca/wp-content/uploads/2023/08/Chilliwack-golden-lawn.png?w=300" medium="image" />
    </item>
  </channel>
</rss>
"""


def test_parse_global_news_bc_feed_extracts_scoring_fields() -> None:
    items = parse_feed(GLOBAL_NEWS_FEED, "https://globalnews.ca/bc/feed/")

    assert len(items) == 2
    assert items[0].title == "‘Billionaire greed’: Some Vancouver businesses concerned about FIFA World Cup"
    assert items[0].description == (
        "The owners and operators of three Vancouver businesses are already experiencing challenges "
        "with the influence that the World Cup has on the city."
    )
    assert items[0].url == "https://globalnews.ca/news/11895199/vancouver-businesses-concerned-fifa-world-cup/"
    assert items[0].image_url == "https://globalnews.ca/wp-content/uploads/2026/06/WEB-FIFA-STILL.png"
    assert items[0].source_url == "https://globalnews.ca/bc/feed/"

    scoring_payload = items[0].to_scoring_dict()
    assert scoring_payload["title"]
    assert scoring_payload["description"]
    assert scoring_payload["url"].startswith("https://globalnews.ca/news/")


def test_global_news_items_can_be_ranked_after_scoring() -> None:
    items = parse_feed(GLOBAL_NEWS_FEED, "https://globalnews.ca/bc/feed/")
    scored = [
        ScoredItem(source_index=0, item=items[0], evaluation={}, overall_score=10),
        ScoredItem(source_index=1, item=items[1], evaluation={}, overall_score=10),
    ]

    ranked = rank_scored_items(scored)

    assert ranked[0].item.title == "Metro Vancouver enters Stage 3 water restrictions as snowpack melts a month early"


def test_filter_recent_items_drops_dated_items_older_than_two_days() -> None:
    now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
    items = [
        NewsItem("recent", None, "Tue, 09 Jun 2026 01:00:00 +0000", "https://example.com/recent", None),
        NewsItem("borderline", None, "Sun, 07 Jun 2026 12:00:00 +0000", "https://example.com/borderline", None),
        NewsItem("old", None, "Sun, 07 Jun 2026 11:59:59 +0000", "https://example.com/old", None),
        NewsItem("missing date", None, None, "https://example.com/missing", None),
        NewsItem("bad date", None, "not a date", "https://example.com/bad", None),
        NewsItem("future", None, "Wed, 10 Jun 2026 01:00:00 +0000", "https://example.com/future", None),
    ]

    filtered = filter_recent_items(items, now=now)

    assert [item.title for item in filtered] == [
        "recent",
        "borderline",
        "missing date",
        "bad date",
        "future",
    ]


def test_item_published_at_supports_atom_iso_dates() -> None:
    item = NewsItem("atom", None, "2026-06-09T01:02:03Z", "https://example.com/atom", None)

    assert item_published_at(item) == datetime(2026, 6, 9, 1, 2, 3, tzinfo=timezone.utc)

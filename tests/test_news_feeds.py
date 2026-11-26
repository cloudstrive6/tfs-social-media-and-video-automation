"""Trend scout news feeds: a dead outlet is skipped, headlines carry their outlet tier, untitled items are dropped."""
from types import SimpleNamespace

import feedparser

from tfs.agents import trend_scout as ts

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Senate approves budget</title><link>https://a/1</link></item>
<item><link>https://a/2</link></item>
</channel></rss>"""


def test_dead_feed_is_skipped_and_tier_kept(monkeypatch):
    feeds = [{"name": "Dead", "tier": "national", "url": "https://dead"},
             {"name": "Live", "tier": "regional", "url": "https://live"}]
    monkeypatch.setattr(ts, "sources", lambda: {"news_rss": feeds})

    def fake_get(url, **kw):
        if "dead" in url:
            raise ConnectionError("remote end closed")
        return SimpleNamespace(content=RSS)

    monkeypatch.setattr(ts, "_get", fake_get)
    out = ts.news("run")
    assert [o["title"] for o in out] == ["Senate approves budget"]
    assert out[0]["tier"] == "regional" and out[0]["feed"] == "Live"


def test_every_configured_feed_has_a_tier():
    feeds = ts.sources()["news_rss"]
    assert len(feeds) >= 15
    assert all(f.get("tier") in {"national", "aggregator", "regional", "filipino"} for f in feeds)
    assert feedparser  # parser is installed

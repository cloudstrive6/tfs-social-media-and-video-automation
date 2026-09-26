"""Trend Scout: collect raw signals, compute velocity vs. earlier runs, let Claude rank what's about to peak."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from urllib.parse import quote

import feedparser
import requests
from bs4 import BeautifulSoup

from .. import db, llm
from ..config import env, now, sources
from ..models import TrendReport

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (TFS trend scout; +https://www.youtube.com/@TheFilipinoStandard)"}


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=20, **kw)
    r.raise_for_status()
    return r


def _velocity(source: str, key: str, value: float, run_started: str) -> dict:
    prev = db.previous_signal(source, key, run_started)
    db.add_signal(source, key, value)
    return {"now": value, "prev": prev}


# ---------- collectors (each returns a list of plain dicts; failures are logged, not fatal) ----------
def google_trends(run: str) -> list[dict]:
    out = []
    for url in sources()["google_trends_rss"]:
        feed = feedparser.parse(_get(url).content)
        for e in feed.entries:
            traffic = int(re.sub(r"\D", "", e.get("ht_approx_traffic", "0")) or 0)
            out.append({"term": e.title, "traffic": traffic, "related_news": e.get("ht_news_item_title", ""),
                        **_velocity("gtrends", e.title, traffic, run)})
    return out


def news(run: str) -> list[dict]:
    """Headlines from the last 24 h; the model clusters them into stories and counts outlets."""
    out, cutoff = [], now() - timedelta(hours=24)
    for feed_cfg in sources()["news_rss"]:
        try:
            feed = feedparser.parse(_get(feed_cfg["url"]).content)
        except requests.RequestException as e:
            log.warning("news feed %s failed: %s", feed_cfg["name"], e)
            continue
        for e in feed.entries[:40]:
            published = e.get("published_parsed")
            if published and date(*published[:3]) < cutoff.date():
                continue
            out.append({"feed": feed_cfg["name"], "title": e.title,
                        "published": e.get("published", ""), "link": e.get("link", "")})
    return out


def x_trends(run: str) -> list[dict]:
    soup = BeautifulSoup(_get(sources()["x_trends_page"]).content, "html.parser")
    first_list = soup.select_one("ol.trend-card__list")
    if not first_list:
        return []
    out = []
    for rank, li in enumerate(first_list.select("li")[:30], start=1):
        name = li.get_text(" ", strip=True)
        # velocity on rank: store inverted so "bigger is better"
        out.append({"trend": name, "rank": rank, **_velocity("x", name, 31 - rank, run)})
    return out


def autocomplete(run: str) -> list[dict]:
    """New autocomplete suggestions for our seeds = earliest search-demand signal."""
    out = []
    for seed in sources()["autocomplete_seeds"]:
        for ds, label in (("yt", "youtube"), ("", "google")):
            url = f"https://suggestqueries.google.com/complete/search?client=firefox&hl=en&gl=ph&ds={ds}&q={quote(seed)}"
            try:
                suggestions = _get(url).json()[1]
            except (requests.RequestException, ValueError, IndexError):
                continue
            for pos, s in enumerate(suggestions):
                v = _velocity(f"ac_{label}", s, 10 - pos, run)
                if v["prev"] is None or v["now"] > v["prev"]:
                    out.append({"seed": seed, "engine": label, "suggestion": s, "position": pos + 1,
                                "is_new": v["prev"] is None})
    return out


def reddit(run: str) -> list[dict]:
    cid, secret = env("REDDIT_CLIENT_ID"), env("REDDIT_CLIENT_SECRET")
    if not cid:
        return []
    token = requests.post("https://www.reddit.com/api/v1/access_token", auth=(cid, secret),
                          data={"grant_type": "client_credentials"}, headers=UA, timeout=20).json()["access_token"]
    headers = {**UA, "Authorization": f"bearer {token}"}
    cfg, out = sources()["reddit"], []
    for sub in cfg["subreddits"]:
        for listing in cfg["listings"]:
            r = requests.get(f"https://oauth.reddit.com/r/{sub}/{listing}?limit=15", headers=headers, timeout=20)
            for child in r.json().get("data", {}).get("children", []):
                p = child["data"]
                out.append({"sub": sub, "listing": listing, "title": p["title"], "score": p["score"],
                            "comments": p["num_comments"], **_velocity("reddit", p["id"], p["score"], run)})
    return out


def youtube_popular(run: str) -> list[dict]:
    key = env("YOUTUBE_API_KEY")
    if not key:
        return []
    cfg, out = sources()["youtube_mostpopular"], []
    for cat in cfg["categories"]:
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=20, params={
            "part": "snippet,statistics", "chart": "mostPopular", "regionCode": cfg["region"],
            "videoCategoryId": cat, "maxResults": 25, "key": key})
        for v in r.json().get("items", []):
            views = int(v["statistics"].get("viewCount", 0))
            out.append({"title": v["snippet"]["title"], "channel": v["snippet"]["channelTitle"],
                        "published": v["snippet"]["publishedAt"], "views": views,
                        **_velocity("yt", v["id"], views, run)})
    return out


def _resolve(year: int, mm: int, rest: str) -> date:
    """'12' -> day 12; '4th-mon' -> 4th Monday; 'last-mon' -> last Monday of the month."""
    if rest.isdigit():
        return date(year, mm, int(rest))
    nth, _ = rest.split("-")                     # weekday is always Monday in our calendar
    first = date(year, mm, 1)
    first_monday = first + timedelta(days=(0 - first.weekday()) % 7)
    if nth == "last":
        d = first_monday
        while (d + timedelta(days=7)).month == mm:
            d += timedelta(days=7)
        return d
    return first_monday + timedelta(weeks=int(nth[0]) - 1)


def calendar_events(days_ahead: int = 21) -> list[dict]:
    today, out = now().date(), []
    for ev in sources()["calendar"]:
        mm, rest = ev["date"].split("-", 1)
        for year in (today.year, today.year + 1):
            d = _resolve(year, int(mm), rest)
            if 0 <= (d - today).days <= days_ahead:
                out.append({"event": ev["name"], "date": d.isoformat(), "days_away": (d - today).days})
    return out


COLLECTORS = {"google_trends": google_trends, "news": news, "x_trends": x_trends,
              "autocomplete": autocomplete, "reddit": reddit, "youtube_popular": youtube_popular}


def collect() -> dict:
    run = db.iso(now())
    signals: dict = {"collected_at": run}
    for name, fn in COLLECTORS.items():
        try:
            signals[name] = fn(run)
        except Exception as e:  # one broken source must not stop the scout
            log.warning("collector %s failed: %s", name, e)
            signals[name] = []
    signals["calendar"] = calendar_events()
    return signals


def run() -> list[dict]:
    signals = collect()
    counts = {k: len(v) for k, v in signals.items() if isinstance(v, list)}
    log.info("signals: %s", counts)
    report = llm.structured(
        "trend_scout",
        "Today is " + now().strftime("%A, %d %B %Y, %H:%M PHT") + ".\n"
        "Rank the 15 best topics for The Filipino Standard from these signals. "
        "`prev` is the value from the previous run (null = first time seen).\n\n"
        + json.dumps(signals, ensure_ascii=False, default=str),
        TrendReport,
    )
    topics = [t.model_dump() for t in sorted(report.topics, key=lambda t: -t.momentum_score)]
    db.add_topics(topics)
    return topics

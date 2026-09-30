"""`tfs audit-carousels`: check that every platform shows a carousel's slides in the right order.

For each carousel, the published images are fetched back from Instagram, Facebook, Threads and Post for Me
(what it was sent, and what TikTok's feed reports) and matched to our slide files by a perceptual hash.
The report gives each platform's order as slide numbers, e.g. 1 2 3 4 = correct.
"""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import requests
from PIL import Image

from . import db, state
from .config import data_dir, item_dir, media

log = logging.getLogger(__name__)


def _hash(img: Image.Image) -> int:
    """Difference hash (9x8 grey): robust to re-encoding and resizing, not to reordering."""
    g = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.getdata())
    bits = [px[r * 9 + c] > px[r * 9 + c + 1] for r in range(8) for c in range(8)]
    return sum(1 << i for i, b in enumerate(bits) if b)


def _fetch(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content))
    except Exception:
        return None


def _match(local: list[int], urls: list[str]) -> list[str]:
    """Slide number (1-based) for each remote image, '?' when nothing is close."""
    out = []
    for url in urls:
        img = _fetch(url)
        if img is None:
            out.append("x")
            continue
        h = _hash(img)
        dist, idx = min((bin(h ^ lh).count("1"), i) for i, lh in enumerate(local))
        out.append(str(idx + 1) if dist <= 12 else "?")
    return out


def _instagram(media_id: str) -> list[str]:
    from .publish import meta
    return [c.get("media_url", "") for c in meta._call("GET", f"{media_id}/children", fields="media_url")
            .get("data", [])]


def _facebook(post_id: str) -> list[str]:
    from .publish import meta
    data = meta._call("GET", post_id, fields="attachments{subattachments.limit(20){media}}")
    att = (data.get("attachments") or {}).get("data") or [{}]
    subs = (att[0].get("subattachments") or {}).get("data", [])
    return [s["media"]["image"]["src"] for s in subs if s.get("media")]


def _threads(media_id: str) -> list[str]:
    from .publish import threads
    return [c.get("media_url", "") for c in threads._call("GET", f"{media_id}/children", fields="media_url")
            .get("data", [])]


def _postforme(post_id: str) -> tuple[list[str], list[str]]:
    """(what Post for Me was sent, what TikTok's feed reports) as image URLs."""
    from .publish import postforme
    sent = [m.get("url", "") for m in postforme._call("GET", f"/social-posts/{post_id}", "tiktok").get("media", [])]
    feed = []
    try:
        account = postforme.account_id("tiktok")
        posts = postforme._call("GET", f"/social-account-feeds/{account}", "tiktok",
                                params={"social_post_id": post_id}).get("data", [])
        for p in posts:
            for m in p.get("media") or []:
                items = m if isinstance(m, list) else [m]
                feed += [i.get("url") or i.get("media_url") or "" for i in items if isinstance(i, dict)]
    except Exception as e:
        log.warning("TikTok feed unavailable: %s", e)
    return sent, feed


def audit(item_ids: list[str]) -> list[str]:
    report = []
    for item_id in item_ids:
        item = db.get_item(item_id)
        if not item or item["kind"] != "carousel":
            continue
        state.pull_item(item_id)
        slides = [media(p) for p in item["data"].get("slides", [])]
        slides = [p for p in slides if p.exists()]
        if not slides:
            report.append(f"{item_id}: slides not found")
            continue
        local = [_hash(Image.open(p)) for p in slides]
        lines = [f"{item_id} ({len(slides)} slides): {item['data'].get('title', '')[:60]}"]
        for post in db.posts_for_item(item_id):
            rid, platform = post.get("remote_id"), post["platform"]
            if not rid or post["status"] not in ("published", "submitted"):
                lines.append(f"  {platform:<19} {post['status']}")
                continue
            try:
                if platform == "instagram_carousel":
                    got = {"published": _match(local, _instagram(rid))}
                elif platform == "facebook_post":
                    got = {"published": _match(local, _facebook(rid))}
                elif platform == "threads_carousel":
                    got = {"published": _match(local, _threads(rid))}
                elif platform == "tiktok_carousel":
                    sent, feed = _postforme(rid)
                    got = {"sent to Post for Me": _match(local, sent)}
                    if feed:
                        got["TikTok feed"] = _match(local, feed)
                else:
                    continue
            except Exception as e:
                lines.append(f"  {platform:<19} could not check: {str(e)[:120]}")
                continue
            for label, order in got.items():
                expected = [str(i + 1) for i in range(len(order))]
                verdict = "OK" if order == expected else "WRONG ORDER"
                lines.append(f"  {platform:<19} {label}: {' '.join(order)}  {verdict}")
        report += lines
    (data_dir() / "carousel_audit.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def recent_carousels(n: int = 6) -> list[str]:
    items = [i for i in db.items_with_status("scheduled") if i["kind"] == "carousel"]
    return [i["id"] for i in sorted(items, key=lambda i: i["anchor_at"])[-n:]]

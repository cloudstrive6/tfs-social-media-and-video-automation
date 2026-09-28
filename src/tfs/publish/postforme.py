"""Post for Me (postforme.dev) — one API for YouTube, Instagram, Facebook and TikTok (videos and photo posts).

With a Quickstart project, posts go out through Post for Me's already-approved platform apps, so
TikTok posts are public without our own TikTok audit, and YouTube uploads don't use our API quota.
Post for Me also hosts the media and holds each post until `scheduled_at`.
"""
from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import requests

from ..config import env, now, require_env

API = "https://api.postforme.dev/v1"

# our platform key -> (Post for Me platform, placement)
PLATFORMS = {
    "youtube": ("youtube", None),
    "youtube_shorts": ("youtube", None),
    "instagram_reel": ("instagram", "reels"),
    "instagram_carousel": ("instagram", "timeline"),
    "facebook_reel": ("facebook", "reels"),
    "facebook_post": ("facebook", "timeline"),
    "tiktok": ("tiktok", None),
    "tiktok_carousel": ("tiktok", None),          # photo post: the slides as a swipeable TikTok photo carousel
}


def _key(platform: str | None) -> str:
    """POSTFORME_API_KEY_<PLATFORM> (e.g. a Quickstart project for TikTok/YouTube) overrides POSTFORME_API_KEY."""
    if platform and env(f"POSTFORME_API_KEY_{platform.upper()}"):
        return env(f"POSTFORME_API_KEY_{platform.upper()}")
    return require_env("POSTFORME_API_KEY")


def _headers(platform: str | None = None) -> dict:
    return {"Authorization": f"Bearer {_key(platform)}", "Content-Type": "application/json"}


def _call(method: str, path: str, platform: str | None = None, **kw) -> dict:
    r = requests.request(method, f"{API}{path}", headers=_headers(platform), timeout=60, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Post for Me {method} {path}: {r.status_code} {r.text[:500]}")
    return r.json()


@lru_cache
def account_id(platform: str) -> str:
    """Connected account for a platform: POSTFORME_ACCOUNT_<PLATFORM> overrides, else the first connected one."""
    override = env(f"POSTFORME_ACCOUNT_{platform.upper()}")
    if override:
        return override
    accounts = _call("GET", "/social-accounts", platform, params={"platform": platform})["data"]
    connected = [a for a in accounts if a.get("status") == "connected"]
    if not connected:
        raise RuntimeError(f"No connected {platform} account in Post for Me — connect it in the dashboard")
    return connected[0]["id"]


def upload(path: Path, platform: str | None = None) -> str:
    """Upload a local file to Post for Me's storage and return its public media URL."""
    urls = _call("POST", "/media/create-upload-url", platform)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as f:
        r = requests.put(urls["upload_url"], data=f, headers={"Content-Type": content_type}, timeout=1800)
    r.raise_for_status()
    return urls["media_url"]


def create_post(platform_key: str, caption: str, media: list[Path], slot: datetime, *,
                title: str = "", description: str = "", tags: list[str] | None = None,
                thumbnail: Path | None = None, external_id: str = "") -> str:
    platform, placement = PLATFORMS[platform_key]
    items = []
    for i, path in enumerate(media):
        item = {"url": upload(path, platform)}
        if i == 0 and thumbnail:
            item["thumbnail_url"] = upload(thumbnail, platform)
        items.append(item)

    config: dict = {}
    if placement:
        config["placement"] = placement
    if platform == "instagram" and placement == "reels":
        config["share_to_feed"] = True
    if platform == "youtube":
        config |= {"title": title[:100], "description": description[:5000], "tags": (tags or [])[:30],
                   "category_id": "27", "default_language": "fil", "localizations": {},
                   "privacy_status": "public", "made_for_kids": False, "contains_synthetic_media": True}
    if platform_key == "tiktok_carousel":
        config |= {"title": title[:90], "privacy_status": "public", "is_ai_generated": True,
                   "allow_comment": True, "auto_add_music": True}
    elif platform == "tiktok":
        config |= {"title": title[:90], "privacy_status": "public", "is_ai_generated": True,
                   "allow_comment": True, "allow_duet": True, "allow_stitch": True}

    body = {
        "caption": caption,
        "social_accounts": [account_id(platform)],
        "media": items,
        "platform_configurations": {platform: config},
        "external_id": external_id,
    }
    if slot > now():
        body["scheduled_at"] = slot.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _call("POST", "/social-posts", platform, json=body)["id"]


def results(post_id: str, platform_key: str) -> list[dict]:
    """Per-account outcome once Post for Me has attempted the post (empty while still scheduled)."""
    return _call("GET", "/social-post-results", PLATFORMS[platform_key][0], params={"post_id": post_id})["data"]


def cancel(post_id: str, platform_key: str) -> None:
    """Delete a scheduled post that hasn't gone out yet."""
    _call("DELETE", f"/social-posts/{post_id}", PLATFORMS[platform_key][0])

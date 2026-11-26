"""YouTube playlists: find or create the channel's playlists (config/playlists.yaml) and add each video to the right ones.

Playlist writes need the `youtube` (or `youtube.force-ssl`) OAuth scope; `granted_scopes()` reports what the stored
refresh token actually carries. Adding is idempotent (a video already in a playlist is skipped) and never raises into
the publish path: `add_for(...)` logs and returns what happened.
Quota: playlists.list / playlistItems.list 1 unit, playlists.insert / playlistItems.insert 50 units (of 10,000/day).
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from pathlib import Path

import requests
import yaml

log = logging.getLogger(__name__)
CONFIG = Path(__file__).resolve().parents[3] / "config" / "playlists.yaml"
WRITE_SCOPES = {"https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.force-ssl"}


@lru_cache
def config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def keys_for(kind: str, pillar: str | None) -> list[str]:
    """Playlist keys for a video of this format ('long_form' or 'vertical') and pillar."""
    rule = config()["rules"].get(kind)
    if rule is None:
        return []
    if isinstance(rule, list):
        return list(rule)
    return list(rule.get(pillar or "", rule.get("default", [])))


def granted_scopes() -> set[str]:
    from .youtube import _creds
    from google.auth.transport.requests import Request

    c = _creds()
    c.refresh(Request())
    info = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": c.token}, timeout=20).json()
    return set(info.get("scope", "").split())


def can_write() -> bool:
    return bool(granted_scopes() & WRITE_SCOPES)


def existing() -> dict[str, str]:
    """title -> playlist id for the channel's own playlists."""
    from .youtube import api

    out, token = {}, None
    while True:
        r = api().playlists().list(part="snippet", mine=True, maxResults=50, pageToken=token).execute()
        out.update({p["snippet"]["title"]: p["id"] for p in r.get("items", [])})
        token = r.get("nextPageToken")
        if not token:
            return out


def ensure(key: str, have: dict[str, str] | None = None) -> str:
    """Playlist id for a config key, creating the playlist (public) if it does not exist yet."""
    from .youtube import api

    spec = config()["playlists"][key]
    have = existing() if have is None else have
    if spec["title"] in have:
        return have[spec["title"]]
    body = {"snippet": {"title": spec["title"], "description": spec.get("description", ""),
                        "defaultLanguage": "en"},
            "status": {"privacyStatus": "public"}}
    pid = api().playlists().insert(part="snippet,status", body=body).execute()["id"]
    have[spec["title"]] = pid
    log.info("created playlist %r (%s)", spec["title"], pid)
    return pid


def _not_found(e: Exception) -> bool:
    return getattr(getattr(e, "resp", None), "status", None) == 404


def contains(playlist_id: str, video_id: str) -> bool:
    from .youtube import api

    try:
        r = api().playlistItems().list(part="id", playlistId=playlist_id, videoId=video_id, maxResults=1).execute()
    except Exception as e:
        if _not_found(e):            # a playlist created seconds ago is not readable yet: it is empty
            return False
        raise
    return bool(r.get("items"))


def _insert_item(playlist_id: str, video_id: str, sleep=time.sleep) -> None:
    """playlistItems.insert, retried while a just-created playlist is still 404 on YouTube's side (2026-11-26)."""
    from .youtube import api

    body = {"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
    for attempt in range(6):
        try:
            api().playlistItems().insert(part="snippet", body=body).execute()
            return
        except Exception as e:      # 404 (new playlist not visible yet), 409 SERVICE_UNAVAILABLE, 5xx: all temporary
            status = getattr(getattr(e, "resp", None), "status", None)
            if status not in (404, 409, 500, 502, 503) or attempt == 5:
                raise
            sleep(5 * (attempt + 1))


def add(video_id: str, keys: list[str], have: dict[str, str] | None = None) -> list[str]:
    """Add a video to each playlist key; returns the playlist titles it was newly added to."""
    have = existing() if have is None else have
    added = []
    for key in keys:
        pid = ensure(key, have)
        if contains(pid, video_id):
            continue
        _insert_item(pid, video_id)
        added.append(config()["playlists"][key]["title"])
    return added


def add_for(video_id: str, kind: str, pillar: str | None) -> list[str]:
    """Publish-path hook: never raises. Returns the playlist titles the video was added to."""
    try:
        keys = keys_for(kind, pillar)
        added = add(video_id, keys) if keys else []
        if added:
            log.info("%s added to playlists: %s", video_id, ", ".join(added))
        return added
    except Exception:
        log.exception("playlist add failed for %s (%s/%s); the upload itself is fine", video_id, kind, pillar)
        return []


def uploads() -> list[dict]:
    """Every video on the channel: id, title, published, privacy, duration seconds."""
    import re

    from .youtube import api

    ch = api().channels().list(part="contentDetails", mine=True).execute()["items"][0]
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while True:
        r = api().playlistItems().list(part="contentDetails", playlistId=up, maxResults=50, pageToken=token).execute()
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        token = r.get("nextPageToken")
        if not token:
            break
    out = []
    for i in range(0, len(ids), 50):
        r = api().videos().list(part="snippet,status,contentDetails", id=",".join(ids[i:i + 50])).execute()
        for v in r.get("items", []):
            m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", v["contentDetails"]["duration"])
            secs = sum(int(x or 0) * k for x, k in zip(m.groups(), (3600, 60, 1))) if m else 0
            out.append({"id": v["id"], "title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"],
                        "privacy": v["status"]["privacyStatus"], "publish_at": v["status"].get("publishAt", ""),
                        "seconds": secs})
    return sorted(out, key=lambda v: v["published"])

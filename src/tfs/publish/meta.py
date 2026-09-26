"""Facebook Page + Instagram professional account via the Graph API."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from ..config import env, require_env


def _graph() -> str:
    return f"https://graph.facebook.com/{env('META_GRAPH_VERSION', 'v23.0')}"


def _call(method: str, path: str, **params) -> dict:
    params["access_token"] = require_env("META_PAGE_ACCESS_TOKEN")
    r = requests.request(method, f"{_graph()}/{path}", data=params if method == "POST" else None,
                         params=params if method == "GET" else None, timeout=120)
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Graph API {path}: {data['error'].get('message')}")
    return data


def _wait_ready(container_id: str, timeout_s: int = 900) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _call("GET", container_id, fields="status_code,status")["status_code"]
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"IG container {container_id} failed: {status}")
        time.sleep(10)
    raise TimeoutError(f"IG container {container_id} not ready after {timeout_s}s")


# ---------- Instagram ----------
def ig_reel(video_url: str, caption: str, cover_url: str = "") -> str:
    ig = require_env("META_IG_USER_ID")
    params = {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true"}
    if cover_url:
        params["cover_url"] = cover_url
    container = _call("POST", f"{ig}/media", **params)["id"]
    _wait_ready(container)
    return _call("POST", f"{ig}/media_publish", creation_id=container)["id"]


def ig_carousel(image_urls: list[str], caption: str) -> str:
    ig = require_env("META_IG_USER_ID")
    children = [_call("POST", f"{ig}/media", image_url=u, is_carousel_item="true")["id"] for u in image_urls[:10]]
    container = _call("POST", f"{ig}/media", media_type="CAROUSEL", children=",".join(children), caption=caption)["id"]
    _wait_ready(container)
    return _call("POST", f"{ig}/media_publish", creation_id=container)["id"]


# ---------- Facebook Page ----------
def fb_reel(video: Path, description: str) -> str:
    page, token = require_env("META_PAGE_ID"), require_env("META_PAGE_ACCESS_TOKEN")
    start = _call("POST", f"{page}/video_reels", upload_phase="start")
    data = video.read_bytes()
    up = requests.post(start["upload_url"], data=data, timeout=600, headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))})
    up.raise_for_status()
    _call("POST", f"{page}/video_reels", upload_phase="finish", video_id=start["video_id"],
          video_state="PUBLISHED", description=description)
    return start["video_id"]


def fb_photos(image_urls: list[str], message: str) -> str:
    page = require_env("META_PAGE_ID")
    ids = [_call("POST", f"{page}/photos", url=u, published="false")["id"] for u in image_urls]
    attached = {f"attached_media[{i}]": json.dumps({"media_fbid": pid}) for i, pid in enumerate(ids)}
    return _call("POST", f"{page}/feed", message=message, **attached)["id"]


# ---------- insights (for the analyst) ----------
def ig_insights(media_id: str) -> dict:
    metrics = "reach,views,likes,comments,shares,saved,total_interactions"
    data = _call("GET", f"{media_id}/insights", metric=metrics).get("data", [])
    return {m["name"]: m["values"][0]["value"] for m in data}

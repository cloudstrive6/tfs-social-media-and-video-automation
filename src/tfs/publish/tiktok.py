"""TikTok Content Posting API (direct post).

Until TikTok approves the app in its audit, every post is forced to SELF_ONLY (private).
Set TIKTOK_PRIVACY=PUBLIC_TO_EVERYONE after approval.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

from ..config import data_dir, env, require_env

API = "https://open.tiktokapis.com/v2"
TOKEN_FILE = "tiktok_token.json"


def _access_token() -> str:
    """Refresh tokens rotate, so the newest one is persisted next to the database."""
    store = data_dir() / TOKEN_FILE
    refresh = json.loads(store.read_text())["refresh_token"] if store.exists() else require_env("TIKTOK_REFRESH_TOKEN")
    r = requests.post(f"{API}/oauth/token/", timeout=30, data={
        "client_key": require_env("TIKTOK_CLIENT_KEY"), "client_secret": require_env("TIKTOK_CLIENT_SECRET"),
        "grant_type": "refresh_token", "refresh_token": refresh})
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"TikTok token refresh failed: {data}")
    store.write_text(json.dumps({"refresh_token": data["refresh_token"]}))
    return data["access_token"]


def post_video(video: Path, caption: str) -> str:
    token = _access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    size = video.stat().st_size
    init = requests.post(f"{API}/post/publish/video/init/", headers=headers, timeout=60, json={
        "post_info": {"title": caption[:2200], "privacy_level": env("TIKTOK_PRIVACY", "SELF_ONLY"),
                      "disable_duet": False, "disable_comment": False, "disable_stitch": False,
                      "is_aigc": True},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1},
    }).json()
    if init.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init failed: {init['error']}")
    up = requests.put(init["data"]["upload_url"], data=video.read_bytes(), timeout=600, headers={
        "Content-Type": "video/mp4", "Content-Range": f"bytes 0-{size - 1}/{size}"})
    up.raise_for_status()
    return init["data"]["publish_id"]

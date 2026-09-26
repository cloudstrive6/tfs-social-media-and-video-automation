"""Telegram notifications: text alerts, plus the actual images/videos of each post. Falls back to the log."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

from .config import env

log = logging.getLogger(__name__)
PHOTO_LIMIT = 10 * 1024 * 1024      # Telegram bot API: photos ≤ 10 MB
VIDEO_LIMIT = 50 * 1024 * 1024      # videos/documents ≤ 50 MB


def _cfg() -> tuple[str, str] | None:
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    return (token, chat) if token and chat else None


def _post(method: str, data: dict, files: dict | None = None) -> None:
    cfg = _cfg()
    if not cfg:
        log.warning("NOTIFY (%s): %s", method, data.get("text") or data.get("caption") or "")
        return
    token, chat = cfg
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data={"chat_id": chat, **data},
                          files=files, timeout=300)
        if not r.ok:
            log.warning("telegram %s failed: %s", method, r.text[:300])
    except requests.RequestException as e:
        log.warning("telegram %s failed: %s", method, type(e).__name__)


def send(text: str) -> None:
    _post("sendMessage", {"text": text[:4000], "disable_web_page_preview": "true"})


def send_photos(paths: list[Path], caption: str) -> None:
    """One photo, or an album of up to 10 (caption on the first)."""
    paths = [p for p in paths if p.exists() and p.stat().st_size <= PHOTO_LIMIT][:10]
    if not paths:
        send(caption)
        return
    if len(paths) == 1:
        with paths[0].open("rb") as f:
            _post("sendPhoto", {"caption": caption[:1024]}, {"photo": f})
        return
    media = [{"type": "photo", "media": f"attach://p{i}", **({"caption": caption[:1024]} if i == 0 else {})}
             for i in range(len(paths))]
    files = {f"p{i}": p.open("rb") for i, p in enumerate(paths)}
    try:
        _post("sendMediaGroup", {"media": json.dumps(media)}, files)
    finally:
        for f in files.values():
            f.close()


def send_video(path: Path, caption: str, fallback_photo: Path | None = None) -> None:
    if path.exists() and path.stat().st_size <= VIDEO_LIMIT:
        with path.open("rb") as f:
            _post("sendVideo", {"caption": caption[:1024], "supports_streaming": "true"}, {"video": f})
    elif fallback_photo:
        send_photos([fallback_photo], caption + "\n(video too large for Telegram; thumbnail shown)")
    else:
        send(caption)

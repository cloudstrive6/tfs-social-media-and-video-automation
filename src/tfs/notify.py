"""Telegram notifications (approvals, failures, daily digest). Falls back to the log."""
from __future__ import annotations

import logging

import requests

from .config import env

log = logging.getLogger(__name__)


def send(text: str) -> None:
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not token or not chat:
        log.warning("NOTIFY: %s", text)
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                      json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True})
    except requests.RequestException as e:
        log.warning("telegram failed (%s): %s", e, text)

"""`tfs telegram-setup`: finds the chat id of whoever messaged the bot, and sends a test message if configured."""
from __future__ import annotations

import requests

from .config import env
from . import notify


def run() -> None:
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set yet")
        return
    me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
    print(f"Bot: @{me.get('result', {}).get('username')}")
    updates = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json().get("result", [])
    chats = {}
    for u in updates:
        chat = (u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}).get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
    if not chats:
        print("No messages yet: open the bot in Telegram, press Start / send 'hi', then run this again.")
    for cid, name in chats.items():
        print(f"CHAT_ID {cid}  ({name})")
    if env("TELEGRAM_CHAT_ID"):
        notify.send("👋 The Filipino Standard pipeline is connected. You'll get every post's images/videos here.")
        print("Test message sent to TELEGRAM_CHAT_ID")

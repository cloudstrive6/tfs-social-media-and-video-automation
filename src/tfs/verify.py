"""Credential smoke test: proves each saved secret works by fetching harmless names. Never prints secrets."""
from __future__ import annotations

import re

import requests

from .config import env


def _scrub(text: str) -> str:
    """Mask anything token-shaped (URLs can carry access_token=...)."""
    text = re.sub(r"(access_token|key|client_secret|refresh_token)=[^&\s'\"]+", r"\1=***", text)
    return re.sub(r"(EAA[A-Za-z0-9]{20,}|1//[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9_.-]+|sk-ant-[A-Za-z0-9_-]+|sk_[A-Za-z0-9]{20,}|GOCSPX-[A-Za-z0-9_-]+)", "***", text)


def _youtube() -> str:
    from .publish import youtube
    items = youtube.api().channels().list(part="snippet", mine=True).execute().get("items", [])
    if not items:
        raise RuntimeError("token works but no channel found for this Google account")
    key = env("YOUTUBE_API_KEY")
    if key:
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", timeout=20, params={
            "part": "id", "chart": "mostPopular", "regionCode": "PH", "maxResults": 1, "key": key})
        r.raise_for_status()
    return f"channel '{items[0]['snippet']['title']}'" + (" + API key OK" if key else "")


def _meta() -> str:
    from .publish import meta
    page = meta._call("GET", env("META_PAGE_ID"), fields="name")
    ig = meta._call("GET", env("META_IG_USER_ID"), fields="username")
    return f"Page '{page['name']}', Instagram @{ig['username']}"


def _elevenlabs() -> str:
    r = requests.get(f"https://api.elevenlabs.io/v1/voices/{env('ELEVENLABS_VOICE_ID')}", timeout=20,
                     headers={"xi-api-key": env("ELEVENLABS_API_KEY")})
    r.raise_for_status()
    return f"voice '{r.json().get('name')}' reachable with the API key"


def _postforme() -> str:
    from .publish import postforme
    accounts = postforme._call("GET", "/social-accounts", "tiktok", params={"platform": "tiktok"})["data"]
    live = [a.get("username") for a in accounts if a.get("status") == "connected"]
    return f"TikTok accounts connected: {live or 'none yet'}"


def _claude() -> str:
    import shutil
    if not shutil.which("claude"):
        return "claude CLI not installed here (it is in the Docker image) — skipped"
    return "Claude Code CLI present; CLAUDE_CODE_OAUTH_TOKEN " + ("set" if env("CLAUDE_CODE_OAUTH_TOKEN") else "MISSING")


CHECKS = [
    ("YouTube", ("YOUTUBE_REFRESH_TOKEN",), _youtube),
    ("Facebook + Instagram", ("META_PAGE_ACCESS_TOKEN", "META_PAGE_ID", "META_IG_USER_ID"), _meta),
    ("ElevenLabs", ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"), _elevenlabs),
    ("Post for Me (TikTok)", ("POSTFORME_API_KEY",), _postforme),
    ("Claude", (), _claude),
]


def run_all() -> bool:
    ok = True
    for name, needed, check in CHECKS:
        missing = [n for n in needed if not env(n)]
        if missing:
            print(f"–  {name}: not configured yet (missing {', '.join(missing)})")
            continue
        try:
            print(f"✅ {name}: {check()}")
        except Exception as e:  # report and keep going; message never includes secret values
            ok = False
            print(f"❌ {name}: {type(e).__name__}: {_scrub(str(e))[:300]}")
    return ok

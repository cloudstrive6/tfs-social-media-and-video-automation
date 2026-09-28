"""Credential smoke test: proves each saved secret works by fetching harmless names. Never prints secrets."""
from __future__ import annotations

import re

import requests

from .config import env


def _scrub(text: str) -> str:
    """Mask anything token-shaped (URLs can carry access_token=...)."""
    text = re.sub(r"(access_token|key|client_secret|refresh_token)=[^&\s'\"]+", r"\1=***", text)
    return re.sub(r"(EAA[A-Za-z0-9]{20,}|1//[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9_.-]+|sk-ant-[A-Za-z0-9_-]+|sk_[A-Za-z0-9]{20,}|GOCSPX-[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]{20,}|bot\d+:[A-Za-z0-9_-]+)", "***", text)


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
    from .config import channel
    model = channel()["tts"]["elevenlabs"]["model_id"]
    resp = requests.get("https://api.elevenlabs.io/v1/models", timeout=20,
                        headers={"xi-api-key": env("ELEVENLABS_API_KEY")})
    models = resp.json()
    if not isinstance(models, list):
        return (f"voice '{r.json().get('name')}' reachable; model list unavailable "
                f"(HTTP {resp.status_code}: {str(models)[:200]})")
    langs = next((m.get("languages", []) for m in models if m.get("model_id") == model), [])
    fil = [f"{x.get('language_id')}={x.get('name')}" for x in langs
           if any(k in (x.get("name") or "").lower() for k in ("filip", "tagal"))]
    return (f"voice '{r.json().get('name')}' reachable; model {model} Filipino language ids: {fil or 'none listed'} "
            f"({len(langs)} languages)")


def _postforme() -> str:
    from .publish import postforme
    accounts = postforme._call("GET", "/social-accounts", "tiktok", params={"platform": "tiktok"})["data"]
    live = [a.get("username") for a in accounts if a.get("status") == "connected"]
    return f"TikTok accounts connected: {live or 'none yet'}"


def _claude() -> str:
    import json
    import shutil
    import subprocess
    if not shutil.which("claude"):
        return "claude CLI not installed on this machine (the run workflow installs it) — skipped"
    out = subprocess.run(["claude", "-p", "Reply with the single word OK.", "--output-format", "json",
                          "--model", "claude-haiku-4-5-20251001"],
                         capture_output=True, text=True, timeout=180)
    result = json.loads(out.stdout or "{}") if out.stdout.strip().startswith("{") else {}
    if out.returncode or result.get("is_error"):
        raise RuntimeError((result.get("result") or out.stderr or out.stdout)[:200])
    return "Claude Code signed in with the Max subscription token and answering"



def _r2() -> str:
    from . import state
    s3, bucket = state._s3(), state._bucket()
    s3.put_object(Bucket=bucket, Key="verify/ping.txt", Body=b"ok")
    body = s3.get_object(Bucket=bucket, Key="verify/ping.txt")["Body"].read()
    s3.delete_object(Bucket=bucket, Key="verify/ping.txt")
    has_state = bool(state._keys(f"{state.PREFIX}{state.DB}"))
    return f"bucket '{bucket}' read/write OK" + ("" if body == b"ok" else " (read mismatch!)") +         (", saved state present" if has_state else ", no state saved yet (first run creates it)")


def _b2() -> str:
    from . import archive
    return archive.ping()


def _telegram() -> str:
    r = requests.get(f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/getMe", timeout=20)
    r.raise_for_status()
    return f"bot @{r.json()['result']['username']}"


CHECKS = [
    ("YouTube", ("YOUTUBE_REFRESH_TOKEN",), _youtube),
    ("Facebook + Instagram", ("META_PAGE_ACCESS_TOKEN", "META_PAGE_ID", "META_IG_USER_ID"), _meta),
    ("ElevenLabs", ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"), _elevenlabs),
    ("Post for Me (TikTok)", ("POSTFORME_API_KEY_TIKTOK",), _postforme),
    ("Cloudflare R2 state", ("S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BACKUP_BUCKET"), _r2),
    ("Backblaze B2 archive", ("B2_ENDPOINT", "B2_BUCKET", "B2_KEY_ID", "B2_APP_KEY"), _b2),
    ("Telegram", ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"), _telegram),
    ("Claude", ("CLAUDE_CODE_OAUTH_TOKEN",), _claude),
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

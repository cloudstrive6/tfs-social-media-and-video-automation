"""Threads (@thefilipinostandard) via Meta's Threads API (graph.threads.net), through the TFS Content Creator app.

Carousels only: each slide becomes an image item (hosted on Meta's CDN the same way Instagram carousels are),
then one CAROUSEL container with the text is published.

Access: THREADS_USER_ID and THREADS_ACCESS_TOKEN (a long-lived token, valid 60 days). The token is refreshed
here about once a week and the fresh one is kept in the private state (data dir -> R2), so it never expires
while the channel is running. The GitHub secret is only the starting token.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from ..config import data_dir, env, now, require_env

API = "https://graph.threads.net/v1.0"
REFRESH_EVERY = timedelta(days=7)
MAX_ITEMS = 20                     # a Threads carousel takes 2–20 images


def _token_file() -> Path:
    return data_dir() / "threads_token.json"


def token() -> str:
    """The newest token: the refreshed one from the state if there is one, else the secret. Refreshes it when
    it is a week old (Threads only refreshes tokens at least 24 hours old)."""
    f = _token_file()
    saved = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    current = saved.get("token") or require_env("THREADS_ACCESS_TOKEN")
    refreshed = datetime.fromisoformat(saved["refreshed"]) if saved.get("refreshed") else None
    if refreshed is None or now() - refreshed > REFRESH_EVERY:
        try:
            r = requests.get("https://graph.threads.net/refresh_access_token", timeout=30,
                             params={"grant_type": "th_refresh_token", "access_token": current})
            data = r.json()
            if "access_token" in data:
                current = data["access_token"]
                f.write_text(json.dumps({"token": current, "refreshed": now().isoformat(timespec="seconds")}),
                             encoding="utf-8")
        except requests.RequestException:
            pass                                   # the current token still works until it expires
    return current


def _call(method: str, path: str, **params) -> dict:
    params["access_token"] = token()
    r = requests.request(method, f"{API}/{path}", timeout=120,
                         data=params if method == "POST" else None, params=params if method == "GET" else None)
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Threads API {path}: {data['error'].get('message')}")
    return data


def _wait_ready(container: str, timeout_s: int = 600) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _call("GET", container, fields="status,error_message")
        if status.get("status") in ("FINISHED", "PUBLISHED"):
            return
        if status.get("status") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Threads container {container} failed: {status.get('error_message')}")
        time.sleep(5)
    raise TimeoutError(f"Threads container {container} not ready after {timeout_s}s")


def carousel(images: list[Path], text: str) -> str:
    """Publish the slides as one Threads carousel. Returns the Threads media id."""
    from .meta import _hosted_image_url

    user = require_env("THREADS_USER_ID")
    items = []
    for path in images[:MAX_ITEMS]:
        item = _call("POST", f"{user}/threads", media_type="IMAGE", is_carousel_item="true",
                     image_url=_hosted_image_url(path))["id"]
        items.append(item)
    for item in items:
        _wait_ready(item)
    if len(items) == 1:                                     # a single slide is a plain image post
        container = _call("POST", f"{user}/threads", media_type="IMAGE", text=text,
                          image_url=_hosted_image_url(images[0]))["id"]
    else:
        container = _call("POST", f"{user}/threads", media_type="CAROUSEL", children=",".join(items),
                          text=text)["id"]
    _wait_ready(container)
    return _call("POST", f"{user}/threads_publish", creation_id=container)["id"]


def permalink(media_id: str) -> str:
    try:
        return _call("GET", media_id, fields="permalink").get("permalink", "")
    except Exception:
        return ""


def check() -> str:
    """For `tfs verify`: the token works and belongs to the configured profile."""
    me = _call("GET", "me", fields="id,username")
    if env("THREADS_USER_ID") and me.get("id") != env("THREADS_USER_ID"):
        raise RuntimeError(f"token is for @{me.get('username')} ({me.get('id')}), not THREADS_USER_ID")
    return f"@{me.get('username')}"

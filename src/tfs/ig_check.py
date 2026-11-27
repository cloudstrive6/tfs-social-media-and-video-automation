"""Read-only Instagram health check (Bryce, 2026-11-27, after four Reels failed at media_publish with Meta's
"Generic Internal Error", code -1, subcode 2207085, while YouTube, Facebook and TikTok posted).

Asks Meta, without posting anything: is the Page token valid and which permissions it holds, is the Instagram
account still the one linked to the Page, how much of the 24-hour publishing quota is used, and which media went up
last. Prints names, counts and public links only, never a token or an id (the repo and its Actions logs are public).
"""
from __future__ import annotations

from .config import env
from .publish import meta


def _try(label: str, fn) -> None:
    try:
        print(f"{label}: {fn()}")
    except Exception as e:  # noqa: BLE001 - every check reports, none stops the others
        print(f"{label}: ERROR {e}")


def _token() -> str:
    t = meta._token()
    d = meta._call("GET", "debug_token", input_token=t).get("data", {})
    exp = d.get("expires_at", 0)
    return (f"valid={d.get('is_valid')}, type={d.get('type')}, app={d.get('application')}, "
            f"expires={'never' if not exp else exp}, data_access_expires={d.get('data_access_expires_at')}, "
            f"scopes={sorted(d.get('scopes', []))}")


def _linked() -> str:
    page = meta._call("GET", env("META_PAGE_ID"), fields="name,instagram_business_account")
    linked = (page.get("instagram_business_account") or {}).get("id", "")
    return f"Page '{page.get('name')}', linked Instagram matches META_IG_USER_ID: {linked == env('META_IG_USER_ID')}"


def _account() -> str:
    a = meta._call("GET", env("META_IG_USER_ID"), fields="username,media_count,followers_count")
    return f"@{a.get('username')}, {a.get('media_count')} posts, {a.get('followers_count')} followers"


def _quota() -> str:
    d = meta._call("GET", f"{env('META_IG_USER_ID')}/content_publishing_limit", fields="config,quota_usage")
    rows = d.get("data", [{}])
    return f"{rows[0].get('quota_usage')} used of {(rows[0].get('config') or {}).get('quota_total')} in 24 h"


def _recent() -> str:
    d = meta._call("GET", f"{env('META_IG_USER_ID')}/media", fields="timestamp,media_product_type,permalink", limit="6")
    return "".join(f"\n  {m.get('timestamp')} {m.get('media_product_type')} {m.get('permalink')}"
                   for m in d.get("data", [])) or "none"


def run() -> None:
    print(f"Graph API version: {env('META_GRAPH_VERSION', 'v23.0')}")
    for label, fn in (("Page token", _token), ("Page link", _linked), ("Instagram account", _account),
                      ("Publishing quota", _quota), ("Latest Instagram media", _recent)):
        _try(label, fn)

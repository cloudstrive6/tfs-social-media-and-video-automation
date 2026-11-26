"""`tfs playlists [--apply]`: put every existing TFS upload into its playlist(s).

Without --apply it only reads and prints: the granted OAuth scopes (names, never tokens), the channel's playlists,
and each upload with the playlists it would join and why. Placement comes from, in order:
  1. config/playlist_backfill.yaml (a reviewed map: video id -> playlist keys, or [] to leave a video out),
  2. the pipeline's own record of that upload (format + pillar of the item it belongs to),
  3. nothing: the video is listed as unplaced and left alone.
Private videos that are not scheduled are left out (they are drafts, holds or locked uploads).
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from . import db

log = logging.getLogger(__name__)
MAP = Path(__file__).resolve().parents[2] / "config" / "playlist_backfill.yaml"


def _manual() -> dict[str, list[str]]:
    if not MAP.exists():
        return {}
    data = yaml.safe_load(MAP.read_text(encoding="utf-8")) or {}
    return {str(k): list(v or []) for k, v in (data.get("videos") or {}).items()}


def _from_pipeline() -> dict[str, tuple[str, str | None]]:
    """video id -> (format, pillar) from the pipeline's YouTube posts."""
    out = {}
    for status in ("published", "submitted", "failed"):
        for post in db.posts_with_status(status):
            if post["platform"] in ("youtube", "youtube_shorts") and post.get("remote_id"):
                item = db.get_item(post["item_id"]) or {}
                out[post["remote_id"]] = ("long_form" if post["platform"] == "youtube" else "vertical",
                                          (item.get("data") or {}).get("pillar"))
    return out


def run(apply: bool = False) -> int:
    from . import state
    from .publish import youtube_playlists as yp

    if state.enabled():
        state.pull()
    scopes = yp.granted_scopes()
    writable = bool(scopes & yp.WRITE_SCOPES)
    print("granted scopes:", ", ".join(sorted(s.rsplit("/", 1)[-1] for s in scopes)))
    print("can create playlists:", "yes" if writable else "NO (the token needs the youtube scope: re-run `tfs auth youtube`)")
    have = yp.existing()
    print("existing playlists:", ", ".join(f"{t} ({i})" for t, i in have.items()) or "none")

    manual, piped = _manual(), _from_pipeline()
    plan = []
    for v in yp.uploads():
        if v["privacy"] == "private" and not v["publish_at"]:
            why, keys = "private draft, left out", []
        elif v["id"] in manual:
            why, keys = "reviewed map", manual[v["id"]]
        elif v["id"] in piped:
            kind, pillar = piped[v["id"]]
            why, keys = f"pipeline: {kind}/{pillar}", yp.keys_for(kind, pillar)
        else:
            why, keys = "UNPLACED (add it to config/playlist_backfill.yaml)", []
        plan.append((v, keys))
        print(f"{v['published'][:10]} {v['privacy']:<8} {v['seconds']:>5}s {v['id']}  {v['title'][:70]}\n"
              f"      -> {', '.join(keys) or '-'}   [{why}]")

    if not apply:
        print("\nread-only: nothing created or added. Run with --apply to write.")
        return 0
    if not writable:
        return 2
    added = 0
    for v, keys in plan:
        if keys:
            done = yp.add(v["id"], keys, have)
            added += len(done)
            for title in done:
                print(f"added {v['id']} to {title}")
    print(f"done: {added} playlist additions; playlists now: {', '.join(have)}")
    return 0

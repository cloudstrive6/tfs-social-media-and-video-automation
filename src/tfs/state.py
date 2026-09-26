"""State between GitHub Actions runs, kept in a PRIVATE Cloudflare R2 bucket (S3 API).

Each run starts on a blank machine: `pull()` restores the SQLite DB, analyst notes, schedule override and the
media of items that are still being produced or waiting to be posted; `push()` uploads whatever changed.
Only one run touches the state at a time (GitHub `concurrency` group), so no locking is needed here.

Bucket layout:  state/<path under TFS_DATA_DIR>   backups/tfs-YYYYMMDD.sqlite3
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import timedelta
from pathlib import Path

from . import db
from .config import data_dir, env, now, require_env

log = logging.getLogger(__name__)
PREFIX = "state/"
DB = "tfs.sqlite3"
SKIP_DIRS = {"work", "style_preview"}           # render scratch; never needed by a later run
KEEP_MEDIA_DAYS = 10                             # after that only an item's text files stay in R2
_lock = threading.Lock()
_seen: dict[str, tuple[int, float]] = {}         # rel path -> (size, mtime) as of the last pull/push


def enabled() -> bool:
    return bool(env("S3_BACKUP_BUCKET"))


def _s3():
    from .publish.storage import _s3 as client
    return client()


def _bucket() -> str:
    return require_env("S3_BACKUP_BUCKET")


def _rel(path: Path) -> str:
    return path.relative_to(data_dir()).as_posix()


def _stamp(path: Path) -> None:
    st = path.stat()
    _seen[_rel(path)] = (st.st_size, st.st_mtime)


def _download(key: str) -> None:
    dest = data_dir() / key[len(PREFIX):]
    dest.parent.mkdir(parents=True, exist_ok=True)
    _s3().download_file(_bucket(), key, str(dest))
    _stamp(dest)


def _keys(prefix: str) -> list[str]:
    keys, pages = [], _s3().get_paginator("list_objects_v2")
    for page in pages.paginate(Bucket=_bucket(), Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", [])]
    return keys


def _active_items() -> set[str]:
    """Items a run may still need the files of: in production, or with posts not yet confirmed."""
    ids = {i["id"] for i in db.items_with_status("planned", "approved", "awaiting_approval")}
    for status in ("queued", "submitted"):
        ids |= {p["item_id"] for p in db.posts_with_status(status)}
    return ids


def pull() -> None:
    if not enabled():
        log.warning("state: S3_BACKUP_BUCKET not set — starting from an empty state")
        return
    keys = _keys(PREFIX)
    if f"{PREFIX}{DB}" in keys:
        _download(f"{PREFIX}{DB}")
    for key in keys:                                # notes, schedule override, tokens
        if "/" not in key[len(PREFIX):] or key.startswith(f"{PREFIX}analyst_notes/"):
            if key != f"{PREFIX}{DB}":
                _download(key)
    active = _active_items()
    for key in keys:
        parts = key[len(PREFIX):].split("/")
        if parts[0] == "items" and len(parts) > 2 and parts[1] in active:
            _download(key)
    log.info("state: pulled %d files (%d active items)", len(_seen), len(active))


def _snapshot() -> Path:
    """Consistent copy of the DB even while the publisher thread writes to it."""
    snap = data_dir() / ".snapshot.sqlite3"
    src, dst = sqlite3.connect(data_dir() / DB), sqlite3.connect(snap)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return snap


def push() -> int:
    """Upload the DB and every new/changed file. Safe to call from several threads."""
    if not enabled() or not (data_dir() / DB).exists():
        return 0
    with _lock:
        s3, bucket, sent = _s3(), _bucket(), 0
        s3.upload_file(str(_snapshot()), bucket, f"{PREFIX}{DB}")
        for path in data_dir().rglob("*"):
            rel = _rel(path)
            if (not path.is_file() or rel == DB or path.name.startswith(".")
                    or SKIP_DIRS & set(rel.split("/")[:-1])):
                continue
            st = path.stat()
            if _seen.get(rel) == (st.st_size, st.st_mtime):
                continue
            s3.upload_file(str(path), bucket, PREFIX + rel)
            _seen[rel] = (st.st_size, st.st_mtime)
            sent += 1
    return sent


def daily_backup() -> None:
    """Dated DB copy once per day (the live copy is overwritten every run)."""
    if not enabled():
        return
    key = f"backups/tfs-{now().strftime('%Y%m%d')}.sqlite3"
    if _keys(key):
        return
    _s3().upload_file(str(_snapshot()), _bucket(), key)
    log.info("state: daily backup %s", key)


def prune() -> None:
    """Keep R2 inside the free 10 GB: drop media of items whose posts all went out > KEEP_MEDIA_DAYS ago."""
    if not enabled():
        return
    cutoff = db.iso(now() - timedelta(days=KEEP_MEDIA_DAYS))
    keep = _active_items()
    doomed = []
    for key in _keys(f"{PREFIX}items/"):
        parts = key[len(PREFIX):].split("/")
        item = db.get_item(parts[1])
        if (item and parts[1] not in keep and item["anchor_at"] < cutoff
                and not key.endswith((".json", ".md"))):
            doomed.append({"Key": key})
    for i in range(0, len(doomed), 1000):
        _s3().delete_objects(Bucket=_bucket(), Delete={"Objects": doomed[i:i + 1000]})
    if doomed:
        log.info("state: pruned %d old media files", len(doomed))

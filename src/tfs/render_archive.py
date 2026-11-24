"""Permanent copy of every final TFS render in the shared studio render archive on Backblaze B2.

Bryce, 2026-11-24: "for all the final/approved renders/versions of the video, be sure to save a copy in B2 Backblaze as
we might be able to use them in the future". The bucket is whatever B2_ARCHIVE_BUCKET names (on 2026-11-24 Bryce was
still choosing one shared studio bucket or one bucket per channel), with the same layout as the PC helper
D:/AI-Video/archive/b2_archive.py:
    tfs/<longform|shorts>/<YYYY-MM>/<item>.mp4               the final video
    tfs/<longform|shorts>/<YYYY-MM>/<item>__thumbnail.jpg    extras (long-form thumbnail)
    tfs/<longform|shorts>/<YYYY-MM>/<item>.mp4.json          sidecar: title, ids, platforms, size, SHA-1, date
The cloud never rewrites the bucket's manifest.jsonl (the PC helper owns it; two writers would drop lines); the
sidecars describe every file. TFS's own working-files bucket (archive.py, tfs-content-archive) is separate.

Needs a key scoped to that bucket only, as repo secrets: B2_ARCHIVE_KEY_ID, B2_ARCHIVE_APP_KEY, B2_ARCHIVE_BUCKET
(and B2_ARCHIVE_ENDPOINT, default B2_ENDPOINT). Without them it does nothing. Never blocks publishing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .config import env

log = logging.getLogger(__name__)
CHANNEL = "tfs"
KIND = {"long_form": "longform", "vertical": "shorts"}


def enabled() -> bool:
    return all(env(k) for k in ("B2_ARCHIVE_KEY_ID", "B2_ARCHIVE_APP_KEY", "B2_ARCHIVE_BUCKET")) and bool(
        env("B2_ARCHIVE_ENDPOINT") or env("B2_ENDPOINT"))


@lru_cache
def _client():
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=env("B2_ARCHIVE_ENDPOINT") or env("B2_ENDPOINT"),
                        aws_access_key_id=env("B2_ARCHIVE_KEY_ID"), aws_secret_access_key=env("B2_ARCHIVE_APP_KEY"),
                        config=Config(request_checksum_calculation="when_required",
                                      response_checksum_validation="when_required"))


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


def _sha1(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def archive_render(item: dict, video: Path, thumbnail: Path | None = None) -> dict | None:
    """Upload one final render with its sidecar. Safe to repeat (a render whose sidecar exists is skipped)."""
    kind = KIND.get(item["kind"])
    if not kind or not enabled() or not video.is_file():
        return None
    s3, bucket = _client(), env("B2_ARCHIVE_BUCKET")
    month = (item.get("anchor_at") or datetime.now(timezone.utc).isoformat())[:7]
    folder = f"{CHANNEL}/{kind}/{month}"
    key = f"{folder}/{_slug(item['id'])}{video.suffix}"
    if _exists(s3, bucket, f"{key}.json"):
        return {"key": key, "skipped": "already archived"}
    s3.upload_file(str(video), bucket, key)
    head = s3.head_object(Bucket=bucket, Key=key)
    if head.get("ContentLength") != video.stat().st_size:
        raise RuntimeError(f"size mismatch after upload of {key}")
    extras = []
    if thumbnail and thumbnail.is_file():
        ek = f"{folder}/{_slug(item['id'])}__{_slug(thumbnail.name)}"
        s3.upload_file(str(thumbnail), bucket, ek)
        extras.append(ek)
    data = item.get("data") or {}
    rec = {"channel": CHANNEL, "kind": kind, "key": key, "bucket": bucket, "sha1": _sha1(video),
           "bytes": video.stat().st_size, "source": f"github-actions:{item['id']}", "extras": extras,
           "archived": datetime.now(timezone.utc).isoformat(timespec="seconds"), "item": item["id"],
           "title": data.get("title") or data.get("working_title") or "", "slot": item.get("anchor_at", ""),
           "platforms": data.get("platforms", {}), "style": "atlas v2"}
    s3.put_object(Bucket=bucket, Key=f"{key}.json", ContentType="application/json",
                  Body=json.dumps(rec, indent=1, ensure_ascii=False).encode("utf-8"))
    log.info("render archived: %s (%d bytes)", key, rec["bytes"])
    return rec


def archive_item(item: dict) -> dict | None:
    """From a scheduled item: never raises, so publishing is never held up; the run's catch-up retries."""
    from .config import media
    data = item.get("data") or {}
    try:
        video = media(data["video"]) if data.get("video") else None
        thumb = media(data["thumbnail"]) if data.get("thumbnail") else None
        return archive_render(item, Path(video), Path(thumb) if thumb else None) if video else None
    except Exception:
        log.exception("render archive failed for %s; retried on the next run", item["id"])
        return None

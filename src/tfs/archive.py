"""Permanent library of everything generated, in a private Backblaze B2 bucket (S3-compatible).

R2 (tfs.state) is working storage and drops media 10 days after posting; B2 keeps every finished piece for
good: video/slides, thumbnail, every AI illustration, narration, script, captions and sources.
Layout:  <YYYY>/<MM>/<item id>/<files>   plus <item id>/item.json (title, pillar, platforms, slots, status).
Archiving never blocks production or posting: failures are logged and retried at the next finish.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from .config import env, item_dir

log = logging.getLogger(__name__)
SKIP_DIRS = {"work"}                               # render scratch
MANIFEST = "_archived.json"                        # synced to R2 with the item, so retries skip what's done


def enabled() -> bool:
    return all(env(k) for k in ("B2_ENDPOINT", "B2_BUCKET", "B2_KEY_ID", "B2_APP_KEY"))


@lru_cache
def _client():
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=env("B2_ENDPOINT"), aws_access_key_id=env("B2_KEY_ID"),
                        aws_secret_access_key=env("B2_APP_KEY"),
                        config=Config(request_checksum_calculation="when_required",
                                      response_checksum_validation="when_required"))


def prefix(item: dict) -> str:
    return f"{item['anchor_at'][:4]}/{item['anchor_at'][5:7]}/{item['id']}"


def archive_item(item: dict) -> int:
    """Upload the item's files not archived yet (tracked in _archived.json). Returns files sent."""
    if not enabled():
        return 0
    d = item_dir(item["id"])
    manifest_path = d / MANIFEST
    done = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    s3, bucket, base, sent = _client(), env("B2_BUCKET"), prefix(item), 0
    try:
        for path in sorted(d.rglob("*")):
            rel = path.relative_to(d).as_posix()
            if not path.is_file() or path.name.startswith(".") or rel == MANIFEST or SKIP_DIRS & set(rel.split("/")[:-1]):
                continue
            stamp = f"{path.stat().st_size}:{int(path.stat().st_mtime)}"
            if done.get(rel) == stamp:
                continue
            s3.upload_file(str(path), bucket, f"{base}/{rel}")
            done[rel] = stamp
            sent += 1
        meta = {k: item.get(k) for k in ("id", "kind", "anchor_at", "status")} | {"data": item.get("data", {})}
        s3.put_object(Bucket=bucket, Key=f"{base}/item.json", ContentType="application/json",
                      Body=json.dumps(meta, ensure_ascii=False, indent=2, default=str).encode())
    except Exception:
        log.exception("archive to B2 failed for %s (will retry next time)", item["id"])
    finally:
        manifest_path.write_text(json.dumps(done))
    if sent:
        log.info("archived %d files for %s to B2", sent, item["id"])
    return sent


def ping() -> str:
    s3, bucket = _client(), env("B2_BUCKET")
    s3.put_object(Bucket=bucket, Key="_verify/ping.txt", Body=b"ok")
    ok = s3.get_object(Bucket=bucket, Key="_verify/ping.txt")["Body"].read() == b"ok"
    s3.delete_object(Bucket=bucket, Key="_verify/ping.txt")
    return f"bucket '{bucket}' read/write {'OK' if ok else 'MISMATCH'}"

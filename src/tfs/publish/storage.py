"""Public media bucket (Cloudflare R2 or any S3-compatible store).

Instagram and Facebook photo endpoints fetch media from a public URL, so rendered files are
pushed here first. Add a lifecycle rule on the bucket to delete objects after 7 days.
"""
from __future__ import annotations

import mimetypes
from functools import lru_cache
from pathlib import Path

import boto3

from ..config import env, now, require_env


@lru_cache
def _s3():
    return boto3.client("s3", endpoint_url=env("S3_ENDPOINT_URL") or None,
                        aws_access_key_id=require_env("S3_ACCESS_KEY_ID"),
                        aws_secret_access_key=require_env("S3_SECRET_ACCESS_KEY"), region_name="auto")


def public_url(path: Path, key_prefix: str) -> str:
    key = f"{key_prefix}/{path.name}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    _s3().upload_file(str(path), require_env("S3_BUCKET"), key, ExtraArgs={"ContentType": content_type})
    return f"{require_env('S3_PUBLIC_BASE_URL').rstrip('/')}/{key}"


def backup(path: Path) -> str:
    """Nightly copy of the SQLite state to a PRIVATE bucket (S3_BACKUP_BUCKET)."""
    key = f"backups/{path.stem}-{now().strftime('%Y%m%d')}{path.suffix}"
    _s3().upload_file(str(path), require_env("S3_BACKUP_BUCKET"), key)
    return key

"""S3-compatible client for Cloudflare R2.

The private state bucket (see tfs.state) uses it. `public_url` is only for a public media bucket, which the
direct Meta publisher does not need (it hosts carousel images as unpublished Page photos).
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

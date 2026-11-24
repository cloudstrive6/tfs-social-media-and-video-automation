"""Narration queue between the cloud pipeline and the local GPU worker.

Bryce, 2026-11-24: TFS narration runs on his RTX 3080 first and on Modal only when the GPU is busy or the PC is off.
The cloud posts a job; tools/voice_worker.py on the PC narrates it between Taas Noo batches and uploads the WAVs;
the cloud scores them like Modal takes. A job not finished by its deadline goes to Modal, so no slot is missed.

R2 layout (bucket S3_BACKUP_BUCKET, deliberately outside the state/ sync and its pruning):
    voice/jobs/<item>.json          {"item", "lines": [{"id", "text"}], "seed", "deadline", "posted"}
    voice/done/<item>/<id:03d>.wav  48 kHz mono 16-bit from the local worker
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PREFIX = "voice/"


def _s3():
    from ..publish.storage import _s3 as client
    return client()


def _bucket() -> str:
    from ..config import require_env
    return require_env("S3_BACKUP_BUCKET")


def enabled() -> bool:
    from .. import state
    return state.enabled()


def job_key(item: str) -> str:
    return f"{PREFIX}jobs/{item}.json"


def done_key(item: str, sid: int) -> str:
    return f"{PREFIX}done/{item}/{int(sid):03d}.wav"


def post(item: str, lines: list[tuple[int, str]], seed: int, deadline: datetime, posted: datetime) -> dict:
    job = {"item": item, "lines": [{"id": int(i), "text": t} for i, t in lines], "seed": int(seed),
           "deadline": deadline.isoformat(), "posted": posted.isoformat()}
    _s3().put_object(Bucket=_bucket(), Key=job_key(item), Body=json.dumps(job, ensure_ascii=False).encode("utf-8"),
                     ContentType="application/json")
    return job


def get_job(item: str) -> dict | None:
    try:
        body = _s3().get_object(Bucket=_bucket(), Key=job_key(item))["Body"].read()
    except Exception:
        return None
    return json.loads(body)


def list_jobs() -> list[dict]:
    s3, jobs = _s3(), []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=_bucket(), Prefix=f"{PREFIX}jobs/"):
        for o in page.get("Contents", []):
            try:
                jobs.append(json.loads(s3.get_object(Bucket=_bucket(), Key=o["Key"])["Body"].read()))
            except Exception:
                continue
    return jobs


def fetch_done(item: str, sids: list[int], dest: Path) -> dict[int, Path]:
    """Download whatever the local worker has finished for these lines."""
    dest.mkdir(parents=True, exist_ok=True)
    s3, got = _s3(), {}
    have = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=_bucket(), Prefix=f"{PREFIX}done/{item}/"):
        have |= {o["Key"] for o in page.get("Contents", [])}
    for sid in sids:
        key = done_key(item, sid)
        if key in have:
            path = dest / f"{int(sid):03d}.wav"
            s3.download_file(_bucket(), key, str(path))
            got[int(sid)] = path
    return got


def put_done(item: str, sid: int, wav: Path) -> None:
    _s3().upload_file(str(wav), _bucket(), done_key(item, sid))


def finish_job(item: str) -> None:
    """The worker narrated every line: drop the job so it is not picked up again."""
    _s3().delete_object(Bucket=_bucket(), Key=job_key(item))


def cleanup(item: str) -> None:
    """The cloud has what it needs: remove the job and the local WAVs from R2."""
    s3, keys = _s3(), [{"Key": job_key(item)}]
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=_bucket(), Prefix=f"{PREFIX}done/{item}/"):
        keys += [{"Key": o["Key"]} for o in page.get("Contents", [])]
    s3.delete_objects(Bucket=_bucket(), Delete={"Objects": keys})

"""Facebook Page + Instagram professional account via Meta's Graph API (app: TFS Content Creator).

Everything is uploaded straight to Meta; no public media bucket is needed:
- Instagram Reels use Instagram's resumable upload (rupload.facebook.com).
- Instagram carousel images are first uploaded to the Facebook Page as unpublished photos, and their
  Meta CDN URLs are handed to Instagram (Instagram only accepts image URLs for carousels).
- Facebook Reels and multi-photo posts upload the files directly.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from ..config import env, require_env


def _graph() -> str:
    return f"https://graph.facebook.com/{env('META_GRAPH_VERSION', 'v23.0')}"


def _token() -> str:
    return require_env("META_PAGE_ACCESS_TOKEN")


def _call(method: str, path: str, files: dict | None = None, **params) -> dict:
    params["access_token"] = _token()
    r = requests.request(method, f"{_graph()}/{path}", data=params if method == "POST" else None,
                         params=params if method == "GET" else None, files=files, timeout=300)
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Graph API {path}: {data['error'].get('message')}")
    return data


TRANSIENT = ("unknown error", "unexpected error", "retry your request", "temporarily unavailable", "please try again")


def _create(path: str, attempts: int = 4, **params) -> dict:
    """Create a media container, retrying Meta's temporary errors. Safe to repeat: an unused container is never
    published and simply expires."""
    for attempt in range(attempts):
        try:
            return _call("POST", path, **params)
        except RuntimeError as e:
            if attempt == attempts - 1 or not any(t in str(e).lower() for t in TRANSIENT):
                raise
            time.sleep(10 * (attempt + 1))
    raise AssertionError("unreachable")


def _wait_ready(container_id: str, timeout_s: int = 900) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _call("GET", container_id, fields="status_code,status")
        if status["status_code"] == "FINISHED":
            return
        if status["status_code"] in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"IG container {container_id} failed: {status.get('status')}")
        time.sleep(10)
    raise TimeoutError(f"IG container {container_id} not ready after {timeout_s}s")


def _publish(ig: str, container: str, attempts: int = 5) -> str:
    """Publish a finished container. Instagram sometimes answers "Media ID is not available" for a few seconds
    after the container reports FINISHED (seen on a carousel): wait and try again rather than fail the post."""
    for attempt in range(attempts):
        try:
            return _call("POST", f"{ig}/media_publish", creation_id=container)["id"]
        except RuntimeError as e:
            if attempt == attempts - 1 or "not available" not in str(e).lower() and "not ready" not in str(e).lower():
                raise
            time.sleep(15 * (attempt + 1))
    raise AssertionError("unreachable")


def _page_photo(path: Path, published: bool = False) -> str:
    with path.open("rb") as f:
        return _call("POST", f"{require_env('META_PAGE_ID')}/photos", files={"source": f},
                     published=str(published).lower())["id"]


def _hosted_image_url(path: Path) -> str:
    """Public Meta CDN URL for an image, via an unpublished Page photo."""
    photo_id = _page_photo(path)
    images = _call("GET", photo_id, fields="images")["images"]
    return max(images, key=lambda i: i["width"])["source"]


# ---------- Instagram ----------
def ig_ready(video: Path) -> Path:
    """Instagram Reels spec (developers.facebook.com, IG User Media): MP4 with no edit lists and the moov atom
    first; H.264 closed GOP, 4:2:0, 23-60 fps, <= 25 Mbps VBR; AAC <= 48 kHz, stereo, 128 kbps."""
    import subprocess

    out = video.with_name(video.stem + ".ig.mp4")
    if out.exists() and out.stat().st_mtime >= video.stat().st_mtime:
        return out
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "20M", "-bufsize", "40M",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", "30", "-g", "60", "-sc_threshold", "0",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", "-use_editlist", "0", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(f"IG re-encode failed: {res.stderr[-500:]}")
    return out


def _signed_url(path: Path, minutes: int = 60) -> tuple[str, str] | None:
    """Put a copy in the private R2 bucket and return (1-hour signed GET URL, key), or None without R2."""
    from .. import state

    if not state.enabled():
        return None
    key = f"tmp/ig/{path.name}"
    s3, bucket = state._s3(), state._bucket()
    s3.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": "video/mp4"})
    url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=minutes * 60)
    return url, key


def ig_reel(video: Path, caption: str) -> str:
    """Instagram fetches the video from a short-lived signed URL (the rupload endpoint refuses Page tokens with
    ProcessingFailedError); falls back to the resumable upload when there is no R2 bucket."""
    video = ig_ready(video)
    ig = require_env("META_IG_USER_ID")
    hosted = _signed_url(video)
    if hosted:
        url, key = hosted
        try:
            container = _call("POST", f"{ig}/media", media_type="REELS", video_url=url, caption=caption,
                              share_to_feed="true")["id"]
            _wait_ready(container)
            return _publish(ig, container)
        finally:
            from .. import state
            try:
                state._s3().delete_object(Bucket=state._bucket(), Key=key)
            except Exception:
                pass
    container = _call("POST", f"{ig}/media", media_type="REELS", upload_type="resumable",
                      caption=caption, share_to_feed="true")["id"]
    data = video.read_bytes()
    up = requests.post(f"https://rupload.facebook.com/ig-api-upload/{env('META_GRAPH_VERSION', 'v23.0')}/{container}",
                       data=data, timeout=1800,
                       headers={"Authorization": f"OAuth {_token()}", "offset": "0", "file_size": str(len(data))})
    if up.status_code >= 400:
        raise RuntimeError(f"IG resumable upload failed: {up.status_code} {up.text[:300]}")
    _wait_ready(container)
    return _publish(ig, container)


def ig_carousel(images: list[Path], caption: str) -> str:
    ig = require_env("META_IG_USER_ID")
    children = [_create(f"{ig}/media", image_url=_hosted_image_url(p), is_carousel_item="true")["id"]
                for p in images[:10]]
    container = _create(f"{ig}/media", media_type="CAROUSEL", children=",".join(children), caption=caption)["id"]
    _wait_ready(container)
    return _publish(ig, container)


# ---------- Facebook Page ----------
def _existing_reel(page: str, description: str, hours: int = 12) -> str | None:
    """A reel with this caption posted in the last few hours (a publish that errored but went through)."""
    from datetime import datetime, timedelta, timezone
    try:
        reels = _call("GET", f"{page}/video_reels", fields="id,description,created_time", limit="15").get("data", [])
    except RuntimeError:
        return None
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    for r in reels:
        created = datetime.strptime(r.get("created_time", "1970-01-01T00:00:00+0000"), "%Y-%m-%dT%H:%M:%S%z")
        if created >= since and (r.get("description") or "").strip()[:150] == description.strip()[:150]:
            return r["id"]
    return None


def fb_reel(video: Path, description: str) -> str:
    page = require_env("META_PAGE_ID")
    existing = _existing_reel(page, description)
    if existing:                                  # already up (an earlier attempt errored after publishing)
        return existing
    start = _call("POST", f"{page}/video_reels", upload_phase="start")
    data = video.read_bytes()
    up = requests.post(start["upload_url"], data=data, timeout=1800, headers={
        "Authorization": f"OAuth {_token()}", "offset": "0", "file_size": str(len(data))})
    up.raise_for_status()
    for attempt in range(3):          # Meta sometimes answers "An unknown error occurred" to the finish step
        try:
            _call("POST", f"{page}/video_reels", upload_phase="finish", video_id=start["video_id"],
                  video_state="PUBLISHED", description=description)
            return start["video_id"]
        except RuntimeError as e:
            if "unknown error" not in str(e).lower() or attempt == 2:
                raise
            time.sleep(30 * (attempt + 1))
            if _existing_reel(page, description):   # it went through after all
                return start["video_id"]
    raise AssertionError("unreachable")


def fb_photos(images: list[Path], message: str) -> str:
    page = require_env("META_PAGE_ID")
    ids = [_page_photo(p) for p in images]
    attached = {f"attached_media[{i}]": json.dumps({"media_fbid": pid}) for i, pid in enumerate(ids)}
    return _call("POST", f"{page}/feed", message=message, **attached)["id"]


# ---------- insights (for the analyst) ----------
def ig_insights(media_id: str) -> dict:
    metrics = "reach,views,likes,comments,shares,saved,total_interactions"
    data = _call("GET", f"{media_id}/insights", metric=metrics).get("data", [])
    return {m["name"]: m["values"][0]["value"] for m in data}

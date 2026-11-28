"""Publish one finished, owner-approved video right away, outside the schedule (the posting workflows stay off).

Used for timely pieces the owner approves one by one (first: the ₱170,598 national-debt Short, 2026-11-25). The video and
its captions are uploaded to the private R2 state bucket under publish/<id>/ (video.mp4, post.json); a request file
publish-requests/<id>.json naming that key is committed, and .github/workflows/publish-file.yml runs
`tfs publish-file --key publish/<id>`. Each platform is tried on its own; one failure never stops the others.

post.json: {"title", "youtube_description", "tags", "facebook", "instagram", "tiktok",
            "platforms": ["youtube_shorts", "facebook_reel", "instagram_reel", "tiktok"]}
Threads is not supported here (the Threads publisher only posts image carousels).
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from . import notify, state
from .config import now

log = logging.getLogger(__name__)
DEFAULT = ["youtube_shorts", "facebook_reel", "instagram_reel", "tiktok"]


def _at(p: dict):
    """post.json "at" (ISO time with offset): Post for Me holds the post until then (owner, 2026-11-27: backlog
    Instagram posts go out one at a time). Missing or past: now."""
    from datetime import datetime
    at = datetime.fromisoformat(p["at"]) if p.get("at") else None
    return at if at and at > now() else now()


def _post(platform: str, video: Path, p: dict) -> tuple[str, str]:
    """Returns (remote id, public link)."""
    from .publish import meta, postforme, youtube
    if platform == "youtube_shorts":
        vid = youtube.upload(video, p["title"], p["youtube_description"], p.get("tags", []), now())
        from .publish import youtube_playlists          # never raises; post.json may carry "pillar"
        youtube_playlists.add_for(vid, "vertical", p.get("pillar"))
        return vid, f"https://youtube.com/shorts/{vid}"
    if platform == "facebook_reel":
        rid = meta.fb_reel(video, p["facebook"])
        return rid, f"https://www.facebook.com/reel/{rid}"
    if platform == "instagram_reel":
        from .config import channel
        if channel()["publishing"].get("overrides", {}).get("instagram_reel") == "postforme":
            rid = postforme.create_post("instagram_reel", p["instagram"], [video], _at(p))
        else:
            rid = meta.ig_reel(video, p["instagram"])
        return rid, "https://www.instagram.com/thefilipinostandard/"
    if platform == "tiktok":
        rid = postforme.create_post("tiktok", p["tiktok"], [video], _at(p), title=p["title"][:90])
        return rid, "https://www.tiktok.com/@thefilipinostandard"
    raise ValueError(f"unsupported platform {platform}")


def run(key: str) -> dict:
    s3, bucket = state._s3(), state._bucket()
    with tempfile.TemporaryDirectory() as td:
        video, meta_file = Path(td) / "video.mp4", Path(td) / "post.json"
        s3.download_file(bucket, f"{key}/video.mp4", str(video))
        s3.download_file(bucket, f"{key}/post.json", str(meta_file))
        p = json.loads(meta_file.read_text(encoding="utf-8"))
        results = {}
        for platform in p.get("platforms") or DEFAULT:
            try:
                rid, link = _post(platform, video, p)
                results[platform] = {"ok": True, "id": rid, "link": link}
                log.info("published %s: %s", platform, link)
            except Exception as e:
                log.exception("publish failed on %s", platform)
                results[platform] = {"ok": False, "error": str(e)[:500]}
    s3.put_object(Bucket=bucket, Key=f"{key}/result.json", ContentType="application/json",
                  Body=json.dumps(results, indent=1).encode("utf-8"))
    lines = [f"{'🟢' if r['ok'] else '❌'} {pl}: {r.get('link') or r.get('error', '')[:160]}" for pl, r in results.items()]
    head = f"🗓 Held by Post for Me until {p['at']}" if _at(p) > now() else "📣 Published now"
    notify.send(f"{head}: {p['title']}\n" + "\n".join(lines))
    print(json.dumps(results, indent=1))
    return results

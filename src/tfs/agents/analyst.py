"""Growth Analyst: pulls performance data, writes standing notes for every agent, retunes the schedule."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

import yaml

from .. import db, llm, notify
from ..config import data_dir, now
from ..models import AnalystReport

log = logging.getLogger(__name__)


def _youtube_stats(video_ids: list[str]) -> dict:
    from ..publish import youtube

    if not video_ids:
        return {}
    end, start = now().date(), (now() - timedelta(days=28)).date()
    stats = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        for metrics in ("views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                        "subscribersGained,likes,comments,shares",
                        "videoThumbnailImpressions,videoThumbnailImpressionsClickRate"):
            try:
                rep = youtube.analytics_api().reports().query(
                    ids="channel==MINE", startDate=str(start), endDate=str(end), metrics=metrics,
                    dimensions="video", filters="video==" + ",".join(batch)).execute()
            except Exception as e:
                log.warning("YouTube Analytics query failed (%s): %s", metrics[:30], e)
                continue
            cols = [h["name"] for h in rep.get("columnHeaders", [])]
            for row in rep.get("rows", []):
                stats.setdefault(row[0], {}).update(dict(zip(cols[1:], row[1:])))
    return stats


def _instagram_stats(media_ids: list[str]) -> dict:
    from ..publish import meta

    out = {}
    for mid in media_ids:
        try:
            out[mid] = meta.ig_insights(mid)
        except Exception as e:
            log.warning("IG insights %s failed: %s", mid, e)
    return out


def run() -> AnalystReport:
    posts = db.posts_for_analysis(28)
    yt_ids = [p["remote_id"] for p in posts if p["platform"].startswith("youtube")]
    ig_ids = [p["remote_id"] for p in posts if p["platform"].startswith("instagram")]
    yt, ig = _youtube_stats(yt_ids), _instagram_stats(ig_ids)

    rows = []
    for p in posts:
        data = json.loads(p["data"])
        rows.append({"item": p["item_id"], "platform": p["platform"], "slot": p["slot_at"], "kind": p["kind"],
                     "title": data.get("title"), "pillar": data.get("pillar"), "remote_id": p["remote_id"],
                     "metrics": yt.get(p["remote_id"]) or ig.get(p["remote_id"]) or {}})
    report = llm.structured(
        "analyst",
        "Performance of everything published in the last 28 days (PHT slots). "
        "For title_swaps use the format 'videoId | new title'.\n\n" + json.dumps(rows, ensure_ascii=False),
        AnalystReport,
    )

    notes_dir = data_dir() / "analyst_notes"
    notes_dir.mkdir(exist_ok=True)
    (notes_dir / "_summary.md").write_text(report.summary_markdown, encoding="utf-8")
    for note in report.agent_notes:
        (notes_dir / f"{note.agent}.md").write_text("\n".join(f"- {n}" for n in note.notes), encoding="utf-8")
    if report.schedule_changes:
        override = data_dir() / "schedule_override.yaml"
        current = yaml.safe_load(override.read_text()) if override.exists() else {}
        for change in report.schedule_changes:
            current[change.platform] = change.slots
        override.write_text(yaml.safe_dump(current))
    for swap in report.title_swaps:
        video_id, _, title = (s.strip() for s in swap.partition("|"))
        if video_id and title:
            from ..publish import youtube
            youtube.update_title(video_id, title)

    notify.send("📊 Weekly analyst report\n\n" + report.summary_markdown[:3500])
    return report

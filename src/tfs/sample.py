"""`tfs sample`: produce one vertical or carousel right now so the look and voice can be reviewed.

Runs on a blank data dir (no R2 state), goes through the real pipeline (scout → editor → research → script →
hook → fact-check → visuals → voice → render), but is never queued for posting. The result goes to Telegram
and to data/sample_out/ (the workflow can attach it, encrypted, for review).
"""
from __future__ import annotations

import logging
import shutil
from datetime import timedelta
from pathlib import Path

from . import db, notify, pipeline
from .agents import editor, trend_scout
from .config import data_dir, env, now
from .slots import FEEDS, Unit

log = logging.getLogger(__name__)


def run(kind: str = "vertical") -> Path:
    topic = (env("TFS_SAMPLE_TOPIC") or "").strip()
    if topic:
        db.add_topics([{"title": topic, "momentum_score": 100, "why_now": "requested sample topic"}])
    else:
        try:
            trend_scout.run()
        except Exception:
            log.exception("trend scout failed; the editor falls back to an evergreen idea")
    unit = Unit(id=f"sample-{kind}-{now():%Y%m%d-%H%M}", kind=kind, index=0,
                platforms={p: now() + timedelta(days=1) for p, _ in FEEDS[kind]})
    if not editor.plan([unit]):
        raise SystemExit("sample: the editor did not assign a topic")
    db.set_status(unit.id, "planned", sample=True)
    pipeline.produce(unit.id)

    item = db.get_item(unit.id)
    if item["status"] != "sample":
        raise SystemExit(f"sample not produced: {item['status']} — {item.get('error') or 'see log / Telegram'}")
    data = item["data"]
    out = data_dir() / "sample_out"
    out.mkdir(exist_ok=True)
    files = [Path(data["video"])] if data.get("video") else [Path(p) for p in data.get("slides", [])]
    for f in files:
        shutil.copy2(f, out / f.name)
    for extra in ("seo.json", "titles.json", "factcheck.json"):   # factcheck.json holds the final script
        src = pipeline.item_dir(unit.id) / extra
        if src.exists():
            shutil.copy2(src, out / extra)
    caption = f"🧪 SAMPLE (not scheduled): {data.get('title') or data.get('working_title')}"
    if files and files[0].suffix == ".mp4":
        notify.send_video(files[0], caption)
    else:
        notify.send_photos(files, caption)
    return out

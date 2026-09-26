"""Editor-in-Chief: assigns fresh topics to upcoming production units."""
from __future__ import annotations

import json

from .. import db, llm
from ..config import channel, data_dir, now
from ..models import Slate
from ..slots import Unit


def plan(units: list[Unit]) -> list[str]:
    topics = db.fresh_topics(hours=12)
    summary = data_dir() / "analyst_notes" / "_summary.md"
    request = {
        "now": now().strftime("%A %d %B %Y %H:%M PHT"),
        "slots_to_fill": [{"slot_id": u.id, "format": u.kind,
                           "first_publish": u.anchor.strftime("%a %H:%M"),
                           "platforms": sorted(u.platforms)} for u in units],
        "topic_pool": topics,
        "pillar_mix_target": channel()["pillars"],
        "published_or_planned_last_30_days": db.recent_titles(30),
        "latest_analyst_summary": summary.read_text(encoding="utf-8") if summary.exists() else "",
    }
    slate = llm.structured(
        "editor_in_chief",
        "Fill every slot in `slots_to_fill` exactly once. Use topic_id 0 for evergreen ideas not in the pool.\n\n"
        + json.dumps(request, ensure_ascii=False, default=str),
        Slate,
    )
    by_id = {u.id: u for u in units}
    planned = []
    for it in slate.items:
        unit = by_id.get(it.slot_id)
        if not unit or db.get_item(unit.id):
            continue
        topic = next((t for t in topics if t["topic_id"] == it.topic_id), None)
        data = {**it.model_dump(), "topic": topic,
                "platforms": {p: db.iso(t) for p, t in unit.platforms.items()}}
        db.upsert_item(unit.id, unit.kind, db.iso(unit.anchor), "planned", data)
        if topic:
            db.mark_topic_used(it.topic_id, unit.id)
        planned.append(unit.id)
    return planned

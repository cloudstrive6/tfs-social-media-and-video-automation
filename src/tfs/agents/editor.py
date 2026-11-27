"""Editor-in-Chief: assigns fresh topics to upcoming production units."""
from __future__ import annotations

from ..config import notes_dir as config_notes_dir

import json

from .. import db, llm
from ..config import ROOT, channel, data_dir, now, schedule
from ..models import Slate
from ..slots import Unit


OWNER_TRIES = 2          # an owner topic whose piece ran out of time gets one more slot, then it is retired


def owner_queue() -> list[dict]:
    """config/owner_topics.yaml in order (the channel owner's own topics, made before the trend pool). Entries
    without an id or a title are ignored, so a typo never stops planning."""
    import logging

    import yaml
    f = ROOT / "config" / "owner_topics.yaml"
    try:
        raw = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("topics") or [] if f.exists() else []
    except (OSError, ValueError, AttributeError, yaml.YAMLError) as e:
        logging.getLogger(__name__).error("owner_topics.yaml unreadable, using the trend pool: %s", e)
        return []
    return [t for t in raw if isinstance(t, dict) and t.get("id") and t.get("title")]


def _owner_taken() -> set[str]:
    """Owner topics that are spoken for: held by a live item, retired by a gate or a person (any skip that is not
    a timeout), or tried OWNER_TRIES times. Only a piece that ran out of time before its slot gives its topic back."""
    with db.conn() as c:
        rows = c.execute("SELECT status, data FROM items").fetchall()
    tries: dict[str, int] = {}
    taken = set()
    for r in rows:
        d = json.loads(r["data"])
        tid = d.get("owner_topic_id")
        if not tid:
            continue
        tries[tid] = tries.get(tid, 0) + 1
        if r["status"] != "skipped" or not d.get("expired"):
            taken.add(tid)
    return taken | {t for t, n in tries.items() if n >= OWNER_TRIES}


def _full_slot(unit: Unit) -> bool:
    """Owner topics go to slots that post to every platform of their kind (not the YouTube-only or IG/TikTok-only
    evening Shorts)."""
    every = set(schedule().get("platforms", {}).get(unit.kind) or [])
    return not every or every <= set(unit.platforms)


def _plan_owner(units: list[Unit]) -> tuple[list[str], list[Unit]]:
    """Gives the earliest open full slots of each kind the next unused owner topics, in queue order."""
    queue = [t for t in owner_queue() if t["id"] not in _owner_taken()]
    planned, rest = [], []
    for unit in sorted(units, key=lambda u: u.anchor):
        t = next((t for t in queue if t.get("kind", "vertical") == unit.kind), None)
        if not t or not _full_slot(unit) or db.get_item(unit.id):
            rest.append(unit)
            continue
        queue.remove(t)
        data = {"slot_id": unit.id, "topic_id": 0, "working_title": t["title"],
                "pillar": t.get("pillar") or "now_explained", "primary_keyword": t.get("keyword") or t["title"],
                "brief": t.get("notes") or t.get("request") or t["title"], "legal_risk": t.get("legal_risk") or "high",
                "owner_request": (t.get("request") or t["title"]).strip()
                + (f"\n\nResearch first: {t['notes'].strip()}" if t.get("notes") else ""),
                "owner_topic_id": t["id"], "topic": None,
                "platforms": {p: db.iso(x) for p, x in unit.platforms.items()}}
        db.upsert_item(unit.id, unit.kind, db.iso(unit.anchor), "planned", data)
        planned.append(unit.id)
    return planned, rest


def plan(units: list[Unit], owner_topics: bool = False) -> list[str]:
    """owner_topics=True only for the scheduled planner: post-now and samples never take an owner topic."""
    owner, units = _plan_owner(units) if owner_topics else ([], units)
    if not units:
        return owner
    topics = db.fresh_topics(hours=12)
    summary = config_notes_dir("analyst_notes") / "_summary.md"
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
    return owner + planned

"""`tfs post-now`: make one piece on a requested topic and publish it right away on every platform of its kind.

Same pipeline and gates as a scheduled piece (research, writing, fact-check, pre-flight, review team). It uses
the production state from R2, so the post is tracked, archived and confirmed like any other. If a gate
rejects it, nothing is posted and Telegram says why.
"""
from __future__ import annotations

import logging

from . import db, pipeline, state
from .agents import editor
from .config import now, schedule
from .slots import Unit

log = logging.getLogger(__name__)


def run(kind: str, topic: str, note: str = "") -> str:
    if not state.enabled():
        raise SystemExit("post-now: no R2 state bucket configured")
    if not topic.strip():
        raise SystemExit("post-now: a topic is required")
    state.pull()
    request = f"Owner request, published immediately. {note}".strip()
    db.add_topics([{"title": topic.strip(), "momentum_score": 100, "why_now": request}])
    at = now()
    unit = Unit(id=f"{at:%Y-%m-%d}-now-{kind}-{at:%H%M}", kind=kind, index=0,
                platforms={p: at for p in schedule()["platforms"][kind]})
    if not editor.plan([unit]):
        raise SystemExit("post-now: the editor did not plan the piece")
    item = db.get_item(unit.id)
    db.set_status(unit.id, item["status"], owner_request=request)
    state.push()
    pipeline.produce(unit.id)
    state.push()
    item = db.get_item(unit.id)
    if item["status"] != "scheduled":
        return f"{unit.id}: not posted ({item['status']}: {item.get('error') or ''})"
    pipeline.publish_due()                    # the slot is now, so every platform is due immediately
    state.push()
    posts = {p["platform"]: f"{p['status']} {p.get('remote_id') or p.get('error') or ''}".strip()
             for p in db.posts_for_item(unit.id)}
    return f"{unit.id}: " + "; ".join(f"{k} {v}" for k, v in sorted(posts.items()))

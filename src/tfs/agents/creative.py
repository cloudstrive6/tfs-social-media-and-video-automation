"""Creative Director: turns the review team's recurring notes into standing instructions for the designers.

Runs twice a day inside the cloud run. Reads the Visual QA / Visual Critic reports of the pieces made since the
last pass and rewrites data/creative_notes/<agent>.md, which load_prompt() appends to that agent's prompt.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from .. import db, llm, notify
from ..config import data_dir, item_dir, now
from ..models import CreativeNotes, ReviewReport

log = logging.getLogger(__name__)
AGENTS = ("motion_designer", "carousel_designer", "thumbnail_artist")
EVERY = timedelta(hours=12)
MIN_PIECES = 2


def notes_dir():
    d = data_dir() / "creative_notes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _last_run() -> datetime | None:
    f = notes_dir() / "_last_run.txt"
    return datetime.fromisoformat(f.read_text().strip()) if f.exists() else None


def due() -> bool:
    last = _last_run()
    return last is None or now() - last >= EVERY


def _reviews(since: datetime | None) -> list[dict]:
    """What the reviewers said about each piece reviewed since the last pass."""
    out = []
    for item in db.items_with_status("scheduled", "sample"):
        d = item_dir(item["id"])
        reports = sorted(d.glob("qa_r*.json")) + sorted(d.glob("qa_polish*.json"))
        if not reports or (since and datetime.fromtimestamp(reports[-1].stat().st_mtime, since.tzinfo) < since):
            continue
        final = ReviewReport.model_validate_json(reports[-1].read_text(encoding="utf-8"))
        critic = []
        for f in sorted(d.glob("critic_r*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            critic += [p for s in data.get("scenes", []) for p in s.get("problems", [])]
        out.append({"piece": item["id"], "kind": item["kind"],
                    "title": item["data"].get("title") or item["data"].get("working_title"),
                    "appeal": final.appeal, "first_frame": final.hook_frame,
                    "review_notes": [w for w in final.warnings if not w.startswith("voice")][:30],
                    "critic_notes_before_render": critic[:20]})
    return out


def run(force: bool = False) -> CreativeNotes | None:
    since = None if force else _last_run()
    pieces = _reviews(since)
    if len(pieces) < (1 if force else MIN_PIECES):
        log.info("creative director: %d reviewed pieces since the last pass; waiting for more", len(pieces))
        return None
    current = {a: (notes_dir() / f"{a}.md").read_text(encoding="utf-8") if (notes_dir() / f"{a}.md").exists() else ""
               for a in AGENTS}
    result = llm.structured(
        "creative_director",
        "# Current standing notes\n" + json.dumps(current, ensure_ascii=False, indent=1)
        + "\n\n# Reviews of the latest pieces\n" + json.dumps(pieces, ensure_ascii=False, indent=1),
        CreativeNotes,
    )
    changed = []
    for note in result.agent_notes:
        if note.agent not in AGENTS:
            continue
        text = "\n".join(f"- {n}" for n in note.notes[:8])
        if text != current.get(note.agent, "").strip():
            (notes_dir() / f"{note.agent}.md").write_text(text, encoding="utf-8")
            changed.append(note.agent)
    (notes_dir() / "_last_run.txt").write_text(now().isoformat(timespec="seconds"))
    appeal = [p["appeal"] for p in pieces if p["appeal"]]
    avg = f"{sum(appeal) / len(appeal):.1f}/10" if appeal else "n/a"
    notify.send(f"🎨 Creative Director ({len(pieces)} pieces, average appeal {avg})\n{result.summary[:900]}"
                + (f"\nUpdated notes for: {', '.join(changed)}" if changed else "\nNo note changes."))
    return result

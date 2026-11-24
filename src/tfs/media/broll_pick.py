"""Find, license-check, grade and log one real photo per planned cutaway (style v2).

Plugs `broll` (Wikimedia Commons, PD / CC0 / CC BY only) into the atlas planner's Resolver. Policy:
- photos only in automated episodes (no fair-use news footage at all; Philippine government video is rejected
  by broll.evaluate);
- skip any candidate whose metadata hints at children (Bryce's no-minors rule), and any file already used in
  this video;
- every photo used gets a licence-log row with where it appears (item_dir/licences.json).
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import broll

log = logging.getLogger(__name__)
MAX_TRIES = 6                    # candidates tried per query before falling back to a type card


class Picker:
    def __init__(self, item_dir: Path, video_id: str, search=broll.search, fetch=broll.fetch, grade=broll.grade):
        self.dir = item_dir
        self.video_id = video_id
        self.log = broll.LicenceLog(item_dir)
        self.assets: dict[str, Path] = {}          # src used in shots -> local graded file
        self.used_titles: set[str] = set()
        self._search, self._fetch, self._grade = search, fetch, grade
        self.n = 0

    def __call__(self, query: str, word: str, t0: float, t1: float) -> dict | None:
        try:
            cands = self._search(query, limit=20)
        except Exception:
            log.exception("commons search failed for %r", query)
            return None
        tried = 0
        for c in cands:
            if tried >= MAX_TRIES:
                break
            if not c.allowed or c.kind != "photo" or c.title in self.used_titles or c.hints:
                continue
            tried += 1
            try:
                raw = self._fetch(c, self.dir / "broll_raw")
                self.n += 1
                rel = f"assets/b{self.n:02d}.jpg"
                out = self.dir / "broll" / f"b{self.n:02d}.jpg"
                out.parent.mkdir(parents=True, exist_ok=True)
                self._grade(raw, out, "photo")
            except Exception:
                log.exception("b-roll %r failed; trying the next candidate", c.title)
                continue
            row = self.log.add(c, file=out, subject=word or query)
            self.log.mark_used(row["id"], self.video_id, t0, t1, word)
            self.log.save()
            self.used_titles.add(c.title)
            self.assets[rel] = out
            return {"kind": "photo", "src": rel, "credit": c.credit_text}
        log.info("no licensed photo for %r; the planner uses a type card", query)
        return None

    def problems(self) -> list[str]:
        return self.log.check()

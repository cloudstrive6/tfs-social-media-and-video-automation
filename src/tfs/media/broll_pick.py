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


GENERIC = {"philippines", "philippine", "filipino", "photo", "image", "file", "view", "daytime", "night", "interior",
           "exterior", "inside", "outside", "front", "aerial", "wide", "shot", "picture", "modern", "public", "city",
           "metro", "national", "official", "government", "general", "the", "and", "with", "from"}


def _fold(t: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(ch))


def mentions(query: str, c) -> bool:
    """True when the candidate's title, description or categories name at least one specific word of the query
    (not "Philippines", "interior" and the like). A cheap first filter; the vision check in the pipeline is the
    second (2026-11-25: a highway was labelled THE HOUSE OF REPRESENTATIVES)."""
    import re
    keys = [w for w in re.findall(r"[a-z0-9]{4,}", _fold(query)) if w not in GENERIC]
    if not keys:
        return True
    text = _fold(" ".join([c.title, getattr(c, "description", "") or "", " ".join(getattr(c, "categories", []) or [])]))
    return any(k in text or (len(k) > 5 and k[:-1] in text) for k in keys)


class Picker:
    def __init__(self, item_dir: Path, video_id: str, search=None, fetch=None, grade=None):
        self.dir = item_dir
        self.video_id = video_id
        self.log = broll.LicenceLog(item_dir)
        self.assets: dict[str, Path] = {}          # src used in shots -> local graded file
        self.used_titles: set[str] = set()
        # looked up at call time, not bound at import, so a test's monkeypatch of broll.search always applies
        self._search = search or (lambda *a, **k: broll.search(*a, **k))
        self._fetch = fetch or (lambda *a, **k: broll.fetch(*a, **k))
        self._grade = grade or (lambda *a, **k: broll.grade(*a, **k))
        self.n = 0

    def __call__(self, query: str, word: str, t0: float, t1: float) -> dict | None:
        try:
            cands = self._search(f"{query} filetype:bitmap", limit=20)   # photos only, no PDF scans
        except Exception:
            log.exception("commons search failed for %r", query)
            return None
        tried = 0
        for c in cands:
            if tried >= MAX_TRIES:
                break
            if not c.allowed or c.kind != "photo" or c.title in self.used_titles or c.hints:
                continue
            if not mentions(query, c):                   # the file's own words must name what we asked for
                log.info("skip %s: title, description and categories never name %r", c.title, query)
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

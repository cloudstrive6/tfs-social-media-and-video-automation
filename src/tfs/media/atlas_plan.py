"""Atlas Designer plan -> timed atlas shots, narration track and caption words (style v2).

Rules carried over from the approved pilot (2026-11-24):
- every cutaway starts on the word it shows (`at_word`), never at a guessed fraction of the line;
- long-forms get a 2.6 s pause with a numbered chapter card on the cutting mat at each new chapter;
- lines are 0.35 s apart; the video starts 0.4 s in and ends 0.4 s after the last line;
- documents keep only highlights that are exact substrings of the quoted text;
- a cutaway with no licensed photo falls back to a text card, never to an unlicensed image.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from ..models import AtlasPlan, AtlasShot

log = logging.getLogger(__name__)
SR = 48000
GAP = 0.35
LEAD = 0.4
CHAPTER_PAD = 2.6
MIN_SHOT = 1.6
SENTENCE_END = (".", "?", "!")


def _norm(w: str) -> str:
    return re.sub(r"[^\w-]", "", w.lower())


def word_time(words: list[tuple[str, float, float]], at_word: str) -> float | None:
    """Start of the first word in `words` matching `at_word` (case and punctuation ignored; a multi-word anchor
    matches its first word; a prefix of 4+ letters counts)."""
    if not at_word.strip():
        return None
    target = _norm(at_word.split()[0])
    for w, s, _ in words:
        if _norm(w) == target:
            return s
    if len(target) >= 4:
        for w, s, _ in words:
            if _norm(w).startswith(target) or target.startswith(_norm(w)) and len(_norm(w)) >= 4:
                return s
    return None


def _chapter_num(name: str) -> str:
    m = re.match(r"\s*chapter\s+(\d+)", name, re.I)
    return m.group(1) if m else ""


def _chapter_title(name: str) -> str:
    return re.sub(r"^\s*chapter\s+\d+\s*[:.]\s*", "", name, flags=re.I).strip() or name


def decode(path: Path) -> np.ndarray:
    """Any audio file to 48 kHz mono float32 (ffmpeg)."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def assemble(clips: list, scenes: list, kind: str, read: Callable[[Path], np.ndarray] = decode):
    """Narration track with the pilot's spacing. Returns (voice, starts, total, chapter_cards) where
    chapter_cards are atlas title shots placed in the long-form chapter pauses."""
    pieces, starts, cards = [], [], []
    t = LEAD
    pieces.append(np.zeros(int(LEAD * SR), np.float32))
    prev_chapter, n = None, 0
    for i, (clip, sc) in enumerate(zip(clips, scenes)):
        chapter = getattr(sc, "chapter", "") or ""
        if kind == "long_form" and i > 0 and chapter and chapter != prev_chapter:
            n += 1
            title = _chapter_title(chapter)
            cards.append({"k": "title", "mat": True, "num": f"{n:02d}",
                          "kicker": "THE FILIPINO STANDARD" if n == 1 else f"CHAPTER {_chapter_num(chapter) or n}",
                          "text": title.upper(), "t0": round(t, 3), "t1": round(t + CHAPTER_PAD, 3)})
            pieces.append(np.zeros(int(CHAPTER_PAD * SR), np.float32))
            t += CHAPTER_PAD
        prev_chapter = chapter or prev_chapter
        y = read(Path(clip.path))
        starts.append(round(t, 3))
        pieces.append(y)
        t += len(y) / SR
        pieces.append(np.zeros(int(GAP * SR), np.float32))
        t += GAP
    voice = np.concatenate(pieces)
    total = round(t - GAP + LEAD, 3)
    voice = np.pad(voice, (0, max(0, int(total * SR) - len(voice))))[: int(total * SR)]
    return voice, starts, total, cards


DASHES = ("\u2014", "\u2013")                 # em and en dashes never appear on screen (house style)


def caption_words(clips: list, starts: list[float]) -> list[dict]:
    out = []
    for clip, st in zip(clips, starts):
        ws = clip.words or []
        for j, (w, s, e) in enumerate(ws):
            dashed = any(dsh in w for dsh in DASHES)
            for dsh in DASHES:
                w = w.replace(dsh, " ")
            w = " ".join(w.split())
            if not w:                                    # a bare dash token: end the caption group there
                if out:
                    out[-1]["brk"] = True
                continue
            out.append({"w": w, "t0": round(st + s, 3), "t1": round(st + e, 3),
                        "brk": dashed or w.endswith(SENTENCE_END) or j == len(ws) - 1})
    return out


Resolver = Callable[[str, str, float, float], dict | None]   # (query, word, t0, t1) -> broll shot fields or None


def _runtime(s: AtlasShot) -> dict:
    """AtlasShot -> the dict atlas.js reads for that kind."""
    d: dict = {"k": s.k}
    if s.k == "map":
        d.update({k: v for k, v in {"view": s.view, "fill": s.fill, "label": s.label}.items() if v})
        d["draw"] = 1.6                                  # the red coastline only shows once traced; a repeat is a no-op
    elif s.k in ("bigtext", "title"):
        # the ink title card read as a dead frame (dry run hook score 2/10): hooks and questions are paper cards over
        # the map; numbered chapter cards on the mat come from assemble(), not from the designer
        d = {"k": "bigtext", "text": s.text, "sub": s.sub or s.kicker, "src": s.src}
    elif s.k == "doc":
        hl = [h for h in s.hl if h and h in s.body]
        d.update({"head": s.head, "sec": s.sec, "body": s.body, "hl": hl, "src": s.src})
    elif s.k == "cards":
        d.update({"items": [{"big": i.big, "small": i.small, "color": i.color} for i in s.items[:3]], "src": s.src})
    elif s.k == "bars":
        d.update({"items": [{"label": i.label, "value": i.value, "frac": max(0.0, min(1.0, i.frac))}
                            for i in s.items[:3]], "src": s.src})
    elif s.k == "seats":
        d.update({"items": [{"label": i.label, "value": max(0, i.count), "of": max(1, i.of), "color": i.color}
                            for i in s.items[:3]], "src": s.src})
    elif s.k == "timeline":
        d.update({"items": [{"date": i.date, "text": i.text} for i in s.items[:4]], "foot": s.foot})
    elif s.k == "compare":
        d.update({"ph": s.ph.model_dump(), "nz": s.nz.model_dump(), "src": s.src})
    elif s.k == "split":
        d.update({"left": s.left, "right": s.right, "text": s.text, "src": s.src})
    return {k: v for k, v in d.items() if v not in ("", None, [])} | {"k": d["k"]}


def to_shots(plan: AtlasPlan, scenes: list, clips: list, starts: list[float], total: float, kind: str,
             resolve: Resolver, hero: dict | None = None) -> list[dict]:
    """Absolute-time atlas shots. `resolve` finds a licensed photo for a broll query; `hero` is the broll dict of
    the rendered 3D shot (long-form) or None."""
    by_id = {s.scene_id: s for s in plan.scenes}
    out: list[dict] = []
    if starts:                                           # the paper map is traced under the opening shot, always, and is
        out.append({"k": "map", "view": "ph", "fill": "ph", "draw": 0.001, "instant": True, "t0": 0.0, "t1": 0.0})  # there at 0.0 s
    hero_used = False
    for i, (sc, clip, st) in enumerate(zip(scenes, clips, starts)):
        nxt = starts[i + 1] if i + 1 < len(starts) else total - LEAD + GAP
        end = min(nxt, st + float(clip.duration) + GAP)    # chapter pauses belong to the chapter card
        planned = by_id.get(sc.id)
        shots = list(planned.shots) if planned and planned.shots else [AtlasShot(k="map", view="ph")]
        timed = []
        for j, s in enumerate(shots):
            wt = None if j == 0 else word_time(clip.words or [], s.at_word)
            if j > 0 and wt is None:
                log.info("scene %s: anchor %r not found; shot dropped", sc.id, s.at_word)
                continue
            timed.append((st + (wt or 0.0), s))
        timed.sort(key=lambda x: x[0])
        timed[0] = (st, timed[0][1])
        kept = [timed[0]]                                # too short to read: drop it and let the previous shot hold
        for j, (t0, s) in enumerate(timed[1:], 1):
            nxt = timed[j + 1][0] if j + 1 < len(timed) else end
            if nxt - t0 >= MIN_SHOT and t0 - kept[-1][0] >= MIN_SHOT:
                kept.append((t0, s))
        for j, (t0, s) in enumerate(kept):
            t1 = kept[j + 1][0] if j + 1 < len(kept) else end
            if s.k == "broll":
                if s.hero and hero and kind == "long_form" and not hero_used:
                    d = dict(hero, word=s.word or hero.get("word", ""))
                    hero_used = True
                else:
                    d = resolve(s.broll_query, s.word, t0, t1) if s.broll_query else None
                    if d is None:                        # no licensed photo: say it in type instead
                        d = {"k": "bigtext", "text": (s.word or s.broll_query).upper()}
                        if not d["text"]:
                            continue
                    else:
                        d = {"k": "broll", "word": s.word, **d}
            else:
                d = _runtime(s)
            d.update(t0=round(t0, 3), t1=round(t1, 3))
            if i == 0 and j == 0:                        # the first frame is the thumbnail in the feed: the opening
                d.update(t0=0.0, instant=True)           # shot is fully on screen from 0.0 s, no fade
            if out and out[-1]["t1"] > d["t0"]:
                out[-1]["t1"] = d["t0"]
            out.append(d)
    return out

"""Atlas Designer plan -> timed atlas shots, narration track and caption words (style v2).

Rules carried over from the approved pilot (2026-11-24):
- every cutaway starts on the word it shows (`at_word`), never at a guessed fraction of the line;
- long-forms get a 2.6 s pause with a numbered chapter card on the cutting mat at each new chapter;
- lines are 0.35 s apart; the video starts 0.4 s in and ends 0.4 s after the last line;
- documents keep only highlights that are exact substrings of the quoted text;
- a cutaway with no licensed photo falls back to a text card, never to an unlicensed image.

Atlas blocks v3 (2026-11-25): globe, checklist, linechart, barchart, waffle, balance, dates and media shots, a
`stamp` on any shot, and caption key words. Every build step inside a shot (checklist row, bar, date card, list
row, chip, stamp, callout, the spoken key number) lands on its own spoken word; steps without a word get an even
spread, computed here so the picture (atlas.js) and the sound (sfx_v2) use the same times. `variety_problems`
fails a plan where one scene family runs longer than MAX_FAMILY_RUN seconds.
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


def word_after(words: list[tuple[str, float, float]], at_word: str, after: float, before: float) -> float | None:
    """Like word_time, but only words starting in [after, before): build steps inside a shot use the first
    matching word spoken while that shot is on screen."""
    inside = [(w, s, e) for w, s, e in words if after - 1e-6 <= s < before]
    return word_time(inside, at_word)


def step_times(ats: list, t0: float, t1: float, lead: float = 0.5, min_gap: float = 0.9) -> list[float]:
    """Start times of n build steps: the anchored time when it falls inside the shot, else an even spread after
    `lead` (same rule as TFSLIB.stepTimes in engine/runtime/atlas_lib.js)."""
    n = len(ats)
    gap = max(min_gap, (t1 - t0 - lead - 1.0) / max(1, n))
    return [round(a, 3) if a is not None and t0 <= a < t1 else round(t0 + lead + i * gap, 3) for i, a in enumerate(ats)]


# lead and gap of the even spread per kind (matches atlas_blocks.js)
STEPS = {"checklist": (0.45, 0.8), "barchart": (0.45, 0.7), "dates": (0.2, 1.8), "rows": (0.7, 1.25),
         "chips": (1.0, 0.8)}


def globe_timing(t0: float, t1: float) -> tuple[float, float]:
    """(rotation start, rotation length) of a globe shot, as atlas_blocks.js animates it."""
    return t0 + 0.15, min(2.4, max(1.2, (t1 - t0) * 0.35))


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


def _media(s: AtlasShot, resolve: Resolver, t0: float, t1: float) -> dict:
    """Media card: a licensed photo in a bordered card (slow push), lower third, credit, side-list rows and honesty
    chips. With no licensed photo it shows a drawn icon instead, never an unlicensed or misleading image."""
    d: dict = {"k": "media"}
    got = resolve(s.broll_query, s.word or s.name, t0, t1) if s.broll_query else None
    if got:
        d.update({kk: v for kk, v in got.items() if kk in ("kind", "src", "credit")})
    else:
        d["icon"] = s.icon or "building"
    d.update({kk: v for kk, v in {"name": s.name, "role": s.role}.items() if v})
    rows = [{"text": r.text, "color": r.color} for r in s.rows[:4] if r.text]
    chips = [{"text": c.text.upper()} for c in s.chips[:2] if c.text]
    if rows:
        d["rows"] = rows
    if chips:
        d["chips"] = chips
    return d


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
    elif s.k == "checklist":
        d.update({"head": s.head, "src": s.src, "items": [{"text": i.text, "mark": i.mark or "tick", "label": i.label}
                                                         for i in s.items[:5] if i.text]})
    elif s.k == "linechart":
        d.update({"head": s.head, "big": s.big, "callout": s.callout, "src": s.src,
                  "items": [{"label": i.label, "num": float(i.num)} for i in s.items[:12]]})
    elif s.k == "barchart":
        d.update({"head": s.head, "callout": s.callout, "src": s.src,
                  "items": [{"label": i.label, "value": i.value, "num": float(i.num), "color": i.color}
                            for i in s.items[:4]]})
    elif s.k == "waffle":
        d.update({"head": s.head, "big": s.big, "small": s.small, "frac": max(0.0, min(1.0, s.frac)), "src": s.src})
    elif s.k == "balance":
        d.update({"head": s.head, "label": s.label, "big": s.big, "small": s.small,
                  "frac": max(0.0, min(1.0, s.frac)), "src": s.src,
                  "chips": [{"text": c.text.upper()} for c in s.chips[:2] if c.text]})
    elif s.k == "dates":
        d.update({"head": s.head, "src": s.src, "items": [{"big": i.big, "label": i.label, "small": i.small,
                                                          "color": i.color} for i in s.items[:3]]})
    elif s.k == "globe":
        d.update({"label": s.label, "src": s.src})
        if s.zoom:
            d["zoom"] = max(1.0, min(6.0, s.zoom))
    return {k: v for k, v in d.items() if v not in ("", None, [])} | {"k": d["k"]}


def clean_src(src: str) -> str:
    """Source badge text without the dossier's internal [S12] codes (blind review: viewers saw "[S6]")."""
    s = re.sub(r"\s*\[S\d+\]", "", src)
    s = re.sub(r"\(\s*\)", "", s)
    s = " ".join(s.split()).strip(" ;,")
    while True:                                    # "Own arithmetic from [S1] and [S18]" -> "Own arithmetic"
        t = re.sub(r"\s+(and|from|of|;|,)$", "", s).strip(" ;,")
        if t == s:
            break
        s = t
    return s or src


def _globe(s: AtlasShot, d: dict) -> None:
    """Resolve the globe's focus, countries, cities and routes to lon/lat (Natural Earth; unknown names dropped)."""
    from . import atlas
    f = atlas.locate(s.focus) if s.focus else None
    if f is None:
        f = atlas.locate((s.highlight or ["Philippines"])[0]) or atlas.locate("Philippines")
    d["focus"] = {"lon": f["lon"], "lat": f["lat"]}
    hl = []
    for name in s.highlight[:4]:
        c = atlas.country(name)
        if c and all(h["iso"] != c["iso"] for h in hl):
            hl.append({"iso": c["iso"], "name": c["name"]})
    d["highlight"] = hl
    d["places"] = [{"name": p["name"], "lon": p["lon"], "lat": p["lat"]}
                   for p in (atlas.locate(x) for x in s.places[:5]) if p]
    arcs = []
    for a in s.arcs[:3]:
        ends = [atlas.locate(x.strip()) for x in re.split(r">|->|\bto\b", a) if x.strip()]
        if len(ends) == 2 and all(ends):
            arcs.append({"from": [ends[0]["lon"], ends[0]["lat"]], "to": [ends[1]["lon"], ends[1]["lat"]],
                         "names": [ends[0]["name"], ends[1]["name"]]})
    d["arcs"] = arcs


def _anchor(d: dict, s: AtlasShot, words: list, st: float, t0: float, t1: float) -> None:
    """Absolute times for every build step of a shot: anchored on its word while the shot is up, else spread.
    Also lists the times of spoken key numbers (`keyAt`) so the captions box them on the same word."""
    rel0, rel1 = t0 - st, t1 - st

    def at(word: str):
        w = word_after(words, word, rel0, rel1) if word else None
        return None if w is None else round(st + w, 3)

    keys = []
    if s.stamp:
        a = at(s.stamp_word)
        d["stamp"] = {"text": s.stamp.upper()[:28], "color": s.stamp_color or "red",
                      "at": a if a is not None else round(t0 + 0.5, 3)}
    for name, word in (("bigAt", s.big_word), ("calloutAt", s.callout_word)):
        a = at(word)
        if a is not None:
            d[name] = a
            keys.append(a)
    k = d["k"]
    if k in ("checklist", "barchart", "dates"):
        items = s.items[:len(d.get("items", []))]
        ats = [at(i.at_word) for i in items]
        lead, gap = STEPS[k]
        for it, a in zip(d.get("items", []), step_times(ats, t0, t1, lead, gap)):
            it["at"] = a
        if k == "barchart":
            keys += [a for a in ats if a is not None]
    if k in ("media", "balance"):
        for field in ("rows", "chips"):
            src = [x for x in getattr(s, field) if x.text][:len(d.get(field, []))]
            if not src:
                continue
            lead, gap = STEPS[field]
            if k == "balance":                            # balance chips follow the count-up
                lead, gap = (d.get("bigAt", t0 + 0.9) - t0) + 1.6, 0.6
            for it, a in zip(d[field], step_times([at(i.at_word) for i in src], t0, t1, lead, gap)):
                it["at"] = a
    if k == "globe":
        rot_at, rot_dur = globe_timing(t0, t1)
        for i, h in enumerate(d.get("highlight", [])):
            a = at(h["name"])
            h["at"] = a if a is not None and a >= rot_at + 0.5 else round(rot_at + rot_dur + 0.2 + i * 0.8, 3)
        ats = [at(p["name"]) for p in d.get("places", [])]
        for p, a in zip(d.get("places", []), step_times(ats, t0, t1, rot_dur + 0.6, 0.6)):
            p["at"] = a
        for i, a in enumerate(d.get("arcs", [])):
            a["at"] = round(rot_at + rot_dur + 0.6 + i * 1.4, 3)
    if keys:
        d["keyAt"] = sorted(set(keys))


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
            elif s.k == "media":
                d = _media(s, resolve, t0, t1)
            else:
                d = _runtime(s)
                if s.k == "globe":
                    _globe(s, d)
            d.update(t0=round(t0, 3), t1=round(t1, 3))
            if d.get("src"):
                d["src"] = clean_src(d["src"])
            _anchor(d, s, clip.words or [], st, t0, t1)
            if i == 0 and j == 0:                        # the first frame is the thumbnail in the feed: the opening
                d.update(t0=0.0, instant=True)           # shot is fully on screen from 0.0 s, no fade
            if out and out[-1]["t1"] > d["t0"]:
                out[-1]["t1"] = d["t0"]
            out.append(d)
    return out


# ---------------------------------------------------------------- caption key words
def mark_keys(words: list[dict], plan: AtlasPlan, scenes: list, starts: list[float], total: float,
              shots: list[dict]) -> list[dict]:
    """Box one key word per caption sentence: the spoken key number of a chart first (`keyAt` on the shots, the
    same word the chart labels), else the designer's `key_words` for that scene. Returns the words, some with
    `key: True`. A plan without key words and without anchored numbers leaves the captions as they were."""
    want: set[int] = set()
    times = sorted(t for s in shots for t in s.get("keyAt", []))
    for t in times:
        j = min(range(len(words)), key=lambda i: abs(words[i]["t0"] - t), default=None)
        if j is not None and abs(words[j]["t0"] - t) < 0.06:
            want.add(j)
    by_id = {sc.scene_id: sc for sc in plan.scenes}
    bounds = list(starts) + [total + 1]
    for i, sc in enumerate(scenes):
        planned = by_id.get(sc.id)
        for kw in (planned.key_words if planned else [])[:3]:
            target = _norm(kw.split()[0]) if kw.strip() else ""
            if not target:
                continue
            for j, w in enumerate(words):
                if bounds[i] - 0.01 <= w["t0"] < bounds[i + 1] - 0.01 and _norm(w["w"]) == target:
                    want.add(j)
                    break
    out, used = [], False
    numbers_first = {j for j in want if any(abs(words[j]["t0"] - t) < 0.06 for t in times)}
    group: list[int] = []

    def flush():
        nonlocal group
        picks = [j for j in group if j in numbers_first] or [j for j in group if j in want]
        for j in group:
            out.append(dict(words[j], key=True) if picks and j == picks[0] else words[j])
        group = []

    for j, w in enumerate(words):
        group.append(j)
        if w.get("brk"):
            flush()
    flush()
    del used
    return out


# ---------------------------------------------------------------- variety (scene families)
FAMILY = {"map": "map", "globe": "map",
          "cards": "chart", "bars": "chart", "seats": "chart", "compare": "chart", "timeline": "chart",
          "linechart": "chart", "barchart": "chart", "waffle": "chart", "balance": "chart", "dates": "chart",
          "broll": "media", "media": "media",
          "doc": "proof", "checklist": "proof",
          "bigtext": "title", "title": "title", "split": "title"}
MAX_FAMILY_RUN = 15.0       # seconds one family may hold the screen before another family (or the map) takes over


def family_runs(shots: list[dict]) -> list[tuple[str, float, float]]:
    """Consecutive stretches of one scene family: [(family, t0, t1)]. Zero-length shots (the instant opener map)
    do not count; a media card with no photo is an icon analogy."""
    runs: list[list] = []
    for s in sorted(shots, key=lambda x: x["t0"]):
        if s["t1"] - s["t0"] <= 0.01:
            continue
        fam = "icon" if s["k"] == "media" and s.get("icon") and not s.get("src") else FAMILY.get(s["k"], s["k"])
        if runs and runs[-1][0] == fam and abs(runs[-1][2] - s["t0"]) < 0.05:
            runs[-1][2] = s["t1"]
        else:
            runs.append([fam, s["t0"], s["t1"]])
    return [(f, round(a, 3), round(b, 3)) for f, a, b in runs]


def builds(shot: dict) -> int:
    """Word-anchored build steps a shot adds after it lands (rows, bars, cards, chips, stamp, callout, number)."""
    n = sum(1 for f in ("items", "rows", "chips", "places", "highlight", "arcs") for x in shot.get(f, []) if x.get("at"))
    return n + bool(shot.get("stamp")) + bool(shot.get("calloutAt")) + bool(shot.get("bigAt"))


def variety_problems(shots: list[dict], max_run: float = MAX_FAMILY_RUN) -> list[str]:
    """QC for the variety rule: one family may not hold the screen for more than `max_run` seconds in a row."""
    return [f"{fam} runs {b - a:.1f} s in a row ({a:.1f} to {b:.1f} s); max {max_run:.0f} s, then change family "
            f"or return to the map" for fam, a, b in family_runs(shots) if b - a > max_run + 0.05]


# ---------------------------------------------------------------- chart consistency
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9, "bn": 1e9,
          "t": 1e12, "trillion": 1e12}


def figure(text: str) -> float | None:
    """The number a printed figure means, units applied: "₱1.37T" -> 1.37e12, "₱876.2B" -> 8.762e11, "28%" -> 28,
    "170,598" -> 170598. None when there is no number."""
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([a-zA-Z]+)?", str(text or ""))
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    return v * _SCALE.get(unit, 1.0)


def _close(a: float, b: float, tol: float = 0.03) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-12)


def chart_problems(shots: list[dict]) -> list[str]:
    """Charts whose plotted numbers disagree with their own printed figures: a line chart whose last point is not its
    headline (in any unit scale), a waffle whose fill is not its printed percentage, a bar chart whose bar heights are
    not in the ratio of their printed values."""
    out = []
    for s in shots:
        k, at = s.get("k"), f"{s.get('t0', 0):.1f} s"
        if k == "linechart" and s.get("big") and s.get("items"):
            big, last = figure(s["big"]), s["items"][-1].get("num")
            if big and last and not any(_close(last * f, big) for f in (1, 1e3, 1e6, 1e9, 1e12, 1e-3)):
                out.append(f"linechart at {at}: headline {s['big']!r} does not match its last point {last}")
        if k == "waffle" and s.get("big") and "%" in s["big"]:
            pct = figure(s["big"])
            if pct is not None and abs(pct - 100 * float(s.get("frac") or 0)) > 1.5:
                out.append(f"waffle at {at}: label {s['big']!r} but {100 * float(s.get('frac') or 0):.1f}% of squares fill")
        if k == "barchart":
            pairs = [(figure(i.get("value")), i.get("num")) for i in s.get("items", [])]
            pairs = [(v, n) for v, n in pairs if v and n]
            for (v0, n0), (v1, n1) in zip(pairs, pairs[1:]):
                if not _close(v1 / v0, n1 / n0, 0.05):
                    out.append(f"barchart at {at}: bar heights {n0}:{n1} do not match printed values {v0:g}:{v1:g}")
                    break
    return out

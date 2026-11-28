"""TFS music bed from the music team's documentary library (owner, 2026-11-27).

The owner picked, blind on a phone, Netflix-style documentary strings: real sampled strings playing a minimalist
driving ostinato ("Style C"), 25 dB under the narrator in the phone band (300 to 3400 Hz), held through pauses, no
level jump at the reveal. The library (music team, the studio notes `skills/global/music-team`, library v1) is 12 beds in
six moods with section markers: intro, drive (its second half loops at bar lines), build, space (for a reveal),
return, ending. This module:

- picks a cue from the item's title and topic words (investigation by default, the sound he picked);
- assembles it to the exact length at bar lines, with the space section starting on the first reveal;
- for long-form, switches cue at each chapter card (crossfade under the card) so a long video never loops one drive;
- sets the bed level: the median voice-over-music gap while the narrator speaks is 25 dB in the phone band, the bed
  holds through pauses under 2.2 s and lifts gently (+6 dB, 1.2 s ramp) only in music-only stretches.

Library files: R2 private bucket under `music/doc-v1/` (index.json, <cue>.json, <cue>.flac, mono 48 kHz), cached in
`data_dir()/music/doc-v1/`; `TFS_MUSIC_DIR` points at a local copy instead (tests, dry runs). If the library is
missing, `bed()` returns None and the mixer falls back to the v2 pad.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path

import numpy as np
from scipy.signal import butter, lfilter, sosfilt

log = logging.getLogger(__name__)
SR = 48000
PREFIX = "music/doc-v1/"
PHONE_GAP_DB = 25.0      # The owner, 2026-11-27 (test 3, level C3)
HOLD_S = 2.2             # pauses shorter than this keep the bed down
LIFT_DB = 6.0            # music-only stretches (before the first word, after the last, long pauses)
ATTACK_S, RELEASE_S, PRE_S = 0.5, 1.2, 0.35   # duck back down before the voice returns, over 0.5 s
XFADE_S = 0.03           # joins at bar lines
CHAPTER_XFADE_S = 1.2    # cue change under a chapter card

MOODS = [  # (mood, words in the title or topic), first match wins; Tagalog and English
    ("urgent", r"deadline|huling araw|hanggang ngayong|bukas na|countdown|agad|emergency|babala|warning"),
    ("dark", r"korap|corrupt|nakaw|kaso|scam|pandaraya|fraud|krimen|crime|patay|pinatay|abuso|abuse"),
    ("somber", r"trahedya|tragedy|nasawi|biktima|victim|bagyo|typhoon|lindol|earthquake|gutom|hunger|kahirapan|poverty"),
    ("hopeful", r"pag-asa|hope|tagumpay|success|bagong simula|panalo|win|solusyon|solution"),
    ("curiosity", r"alam mo ba|did you know|how to|tips|gabay|guide"),   # not "paano" or "bakit": most hooks ask
]
DEFAULT_MOOD = "investigation"


# ---- library ---------------------------------------------------------------------------------------------------
def _dir() -> Path:
    local = os.environ.get("TFS_MUSIC_DIR")
    if local:
        return Path(local)
    from ..config import data_dir
    return data_dir() / "music" / "doc-v1"


def _fetch(name: str) -> Path | None:
    """Local file, downloading it from the private R2 bucket on first use. None when unavailable."""
    p = _dir() / name
    if p.exists():
        return p
    if os.environ.get("TFS_MUSIC_DIR") or os.environ.get("PYTEST_CURRENT_TEST"):
        return None                              # local copy only; tests never touch the bucket
    try:
        from .. import state
        if not state.enabled():
            return None
        p.parent.mkdir(parents=True, exist_ok=True)
        state._s3().download_file(state._bucket(), PREFIX + name, str(p))
        return p
    except Exception as e:  # music is never worth failing a video for: the mixer falls back to the pad
        log.warning("music library: could not fetch %s: %s", name, e)
        return None


def index() -> list[dict]:
    p = _fetch("index.json")
    return json.loads(p.read_text(encoding="utf-8")) if p else []


def mood_of(text: str) -> str:
    t = (text or "").lower()
    for mood, rx in MOODS:
        if re.search(rx, t):
            return mood
    return DEFAULT_MOOD


def pick(text: str, seed: str, count: int = 1) -> list[str]:
    """`count` cue ids for this item: its mood's cues first (variant by a stable hash of `seed`), then neighbours."""
    cues = [c["cue_id"] for c in index()]
    if not cues:
        return []
    mood = mood_of(text)
    order = {"investigation": ["investigation", "dark", "curiosity", "urgent", "somber", "hopeful"],
             "dark": ["dark", "investigation", "somber", "urgent", "curiosity", "hopeful"],
             "urgent": ["urgent", "investigation", "dark", "curiosity", "hopeful", "somber"],
             "somber": ["somber", "hopeful", "investigation", "dark", "curiosity", "urgent"],
             "hopeful": ["hopeful", "curiosity", "investigation", "somber", "urgent", "dark"],
             "curiosity": ["curiosity", "investigation", "hopeful", "urgent", "dark", "somber"]}[mood]
    h = int(hashlib.sha1(seed.encode("utf-8")).hexdigest(), 16)
    ranked = []
    for m in order:
        group = sorted(c for c in cues if c.startswith(f"doc-{m}-"))
        if group:
            k = h % len(group)
            ranked += group[k:] + group[:k]
    return [ranked[i % len(ranked)] for i in range(count)]


def load_cue(cue_id: str) -> tuple[dict, np.ndarray] | None:
    mp, ap = _fetch(f"{cue_id}.json"), _fetch(f"{cue_id}.flac")
    if not (mp and ap):
        return None
    from .sfx_v2 import load_audio              # ffmpeg decode to mono float32 at 48 kHz
    return json.loads(mp.read_text(encoding="utf-8")), load_audio(ap, SR)


# ---- assembly at bar lines -------------------------------------------------------------------------------------
def plan(meta: dict, length: float, reveal: float | None, chain: bool = False,
         skip_lead: bool = False) -> list[tuple[float, float]]:
    """Source spans (start_s, end_s) of the cue that, joined end to end, last `length` s and (if `reveal`) put the
    start of the space section exactly at `reveal`. Every join is at a bar line of the cue.
    `chain`: the segment hands over to another cue (long-form chapter), so it ends on drive loops, filled to exactly
    `length`, instead of the ending. `skip_lead`: start at the first downbeat (no silent lead-in)."""
    s, bar = meta["sections"], meta["bar_s"]
    lo, le = meta["loop"]["start_s"], meta["loop"]["end_s"]
    intro = (meta.get("first_downbeat_s", 0.0) if skip_lead else 0.0, s["intro"]["end_s"])
    d1 = (s["drive"]["start_s"], lo)
    build = (s["build"]["start_s"], s["build"]["end_s"])
    space = (s["space"]["start_s"], s["space"]["end_s"])
    ret = (s["return"]["start_s"], s["return"]["end_s"])
    end = (s["ending"]["start_s"], meta["length_s"])
    dur = lambda sp: sp[1] - sp[0]

    def fill(spans, room, exact=False):
        """Repeat the loop region into `room` s at bar lines; `exact` adds a final partial span to use it all."""
        out = list(spans)
        while room >= dur((lo, le)) - 1e-6:
            out.append((lo, le)); room -= dur((lo, le))
        bars = int(room // bar + 1e-6)
        if bars:
            out.append((lo, lo + bars * bar)); room -= bars * bar
        if exact and room > 1e-6:
            out.append((lo, lo + room)); room = 0.0
        return out, room

    def trim_front(spans, cut):
        """Start `cut` s later inside the first span (keeps every later join on a bar line)."""
        if cut > 1e-6 and spans:
            a0, b0 = spans[0]
            spans[0] = (min(b0, a0 + cut), b0)
        return spans

    def tail(after, room):
        """What follows a point with `room` s left: the ending (one-off segment) or loops (chained segment)."""
        if chain:
            return fill(after, room, exact=True)[0]
        if room <= dur(end):
            return after + [(end[0], end[0] + max(0.0, room))]
        room -= dur(end)
        if room >= dur(ret):
            after = after + [ret]; room -= dur(ret)
        after, _ = fill(after, room)
        return after + [end]                      # any leftover (under a bar) is silence after the ending's tail

    if reveal is not None and bar - 1e-9 <= reveal < length:
        pre = None
        for head in ([intro, d1], [intro], []):
            need = sum(dur(x) for x in head) + dur(build)
            if reveal >= need - 1e-6:
                room = reveal - need
                spans, left = fill(list(head), room)
                if left > 1e-6:                   # one more bar, entered `bar - left` s late: total is exact
                    spans, left = fill(list(head), room + bar)
                    spans = trim_front(spans, bar - left)
                pre = spans + [build]
                break
        if pre is None:
            pre = [(build[1] - reveal, build[1])]
        got = sum(dur(x) for x in pre)
        pre = trim_front(pre, got - reveal)       # float clean-up only (a few ms at most)
        after = length - reveal
        if after <= dur(space):                   # the video ends inside the space section
            return pre + [(space[0], space[0] + after)]
        return pre + tail([space], after - dur(space))
    head = [intro, d1]
    room = length - sum(dur(x) for x in head)
    if room < 0:
        return [(intro[0], intro[0] + min(length, meta["length_s"] - intro[0]))]
    return tail(head, room)


def render_spans(audio: np.ndarray, spans: list[tuple[float, float]], length_n: int, fade_end: bool = True) -> np.ndarray:
    """Join the spans end to end at their planned positions. Each join overlaps by XFADE_S using the audio just
    after the outgoing span's end (so no join arrives early); `fade_end` fades the last 1.5 s."""
    xf = int(XFADE_S * SR)
    out = np.zeros(length_n + xf, np.float32)
    up = np.linspace(0, 1, xf, dtype=np.float32)
    cum = 0.0
    for i, (a, b) in enumerate(spans):
        pos = int(round(cum * SR))
        cum += b - a
        if pos >= length_n:
            break
        last = i == len(spans) - 1
        a0, b0 = int(round(a * SR)), int(round(b * SR))
        seg = audio[a0: min(len(audio), b0 + (0 if last else xf))].astype(np.float32).copy()
        if not len(seg):
            continue
        if i and len(seg) > xf:
            seg[:xf] *= up                        # fade in over the previous span's overrun
        if not last and len(seg) > (b0 - a0):
            k = len(seg) - (b0 - a0)
            seg[-k:] *= up[::-1][:k]              # overrun past the span end fades out
        end = min(len(out), pos + len(seg))
        out[pos:end] += seg[: end - pos]
    bed = out[:length_n]
    if fade_end:
        f = min(len(bed), int(1.5 * SR))
        bed[-f:] *= np.linspace(1, 0, f, dtype=np.float32) ** 1.5    # never stop dead at the very end
    return bed


# ---- level -----------------------------------------------------------------------------------------------------
def _kw(x):
    b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
    b2, a2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]
    return lfilter(b2, a2, lfilter(b1, a1, x))


def _phone(x):
    return sosfilt(butter(4, [300, 3400], btype="band", fs=SR, output="sos"), x)


def _win_db(x, win=0.4, hop=0.1):
    w, h = int(win * SR), int(hop * SR)
    p = np.asarray(x, np.float64) ** 2
    if len(p) < w:
        return np.array([10 * np.log10(p.mean() + 1e-12)])
    c = np.concatenate([[0.0], np.cumsum(p)])
    st = np.arange(0, len(p) - w + 1, h)
    return 10 * np.log10((c[st + w] - c[st]) / w + 1e-12)


def speech_frames(voice: np.ndarray) -> np.ndarray:
    v = _win_db(_kw(voice))
    return v > max(np.percentile(v, 95) - 25, -55)


def held(mask: np.ndarray, hold_s: float = HOLD_S, hop: float = 0.1) -> np.ndarray:
    m = mask.copy()
    on = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(int), [0]])))
    runs = list(zip(on[::2], on[1::2]))
    for (s0, e0), (s1, _) in zip(runs, runs[1:]):
        if (s1 - e0) * hop < hold_s:
            m[e0:s1] = True
    return m


def gain_db_curve(mask: np.ndarray, n: int, hop: float = 0.1, ctl: int = 1000) -> np.ndarray:
    """0 dB under (held) speech, +LIFT_DB in music-only stretches, slew-limited (attack and release ramps)."""
    ft = np.arange(len(mask)) * hop + 0.2
    tc = np.arange(int(n / SR * ctl) + 2) / ctl
    target = np.where(np.interp(tc + PRE_S, ft, mask.astype(float)) > 0.5, 0.0, LIFT_DB)
    out, cur = np.empty(len(tc)), target[0]
    a, r = LIFT_DB / (ATTACK_S * ctl), LIFT_DB / (RELEASE_S * ctl)
    for i, tg in enumerate(target):
        cur = max(tg, cur - a) if tg < cur else (min(tg, cur + r) if tg > cur else cur)
        out[i] = cur
    return np.interp(np.arange(n) / SR, tc, out)


def phone_gap(voice: np.ndarray, music: np.ndarray) -> float:
    sp = speech_frames(voice)
    v, m = _win_db(_phone(voice)), _win_db(_phone(music))
    k = min(len(v), len(m), len(sp))
    return float(np.median(v[:k][sp[:k]] - m[:k][sp[:k]])) if sp[:k].any() else float("nan")


def level(voice: np.ndarray, bed: np.ndarray, target_db: float = PHONE_GAP_DB) -> tuple[np.ndarray, float]:
    """Shape the bed under the voice and solve its gain so the phone-band gap while speaking is `target_db`."""
    n = len(bed)
    v = np.zeros(n, np.float32)
    v[: min(n, len(voice))] = voice[:n]
    shaped = bed * (10 ** (gain_db_curve(held(speech_frames(v)), n) / 20)).astype(np.float32)
    g = 0.0
    for _ in range(4):
        got = phone_gap(v, shaped * 10 ** (g / 20))
        if not np.isfinite(got):
            break
        g += got - target_db
    if not np.isfinite(phone_gap(v, shaped * 10 ** (g / 20))):  # no speech found: a fixed quiet bed (about -43 dB)
        lvl = np.median(_win_db(_kw(shaped)))
        g = -43.0 - lvl if np.isfinite(lvl) else 0.0
    out = (shaped * 10 ** (g / 20)).astype(np.float32)
    return out, phone_gap(v, out)


# ---- the bed ---------------------------------------------------------------------------------------------------
def bed(voice: np.ndarray, length_n: int, reveals: list[float], chapter_starts: list[float], text: str, seed: str):
    """Levelled music bed (mono float32, `length_n` samples) and a report dict, or (None, report) if the library is
    unavailable. `reveals` are reveal times in s; `chapter_starts` are chapter card start times (long-form)."""
    total = length_n / SR
    bounds = [0.0] + sorted(t for t in chapter_starts if 2.0 < t < total - 4.0) + [total]
    ids = pick(text, seed, count=len(bounds) - 1)
    report = {"music": "library", "mood": mood_of(text), "cues": ids, "chapters": len(bounds) - 1}
    if not ids:
        report["music"] = "pad (library unavailable)"
        return None, report
    out = np.zeros(length_n, np.float32)
    cx = int(CHAPTER_XFADE_S * SR)
    nseg = len(bounds) - 1
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        got = load_cue(ids[i])
        if got is None:
            report["music"] = f"pad (could not load {ids[i]})"
            return None, report
        meta, audio = got
        last = i == nseg - 1
        seg_len = b - a + (0 if last else CHAPTER_XFADE_S)   # chained segments run on under the next one's fade-in
        rv = next((r - a for r in reveals if a + 2.0 <= r < b - 2.0), None)
        if rv is not None and rv < meta["bar_s"]:
            rv = None
        spans = plan(meta, seg_len, rv, chain=not last, skip_lead=i > 0)
        seg = render_spans(audio, spans, int(round(seg_len * SR)), fade_end=last)
        s0 = int(round(a * SR))
        if i:                                    # one equal-power crossfade at the chapter card
            f = min(cx, len(seg), length_n - s0)
            ang = np.linspace(0, np.pi / 2, f, dtype=np.float32)
            seg[:f] *= np.sin(ang)
            out[s0: s0 + f] *= np.cos(ang)
        e0 = min(length_n, s0 + len(seg))
        out[s0:e0] += seg[: e0 - s0]
        report.setdefault("reveal_aligned", []).append(None if rv is None else round(a + rv, 3))
    levelled, gap = level(voice, out)
    report["phone_gap_db"] = round(gap, 1) if np.isfinite(gap) else None
    return levelled, report

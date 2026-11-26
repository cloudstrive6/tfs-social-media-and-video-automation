"""TFS sound design v2 (map-explainer style, approved by Bryce on 2026-11-24 with the v2.2 pilot).

A synthesized "paper desk" SFX palette (owned outright, so no Content ID risk), a cue engine that places each
sound on the visual beat the atlas runtime (engine atlas.js) animates, a synthesized documentary string bed
("pulse strings" on the same 4-chord plan, Bryce 2026-11-27; it replaced the pilot's sine pad), and the mix chain:

- speech gate from the narration (0.3 s moving averages) for the SFX bus;
- the music director (`music_duck`) for the bed: held about 15 dB under the voice through every pause shorter
  than 1.5 s, opening only at the intro, the outro and long pauses such as chapter cards (Bryce, 2026-11-27:
  the music must not jump up whenever the narrator pauses);
- bed swelling about 10 dB over the 1.5 s before each reveal, silent from
  reveal - 0.8 s to reveal + 1.6 s, then back over 0.8 s ("silence is a sound");
- SFX bus gain 1.78 * (1 - 0.75 * gate): about +5 dB in gaps, about 7 dB under speech;
- QC: voice-over-SFX margin in 50 ms windows where the voice is above -40 dBFS.

`master` then compresses and limits the raw mix with ffmpeg, looping the make-up gain until integrated loudness
is within 0.3 LU of the target (-14 LUFS), 48 kHz out.

Atlas blocks v3 (2026-11-25) add three sounds measured off the Worldwire reel: a mid stamp hit (body about
800 to 1,100 Hz, 0.3 s) for stamps, a bright UI tick (above 4 kHz, under 0.12 s) for checklist marks and city dots,
and a soft sub thump (mostly under 150 Hz) for panel landings and the globe arrival. Every cue still sits on a
visual event of the shot; shots of the v2 kinds get exactly the cues they had before.

Ported from revamp-2026-11/pilot/engine/sfx_tfs.py and remix.py (2026-11-24). Same sounds, same levels, same
cue rules; the RNG is reseeded on every `build_cues` call so output is deterministic per call.

Typical use:
    voice = load_audio(work / "narration.wav")             # 48 kHz mono float32
    mixed, report = mix(voice, shots, total)
    write_wav(work / "mix_raw.wav", mixed)
    lufs, peak = master(work / "mix_raw.wav", work / "mix.wav")
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import butter, oaconvolve, sosfilt

SR = 48000
SEED = 7
MIN_GAP = 1.2            # seconds between ordinary cues (hits, pens and ticks are exempt)

PAD_LEVEL = 0.035        # pad bed gain in gaps
PAD_DUCK = 0.82          # 1 - 0.82 is about -15 dB under speech
SFX_BUS = 1.78           # about +5 dB in gaps
SFX_DUCK = 0.75          # 1.78 * 0.25 is about -7 dB under speech
CHORD_SECONDS = 6.0
# The string bed's chord plan in MIDI notes (Am, F, C(add G), G): basses, the cello pulse root, the held triad
VOICING = [dict(bass=33, cello=45, triad=[57, 60, 64]), dict(bass=29, cello=41, triad=[57, 60, 65]),
           dict(bass=36, cello=48, triad=[55, 60, 64]), dict(bass=31, cello=43, triad=[55, 59, 62])]
PULSE_BPM = 80
MUSIC_TAIL = 1.5         # each chord block rings this long into the next
MUSIC_TRIM = 1.1         # unity-scale trim: the bed's integrated loudness matches the v2 sine pad (measured over 120 s)
HOLD_GAP = 1.5           # the music director: pauses shorter than this keep the bed ducked (lines are 0.35 s apart)
OPEN_DELAY = 0.35        # a longer pause opens the bed this long after the voice stops ...
OPEN_RISE = 1.2          # ... over this long ...
CLOSE_LEAD = 0.2         # ... and it is back under the voice this long before the voice returns ...
CLOSE_FALL = 0.8         # ... after closing over this long

_rng = np.random.default_rng(SEED)


# ---- helpers (identical maths to the pilot) --------------------------------------------------------------------
def db(x): return 10 ** (x / 20)
def n(sec): return int(sec * SR)
def noise(sec): return _rng.standard_normal(n(sec)).astype(np.float32)
def band(x, lo, hi, order=2): return sosfilt(butter(order, [lo, hi], btype="band", fs=SR, output="sos"), x).astype(np.float32)
def low(x, hi, order=2): return sosfilt(butter(order, hi, btype="low", fs=SR, output="sos"), x).astype(np.float32)
def high(x, lo, order=2): return sosfilt(butter(order, lo, btype="high", fs=SR, output="sos"), x).astype(np.float32)


def norm(x, peak_db):
    m = np.abs(x).max() + 1e-9
    return (x / m * db(peak_db)).astype(np.float32)


def ad(length, a, d_shape=4.0):
    k = max(1, int(a * length))
    e = np.ones(length)
    e[:k] = np.linspace(0, 1, k) ** 1.5
    e[k:] = (1 - np.linspace(0, 1, length - k)) ** d_shape
    return e.astype(np.float32)


# ---- palette -------------------------------------------------------------------------------------------------
def paper_swish(dur=0.34):
    """Sheet of paper slid across the desk: a band of noise whose centre sweeps up then settles."""
    x = noise(dur); L = len(x); out = np.zeros(L, np.float32)
    for i, (lo, hi) in enumerate([(900, 2600), (1600, 4800), (2600, 7500)]):
        out += band(x, lo, hi) * np.sin(np.linspace(0, np.pi, L)) ** (1.5 + i)
    return norm(out * ad(L, 0.35, 2.2), -27)


def card_slap(heavy=False):
    """A stiff card landing on paper: soft transient, paper flutter, small low thump."""
    L = n(0.32); t = np.arange(L) / SR
    crack = low(noise(0.32), 4200) * np.exp(-t / 0.018)
    flutter = band(noise(0.32), 1200, 5000) * np.exp(-t / 0.06) * 0.35
    thump = np.sin(2 * np.pi * (95 if heavy else 120) * t) * np.exp(-t / (0.11 if heavy else 0.07)) * (1.2 if heavy else 0.7)
    return norm(crack + flutter + thump, -26 if heavy else -24)


def pen_circle(dur=0.6):
    """Felt pen drawing a quick loop: scratchy band noise in short strokes."""
    L = n(dur); t = np.arange(L) / SR
    strokes = 0.55 + 0.45 * np.abs(np.sin(2 * np.pi * 4.2 * t + _rng.uniform(0, 1)))
    grain = band(noise(dur), 2200, 6500) * strokes + band(noise(dur), 700, 1600) * 0.25
    return norm(grain * ad(L, 0.08, 1.2), -29)


def marker_swipe(dur=0.65):
    """Highlighter dragged across a line: one smooth, slightly squeaky stroke."""
    L = n(dur); t = np.arange(L) / SR
    body = band(noise(dur), 900, 3200)
    squeak = np.sin(2 * np.pi * (1850 + 120 * np.sin(2 * np.pi * 3 * t)) * t) * 0.05
    return norm((body + squeak) * ad(L, 0.15, 1.0), -31)


def tick(f=2100):
    L = n(0.05); t = np.arange(L) / SR
    return norm(np.sin(2 * np.pi * f * t) * np.exp(-t / 0.008) + high(noise(0.05), 3000) * np.exp(-t / 0.004) * 0.4, -30)


def bar_fill(dur=0.9, count=9):
    """Ticks that slow down with the bar's power2.out ease."""
    out = np.zeros(n(dur + 0.06), np.float32)
    for i in range(count):
        u = i / (count - 1)
        at = dur * (1 - (1 - u) ** 0.5)                       # dense first, then slower, like power2.out
        tk = tick(1800 + 500 * u) * (0.75 + 0.25 * u)
        s = n(at); out[s:s + len(tk)] += tk[: len(out) - s]
    return out


def pop():
    """Paper tab tap for list items."""
    L = n(0.12); t = np.arange(L) / SR
    return norm(band(noise(0.12), 600, 3800) * np.exp(-t / 0.02) + np.sin(2 * np.pi * 300 * t) * np.exp(-t / 0.03) * 0.5, -20)


def riser(dur=1.0):
    """Air and a low tone climbing into a chapter card; peaks right at the landing."""
    L = n(dur); t = np.arange(L) / SR; u = t / dur
    air = np.zeros(L, np.float32)
    for k, (lo, hi) in enumerate([(300, 900), (700, 2000), (1500, 4500), (3000, 9000)]):
        air += band(noise(dur), lo, hi) * np.clip((u - k * 0.18) / 0.4, 0, 1)
    tone = np.sin(2 * np.pi * (110 * t + 70 * t * u)) * 0.6
    return norm((air * 0.6 + tone) * (u ** 2.2), -25)


def low_hit():
    """Deep, short documentary hit for the reveal."""
    L = n(1.4); t = np.arange(L) / SR
    f = 62 - 18 * (1 - np.exp(-t / 0.25))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.3)
    knock = low(noise(1.4), 300) * np.exp(-t / 0.03) * 0.15        # soft attack: the hit often lands on a word
    tail = band(noise(1.4), 150, 600) * np.exp(-t / 0.5) * 0.12
    return norm(body + knock + tail, -23)


def soft_air(dur=0.9):
    """Gentle air move for photo cutaways and map moves."""
    L = n(dur); x = noise(dur)
    centre = np.sin(np.linspace(0, np.pi, L))
    out = band(x, 400, 1400) * centre ** 2 + band(x, 1400, 4200) * centre ** 4 * 0.6
    return norm(out, -26)


def stamp_hit():
    """A stamp slammed onto paper: a mid body around 950 Hz with a fast knock, about 0.3 s."""
    L = n(0.3); t = np.arange(L) / SR
    body = band(noise(0.3), 800, 1100, order=4) * np.exp(-t / 0.07)
    tone = np.sin(2 * np.pi * 940 * t) * np.exp(-t / 0.05) * 0.6
    knock = band(noise(0.3), 500, 1300, order=3) * np.exp(-t / 0.01) * 0.5
    return norm(low((body + tone + knock) * ad(L, 0.01, 1.5), 1800, order=4), -25)


def ui_tick():
    """Bright interface tick for a check mark, an X or a city dot: above 4 kHz, about 0.06 s."""
    L = n(0.06); t = np.arange(L) / SR
    click = band(noise(0.06), 4500, 9000, order=4) * np.exp(-t / 0.005)
    ping = np.sin(2 * np.pi * 6400 * t) * np.exp(-t / 0.012) * 0.6
    return norm(click + ping, -27)


def sub_thump():
    """Soft low landing for a panel or the globe arriving on its country: mostly under 150 Hz, 0.4 s."""
    L = n(0.4); t = np.arange(L) / SR
    f = 72 - 24 * (1 - np.exp(-t / 0.08))
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.11)
    air = low(noise(0.4), 180) * np.exp(-t / 0.05) * 0.5
    return norm((body + air) * ad(L, 0.02, 1.2), -27)


def camera_push(dur=3.6):
    """Long airy push with a low rumble for the 3D hero shot."""
    L = n(dur); t = np.arange(L) / SR; u = t / dur
    air = band(noise(dur), 500, 3500) * (np.sin(np.pi * u) ** 1.5)
    rumble = low(noise(dur), 120) * 3 * np.sin(np.pi * np.clip(u * 1.2, 0, 1))
    return norm(air + rumble, -24)


def projector(dur):
    """Film projector under archive footage: 24 fps gate clatter plus motor hum."""
    L = n(dur); t = np.arange(L) / SR
    clicks = np.zeros(L, np.float32)
    for k in range(int(dur * 24)):
        s = max(0, n(k / 24 + _rng.uniform(-0.002, 0.002)))   # clamp: the first click could jitter below 0 s
        c = band(noise(0.02), 1200, 5000) * np.exp(-np.arange(n(0.02)) / SR / 0.004)
        clicks[s:s + len(c)] += c[: L - s] * (0.8 + 0.4 * _rng.random())
    hum = (np.sin(2 * np.pi * 60 * t) * 0.3 + np.sin(2 * np.pi * 120 * t) * 0.15) * 0.4
    env = np.minimum(1, t / 0.3) * np.minimum(1, (dur - t) / 0.3)
    return norm((clicks + hum) * env, -19)


def room_tone(dur):
    """Very quiet hall air. Kept in the palette, but the approved v2.2 mix does NOT use it (no room tone)."""
    L = n(dur); t = np.arange(L) / SR
    x = low(noise(dur), 700) + band(noise(dur), 2000, 5000) * 0.08
    env = np.minimum(1, t / 0.4) * np.minimum(1, (dur - t) / 0.4)
    return norm(x * env, -40)


# ---- cue engine ----------------------------------------------------------------------------------------------
def is_reveal(s: dict) -> bool:
    """The big turn of a video: a card or bigtext whose answer is zero."""
    texts = [it.get("big", "") for it in s.get("items", [])] + [s.get("text", ""), s.get("foot", "")]
    return any(str(x).strip().endswith(": 0") or str(x).strip() == "0" or "\n0" in str(x) or ": 0\n" in str(x)
               for x in texts)


def build_cues(shots: list[dict], total: float, seed: int = SEED):
    """Return (cues, track, reveals): cues as (time, name, job), a mono float32 48 kHz track of
    int((total + 0.5) * 48000) samples, and the reveal shot start times.

    `shots` are the atlas.js shot dicts (k, t0, t1, plus src, gate, mat, items, hl, foot, text, view...)."""
    global _rng
    _rng = np.random.default_rng(seed)
    track = np.zeros(n(total + 1.5), np.float32)
    cues, reveals = [], []
    last_ordinary = -9.0

    def put(at, sound, name, job, ordinary=True):
        nonlocal last_ordinary
        if at < 0:
            return
        if ordinary and at - last_ordinary < MIN_GAP:
            return
        s = n(at); track[s:s + len(sound)] += sound[: max(0, len(track) - s)]
        cues.append((round(at, 2), name, job))
        if ordinary:
            last_ordinary = at

    prev_kind = None
    for s in sorted(shots, key=lambda x: x["t0"]):
        k, t0, t1 = s.get("k"), s["t0"], s["t1"]
        dur = t1 - t0
        if k == "title" and s.get("mat"):
            put(t0 - 0.95, riser(1.0), "riser", "lift into the chapter card", ordinary=False)
            put(t0 + 0.08, card_slap(heavy=True), "card slap (heavy)", "chapter card lands", ordinary=False)
            last_ordinary = t0
        elif k == "title":
            put(t0 + 0.05, card_slap(), "card slap", "title card lands")
        elif k == "broll":
            if s.get("gate"):
                put(t0, projector(dur), "projector", "archive footage feels like film", ordinary=False)
            elif s.get("src", "").endswith("hero.mp4"):
                put(t0, camera_push(dur), "camera push", "3D push to Metro Manila", ordinary=False)
            else:
                put(t0 - 0.1, soft_air(0.9), "soft air", "cut to a real place")
        elif k == "doc":
            put(t0, paper_swish(), "paper swish", "document slides in")
            put(t0 + 0.35, pen_circle(0.6), "pen circle", "red ring around the section", ordinary=False)
            hl = s.get("hl") or []
            for i in range(len(hl)):
                at = t0 + 0.5 + i * max(0.8, (dur - 1.2) / max(1, len(hl)))
                if at < t0 + 0.35 + 0.6:
                    continue                                       # the pen circle already covers this moment
                put(at, marker_swipe(0.7), "marker swipe", "highlight the quoted words", ordinary=False)
        elif k in ("cards", "seats", "timeline"):
            items = s.get("items", [])
            last_item = -9.0
            for i in range(len(items)):
                if k == "cards":
                    at = t0 + i * max(0.5, (dur - 1) / len(items))
                elif k == "seats":
                    at = t0 + i * max(0.8, (dur - 1) / len(items))
                else:
                    at = t0 + i * max(0.6, (dur - 1.5) / (len(items) + (1 if s.get("foot") else 0)))
                snd = card_slap() if k == "cards" else pop()
                if at - last_item < MIN_GAP:                       # item cues 1.2 s apart: nudge up to 0.15 s, else skip
                    if last_item + MIN_GAP - at > 0.15:
                        continue
                    at = last_item + MIN_GAP
                last_item = at
                put(at + 0.05, snd, "card slap" if k == "cards" else "tab pop", "each point lands",
                    ordinary=(i == 0 and prev_kind != k))
        elif k == "bars":
            put(t0, paper_swish(), "paper swish", "chart slides in")
            items = s.get("items", [])
            for i in range(len(items)):
                put(t0 + 0.4 + i * max(0.6, (dur - 1.2) / len(items)), bar_fill(), "bar ticks",
                    "bar fills to its threshold", ordinary=False)
        elif k in ("bigtext", "compare", "split"):
            put(t0, card_slap() if k != "split" else paper_swish(), "card slap" if k != "split" else "paper swish",
                "new idea on screen")
        elif k == "map" and s.get("view") and prev_kind == "map":
            put(t0, soft_air(1.2), "soft air", "map move")
        elif k in V3_KINDS:
            for at, snd, name, job, ordinary in _v3_cues(s):
                put(at, snd(), name, job, ordinary=ordinary)
        for tg in s.get("tags", []) or []:
            put(tg.get("at", t0), pop(), "tab pop", f"number tag '{tg.get('text', '')}' lands", ordinary=False)
        if s.get("stamp"):
            st = s["stamp"]
            put(st.get("at", t0 + 0.5), stamp_hit(), "stamp hit", f"stamp '{st.get('text', '')}' lands", ordinary=False)
        if is_reveal(s):
            reveals.append(t0)
            put(t0 + 0.05, low_hit(), "low hit", "the reveal: zero", ordinary=False)
        prev_kind = k
    return cues, track[: n(total + 0.5)], reveals


V3_KINDS = ("globe", "checklist", "linechart", "barchart", "waffle", "balance", "dates", "media")


def _v3_cues(s: dict) -> list[tuple]:
    """(time, sound factory, name, job, ordinary) for a v3 block, on the times atlas_blocks.js animates (the planner
    writes them on the shot; hand-written shots fall back to the same even spread)."""
    from .atlas_plan import STEPS, globe_timing, step_times

    k, t0, t1 = s["k"], s["t0"], s["t1"]

    def ats(field, kind):
        xs = s.get(field, [])
        lead, gap = STEPS[kind]
        return step_times([x.get("at") for x in xs], t0, t1, lead, gap)

    out = []
    if k == "globe":
        rot_at, rot_dur = globe_timing(t0, t1)
        out.append((t0 - 0.1, lambda: soft_air(1.2), "soft air", "the globe turns", True))
        hl = s.get("highlight", [])
        if hl:
            out.append((hl[0].get("at", rot_at + rot_dur + 0.2), sub_thump, "sub thump", "the globe arrives on the country",
                        False))
        places = s.get("places", [])
        for at in step_times([p.get("at") for p in places], t0, t1, rot_dur + 0.6, 0.6):
            out.append((at, ui_tick, "ui tick", "a city dot lands", False))
        for i, a in enumerate(s.get("arcs", [])):
            out.append((a.get("at", rot_at + rot_dur + 0.6 + i * 1.4), paper_swish, "swish", "a route launches", False))
    elif k == "checklist":
        out.append((t0, sub_thump, "sub thump", "the checklist panel lands", True))
        for at in ats("items", "checklist"):
            out.append((at + 0.25, ui_tick, "ui tick", "a tick or an X draws", False))
    elif k == "linechart":
        draw = s["bigAt"] if isinstance(s.get("bigAt"), (int, float)) and s["bigAt"] < t1 - 1 else t0 + 0.55
        out.append((t0, paper_swish, "paper swish", "chart panel slides in", True))
        out.append((draw, lambda: bar_fill(2.25, 10), "count ticks", "the line draws and the number counts up", False))
        co = s.get("calloutAt") if isinstance(s.get("calloutAt"), (int, float)) and s["calloutAt"] >= draw else draw + 2.3
        if s.get("callout"):
            out.append((co, pop, "tab pop", "the end-dot callout pops", False))
    elif k == "barchart":
        out.append((t0, paper_swish, "paper swish", "chart panel slides in", True))
        bars = ats("items", "barchart")
        for at in bars:
            out.append((at, lambda: bar_fill(0.5, 5), "bar ticks", "a bar grows and counts up", False))
        if s.get("callout") and len(bars) > 1:
            co = s.get("calloutAt") if isinstance(s.get("calloutAt"), (int, float)) and s["calloutAt"] > bars[-1]                 else bars[-1] + 0.7
            out.append((co + 0.2, pop, "tab pop", "the annotation arrow lands", False))
    elif k == "waffle":
        out.append((t0, paper_swish, "paper swish", "the grid wipes in", True))
        frac = float(s.get("frac") or 0)
        kk = max(1, min(400, round(frac * 400))) if frac > 0 else 0
        fill_at = t0 + 1.35
        if kk:
            out.append((fill_at, lambda: bar_fill(1.0, 8), "fill ticks", "the squares fill", False))
        fill_end = fill_at + (min(0.05, 1.0 / kk) * kk if kk else 0)
        lab = s["bigAt"] if isinstance(s.get("bigAt"), (int, float)) and s["bigAt"] >= t0 + 0.5 else fill_end + 0.1
        out.append((lab, pop, "tab pop", "the share label lands on its word", False))
    elif k == "balance":
        out.append((t0, paper_swish, "paper swish", "the balance bar draws", True))
        fill = s["bigAt"] if isinstance(s.get("bigAt"), (int, float)) and s["bigAt"] >= t0 + 0.6 else t0 + 0.9
        out.append((min(fill, t0 + 0.9), lambda: bar_fill(0.6, 6), "bar ticks", "the sliver fills", False))
        if s.get("small"):
            out.append((fill + 1.25, pop, "tab pop", "the tag lands", False))
        for c in s.get("chips", []):
            if c.get("at"):
                out.append((c["at"], ui_tick, "ui tick", "an honesty chip lands", False))
    elif k == "dates":
        for at in ats("items", "dates"):
            out.append((at, card_slap, "card slap", "a date card pops", False))
    elif k == "media":
        out.append((t0 - 0.1, lambda: soft_air(0.9), "soft air", "a photo card slides in", True))
        for at in ats("rows", "rows"):
            out.append((at, pop, "tab pop", "a side-list row lands", False))
        for at in ats("chips", "chips"):
            out.append((at, ui_tick, "ui tick", "an honesty chip lands", False))
    return out


# ---- music pad and mix -----------------------------------------------------------------------------------------
def _hz(midi: float) -> float: return 440.0 * 2 ** ((midi - 69) / 12)


def _lp(x, f, order=2): return sosfilt(butter(order, f, btype="low", fs=SR, output="sos"), x)
def _hp(x, f, order=2): return sosfilt(butter(order, f, btype="high", fs=SR, output="sos"), x)


def _peaking(x, f0, gain_db, q):
    """RBJ peaking EQ biquad."""
    A = 10 ** (gain_db / 40); w = 2 * np.pi * f0 / SR; al = np.sin(w) / (2 * q)
    b = np.array([1 + al * A, -2 * np.cos(w), 1 - al * A]); a = np.array([1 + al / A, -2 * np.cos(w), 1 - al / A])
    return sosfilt(np.concatenate([b / a[0], a / a[0]])[None, :], x)


def _saw(freq: np.ndarray) -> np.ndarray:
    """Band-limited sawtooth (polyBLEP) from an instantaneous frequency curve in Hz."""
    dt = freq / SR
    t = np.cumsum(dt) % 1.0
    y = 2 * t - 1
    m = t < dt
    x = t[m] / dt[m]; y[m] -= 2 * x - x * x - 1
    m = t > 1 - dt
    x = (t[m] - 1) / dt[m]; y[m] -= x * x + 2 * x + 1
    return y


def _bowed(midi, dur, rng, players, vib_cents, dark, bright, attack=1.4, release=1.5, vib_rate=5.2, detune=5.0):
    """A string section holding one note: detuned players who never start together, vibrato that comes in after the
    bow settles, a slow smooth bow attack, and a tone that brightens with bow pressure (the envelope)."""
    L = int(dur * SR); t = np.arange(L) / SR
    out = np.zeros(L)
    for _ in range(players):
        det = rng.normal(0, detune)
        rate = vib_rate * (1 + rng.normal(0, 0.07))
        ph = rng.uniform(0, 2 * np.pi)
        drift = _lp(rng.standard_normal(L), 1.5, 1) * 40                    # slow pitch wander, a couple of cents
        cents = det + vib_cents * np.clip((t - 0.35) / 1.2, 0, 1) * np.sin(2 * np.pi * rate * t + ph) + drift
        s = int(rng.uniform(0, 0.06) * SR)
        out[s:] += _saw(_hz(midi) * 2 ** (cents / 1200))[: L - s]
    out /= np.sqrt(players)
    a = np.clip(t / attack, 0, 1); a = a * a * (3 - 2 * a)
    r = np.clip((dur - t) / release, 0, 1); r = r * r * (3 - 2 * r)
    env = a * r * (1 + 0.12 * np.sin(np.pi * np.clip(t / dur, 0, 1)))
    w = np.clip(env, 0, 1) ** 2
    return _hp(_lp(out, dark) * (1 - w) + _lp(out, bright) * w, max(35.0, _hz(midi) * 0.7)) * env


def _spiccato(midi, dur, rng, players, accent):
    """One short bounced bow stroke for a section (about 0.16 s decay)."""
    L = int(dur * SR); t = np.arange(L) / SR
    y = np.zeros(L)
    for _ in range(players):
        s = int(abs(rng.normal(0, 0.006)) * SR)
        y[s:] += _saw(np.full(L, _hz(midi) * 2 ** (rng.normal(0, 6) / 1200)))[: L - s]
    env = np.clip(t / 0.018, 0, 1) * np.exp(-t / 0.16)
    return _hp(_lp(y / np.sqrt(players), 2000), _hz(midi) * 0.7) * env * accent


_BLOCKS: dict[int, np.ndarray] = {}
_IR: list[np.ndarray] = []


def _chord_block(i: int) -> np.ndarray:
    """Chord i of the plan (VOICING[i % 4]), CHORD_SECONDS + MUSIC_TAIL long, unity scale. Eight distinct blocks
    (i % 8, own seeded RNG so the SFX RNG is never touched), cached for the process: deterministic."""
    key = i % 8
    if key in _BLOCKS:
        return _BLOCKS[key]
    v = VOICING[key % 4]
    rng = np.random.default_rng(SEED * 1000 + key)
    dur = CHORD_SECONDS + MUSIC_TAIL
    L = int(dur * SR)
    out = np.zeros(L)

    def add(x, at=0.0, g=1.0):
        s = int(at * SR); k = min(len(x), L - s)
        out[s:s + k] += g * x[:k]

    add(_bowed(v["bass"], dur, rng, 3, 4, 600, 1000), g=0.6)                              # basses, legato roots
    for m in v["triad"]:
        add(_bowed(m + 12, dur, rng, 6, 10, 2200, 3800, attack=1.8), g=0.14)             # high violins, held
    eighth = 60 / PULSE_BPM / 2
    root, fifth = v["cello"], v["cello"] + 7
    pattern = [root, root, fifth, root, root + 12, root, fifth, root]
    for k in range(int(CHORD_SECONDS / eighth)):
        acc = 1.0 if k % 4 == 0 else (0.75 if k % 2 == 0 else 0.6)
        add(_spiccato(pattern[k % 8], 0.45, rng, 3, acc), at=k * eighth, g=0.5)         # cellos
        if k % 2 == 0:
            add(_spiccato(pattern[k % 8] + 12, 0.4, rng, 3, acc * 0.7), at=k * eighth + 0.002, g=0.28)   # violas
    _BLOCKS[key] = out
    return out


def _hall_ir() -> np.ndarray:
    """Synthesized hall impulse response: early reflections, then a tail that darkens as it decays (RT60 2.6 s
    below 1.5 kHz, 1.3 s above)."""
    if not _IR:
        rng = np.random.default_rng(11)
        L = int(3.2 * SR); t = np.arange(L) / SR
        nz = rng.standard_normal(L)
        tail = (_lp(nz, 1500) * np.exp(-6.91 * t / 2.6) + 0.6 * _hp(nz, 1500) * np.exp(-6.91 * t / 1.3)) \
            * np.clip((t - 0.02) / 0.03, 0, 1)
        for d, g in ((0.011, 0.5), (0.019, -0.35), (0.027, 0.3), (0.041, -0.22), (0.057, 0.18)):
            tail[int(d * SR)] += g * 3
        _IR.append(tail / np.sqrt((tail ** 2).sum()))
    return _IR[0]


def music_pad(total: float, length: int | None = None, sr: int = SR) -> np.ndarray:
    """The documentary string bed ("pulse strings", picked by Bryce on 2026-11-27 over chamber strings and a small
    orchestra): the TFS chord plan (Am, F, C(add G), G; 6 s each) played by legato basses and held high violins over
    a spiccato cello and viola eighth-note pulse at 80 bpm (two bars per chord), in a synthesized hall. Synthesized
    from nothing, so owned outright. Unity scale, loudness matched to the v2 sine pad (so PAD_LEVEL keeps its
    meaning); `mix` applies the bed gain."""
    if sr != SR:
        raise ValueError(f"sfx_v2 is built at {SR} Hz (got {sr})")
    L = length if length is not None else int((total + 0.5) * sr)
    dry = np.zeros(L + int((MUSIC_TAIL + 1) * sr))
    for i in range(int(L / sr / CHORD_SECONDS) + 1):
        b = _chord_block(i); s = int(i * CHORD_SECONDS * sr)
        k = min(len(b), len(dry) - s)
        dry[s:s + k] += b[:k]
    dry = dry[:L]
    y = 0.72 * dry + 0.55 * oaconvolve(dry, _hall_ir())[:L]
    y = _peaking(_peaking(_hp(y, 38), 2500, -4.0, 0.8), 250, -1.5, 1.0)                 # room for the voice
    return (y * MUSIC_TRIM).astype(np.float32)


def _smooth(x: np.ndarray, win: int) -> np.ndarray:
    """Centred moving average via a running sum (float64)."""
    c = np.cumsum(np.concatenate([np.zeros(win), x, np.zeros(win)]))
    return ((c[win:] - c[:-win]) / win)[win // 2: win // 2 + len(x)]


def speech_gate(voice: np.ndarray, sr: int = SR) -> np.ndarray:
    """0..1 curve, about 1 while the narrator speaks: smoothed |voice| over 8 % of its maximum, smoothed again."""
    win = int(0.3 * sr)
    speech = _smooth(np.abs(voice), win)
    return _smooth(np.clip(speech / (speech.max() * 0.08 + 1e-9), 0, 1), win)


def music_duck(voice: np.ndarray, sr: int = SR) -> np.ndarray:
    """The music director's duck curve for the bed (0 = open, 1 = held under the voice). Bryce, 2026-11-27: the
    music must not jump up every time the narrator pauses. So a pause shorter than HOLD_GAP (breaths, the 0.35 s
    between lines) keeps the bed down; only the intro, the outro and long pauses (the 2.6 s long-form chapter cards)
    open it: OPEN_DELAY after the voice stops it rises over OPEN_RISE, and it is back down CLOSE_LEAD before the voice
    returns (offline, so it can look ahead), closing over CLOSE_FALL. Smooth (smoothstep) both ways."""
    L = len(voice)
    env = _smooth(np.abs(np.asarray(voice, dtype=np.float64)), max(1, int(0.05 * sr)))
    peak = env.max() if L else 0.0
    if peak <= db(-60):
        return np.zeros(L)
    active = env > 0.04 * peak
    edges = np.flatnonzero(np.diff(np.concatenate([[0], active.astype(np.int8), [0]])))
    starts, ends = edges[0::2], edges[1::2]                                  # speech runs [start, end)
    gaps = [(0, starts[0], True, False)]                                    # (a, b, leading, trailing)
    gaps += [(ends[k], starts[k + 1], False, False) for k in range(len(starts) - 1)]
    gaps.append((ends[-1], L, False, True))
    duck = np.ones(L)
    ss = lambda x: x * x * (3 - 2 * x)                                       # noqa: E731
    for a, b, leading, trailing in gaps:
        if b <= a or (not leading and not trailing and (b - a) / sr < HOLD_GAP):
            continue
        t = np.arange(a, b) / sr
        up = np.ones(b - a) if leading else ss(np.clip((t - a / sr - OPEN_DELAY) / OPEN_RISE, 0, 1))
        down = np.ones(b - a) if trailing else ss(np.clip((b / sr - CLOSE_LEAD - t) / CLOSE_FALL, 0, 1))
        duck[a:b] = 1 - np.minimum(up, down)
    return duck


def pad_gain_curve(gate: np.ndarray, reveals: list[float], sr: int = SR) -> np.ndarray:
    """Pad gain: PAD_LEVEL ducked about 15 dB under speech; before each reveal a swell (+10 dB over 1.5 s from
    reveal - 2.3 s), a hard cut at reveal - 0.8 s, silence to reveal + 1.6 s, back over 0.8 s."""
    t = np.arange(len(gate)) / sr
    g = PAD_LEVEL * (1 - PAD_DUCK * gate)
    for r in reveals:
        swell = 1 + 2.2 * np.clip((t - (r - 2.3)) / 1.5, 0, 1) * (t < r - 0.8)
        g = (np.maximum(g, PAD_LEVEL * 0.4) * swell * (t >= r - 2.3) * (t < r - 0.8)
             + g * ((t < r - 2.3) | (t >= r - 0.8)))
        back = np.clip((t - (r + 1.6)) / 0.8, 0, 1)
        g = np.where(t < r - 0.8, g, g * back)
    return g


def voice_over_sfx(voice: np.ndarray, sfx_bus: np.ndarray, sr: int = SR):
    """(median, p10, worst) dB of voice RMS over SFX-bus RMS in 50 ms windows where the voice is above -40 dBFS
    and the effects above -70 dBFS; Nones if they never overlap."""
    w = int(0.05 * sr); m = min(len(voice), len(sfx_bus)) // w
    vr = np.sqrt((voice[: m * w].astype(np.float64).reshape(m, w) ** 2).mean(1))
    fr = np.sqrt((sfx_bus[: m * w].astype(np.float64).reshape(m, w) ** 2).mean(1))
    both = (vr > db(-40)) & (fr > db(-70))
    if not both.any():
        return None, None, None
    d = 20 * np.log10(vr[both] / fr[both])
    return float(np.median(d)), float(np.percentile(d, 10)), float(d.min())


def mix(voice: np.ndarray, shots: list[dict], total: float, sr: int = SR, seed: int = SEED):
    """Narration + ducked pad + SFX bus -> (mono float32 mix, report). `voice` is mono float32 at 48 kHz, placed
    at 0 s. Output length is max(len(voice), int((total + 0.5) * sr)). The mix is not normalised: write it
    with `write_wav` (float, no clipping) and finish it with `master`."""
    if sr != SR:
        raise ValueError(f"sfx_v2 is built at {SR} Hz; resample the voice first (got {sr})")
    voice = np.asarray(voice, dtype=np.float32)
    if voice.ndim > 1:
        voice = voice.mean(axis=1).astype(np.float32)
    L = max(len(voice), int((total + 0.5) * sr))
    track = np.zeros(L, np.float32)
    track[: len(voice)] = voice
    gate = speech_gate(track, sr)
    cues, sfx, reveals = build_cues(shots, total, seed=seed)
    sfx = np.pad(sfx, (0, max(0, L - len(sfx))))[:L]
    pad_g = pad_gain_curve(music_duck(track, sr), reveals, sr)             # the bed holds through short pauses
    sfx_bus = sfx * (SFX_BUS * (1 - SFX_DUCK * gate))
    out = (track + music_pad(total, L, sr) * pad_g + sfx_bus).astype(np.float32)
    median, p10, worst = voice_over_sfx(track, sfx_bus, sr)
    report = {
        "cues": cues,
        "reveals": reveals,
        "voice_over_sfx_db_median": median,
        "voice_over_sfx_db_p10": p10,
        "voice_over_sfx_db_worst": worst,
    }
    return out, report


# ---- file helpers and mastering ---------------------------------------------------------------------------------
def load_audio(path: str | Path, sr: int = SR) -> np.ndarray:
    """Decode any audio file to mono float32 at `sr` with ffmpeg."""
    res = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True)
    if res.returncode:
        raise RuntimeError(f"ffmpeg (decode) failed: {res.stderr.decode(errors='replace')[-1500:]}")
    return np.frombuffer(res.stdout, dtype="<f4").copy()


def write_wav(path: str | Path, mono: np.ndarray, sr: int = SR) -> Path:
    """Write a mono 32-bit float WAV (no clipping before the limiter)."""
    data = np.asarray(mono, dtype="<f4").tobytes()
    fmt = (3).to_bytes(2, "little") + (1).to_bytes(2, "little") + sr.to_bytes(4, "little") \
        + (sr * 4).to_bytes(4, "little") + (4).to_bytes(2, "little") + (32).to_bytes(2, "little")
    body = b"WAVE" + b"fmt " + len(fmt).to_bytes(4, "little") + fmt + b"data" + len(data).to_bytes(4, "little") + data
    path = Path(path)
    path.write_bytes(b"RIFF" + len(body).to_bytes(4, "little") + body)
    return path


def loudness(path: str | Path) -> tuple[float, float]:
    """(integrated LUFS, true peak dBFS) from ffmpeg's ebur128 summary."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    summ = out[out.rfind("Summary"):]
    i = re.search(r"I:\s+(-?[\d.]+)", summ)
    pk = re.search(r"Peak:\s+(-?[\d.]+)", summ)
    if not (i and pk):
        raise RuntimeError(f"ffmpeg ebur128 gave no summary for {path}: {out[-800:]}")
    return float(i.group(1)), float(pk.group(1))


def master(in_wav: str | Path, out_wav: str | Path, target: float = -14.0, tries: int = 6) -> tuple[float, float]:
    """Light compression (2:1 above -20 dB), make-up gain, limiter at 0.70 (about -3.1 dBFS sample peak), 48 kHz.
    Loops the gain until integrated loudness is within 0.3 LU of `target`. Returns (LUFS, true peak dBFS).

    The pilot stepped the gain by the plain LU error, which converges slowly once the limiter works (the approved
    pilot chapter sat at -14.5 after 4 passes). From the second pass the step is scaled by the measured dB per LU
    (secant step, slope clamped to 1..4)."""
    g = 0.0
    i = pk = None
    prev = None
    for _ in range(tries):
        res = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(in_wav), "-af",
                              f"acompressor=threshold=-20dB:ratio=2:attack=10:release=150,volume={g}dB,"
                              f"alimiter=limit=0.70:level=disabled", "-ar", str(SR), str(out_wav)],
                             capture_output=True, text=True)
        if res.returncode:
            raise RuntimeError(f"ffmpeg (master) failed: {res.stderr[-1500:]}")
        i, pk = loudness(out_wav)
        if abs(i - target) <= 0.3:
            break
        slope = 1.0
        if prev is not None and abs(i - prev[1]) > 0.05:
            slope = min(4.0, max(1.0, (g - prev[0]) / (i - prev[1])))
        prev = (g, i)
        g = round(g + (target - i) * slope, 2)
    return i, pk

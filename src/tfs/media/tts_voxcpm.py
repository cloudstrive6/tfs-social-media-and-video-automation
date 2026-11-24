"""Narrator on VoxCPM2 (Modal L4 GPU) in clone mode from the approved master clip, checked by Whisper.

Flow per scene (ported from the 2026-11 pilot, revamp-2026-11/pilot/engine/align_and_mix.py):
1. Digits become spoken words before the text goes to VoxCPM ("1987" -> "nineteen eighty-seven").
2. The deployed Modal function "tfs-voice"/"narrate" (modal_apps/tfs_voice.py) returns 2 takes per line
   (16-bit mono WAV at the native 48 kHz). Lines are sent in chunks of CHUNK, run in parallel containers.
3. Each take is trimmed (silence below -38 dB of the peak, keeping 0.05 s before and 0.12 s after), heard by
   faster-whisper (same model and language as qa.py, CPU int8) and scored by letter match against the script:
   difflib on the joined letters with autojunk=False, with numbers turned into words on both sides so Whisper's
   "Article 7" matches the spoken "Article seven".
4. The best take wins; below 0.85 the scene is retried once with new seeds, then fails (NarrationQualityError).
5. Whisper's word times are mapped onto the script's own words (difflib block matching, gaps interpolated), so
   captions keep the script spelling, digits included.
Output matches tts.py: <out_dir>/<id:03d>.mp3 plus <id:03d>.json {"words": [[word, start, end], ...]}, cached.

Cost estimate (2026-11-24)
- Modal public pricing, read 2026-11-24: L4 US$0.000222 a second, CPU US$0.0000131 a physical core a second,
  memory US$0.00000222 a GiB a second; Starter plan has US$30 free credit a month. The function asks for
  2 cores and 12 GiB, so about US$0.000275 a second while a container runs.
- Real-time factor: measured on the local RTX 3080 in the pilot (same settings, bf16, no torch.compile):
  2.2x (L2: 14.9 s of audio in 32.1 s; L3: 18.7 s in 40.5 s). The L4 has less memory bandwidth, so this
  assumes 3.5x on the L4 (range 2.2x to 3.5x). A CPU test was skipped: the pilot's CPU load ran out of memory and
  a line takes well over 2 minutes there; the local GPU was not touched (Taas Noo renders).
- Monthly volume: 13 long-forms of about 10 min plus 90 Shorts of about 45 s = 7,800 + 4,050 = 11,850 s of
  audio, times 2 takes = 23,700 s generated.
- GPU time: 23,700 x 3.5 = 82,950 s, plus about 129 cold starts (3 parallel chunks per long-form, 1 per Short)
  at about 75 s each (load 4.7 GB from the Volume) = 9,700 s. Total about 92,600 s (25.7 h).
- Money: 92,600 x US$0.000275 = about US$25 a month (about US$17 at the 2.2x best case), plus a few cents of
  image build once. Retakes for failed lines add a little. That is most of the US$30 free credit, which the
  Blender hero shots share; one take per line would roughly halve it.
"""
from __future__ import annotations

from ..config import channel

import difflib
import io
import json
import logging
import re
import subprocess
import tempfile
import unicodedata
import wave
from pathlib import Path

import numpy as np

from .tts import Clip, clean, duration

log = logging.getLogger(__name__)

APP, FUNCTION = "tfs-voice", "narrate"
THRESHOLD = 0.85            # pilot pass mark for Whisper letter match
SEED, TAKES = 19, 2         # seed 19 is the approved voice's design seed; 2 takes per line as in the pilot
RETRY_SEED_STEP = 1000      # a retry round uses seed + 1000
CHUNK = 16                  # lines per Modal call
TOP_DB, PAD_BEFORE, PAD_AFTER = 38, 0.05, 0.12


class NarrationQualityError(RuntimeError):
    """A scene's best take stayed below the letter-match threshold."""


# ---------------------------------------------------------------- numbers as spoken words
_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
        "twelve": "twelfth"}
_NUM = re.compile(r"(?<![\w.])([₱$])?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%|(?:st|nd|rd|th)\b)?"
                  r"(\s+(?:million|billion|trillion)\b)?", re.I)


def _under_1000(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(f"{_ONES[n // 100]} hundred")
        n %= 100
    if n >= 20:
        parts.append(_TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else ""))
    elif n or not parts:
        parts.append(_ONES[n])
    return " ".join(parts)


def cardinal(n: int) -> str:
    """120 -> 'one hundred twenty' (no 'and', as the pilot narrated)."""
    if n == 0:
        return "zero"
    out = []
    for value, name in ((10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= value:
            out.append(f"{cardinal(n // value) if n // value >= 1000 else _under_1000(n // value)} {name}")
            n %= value
    if n:
        out.append(_under_1000(n))
    return " ".join(out)


def year(n: int) -> str:
    """1987 -> 'nineteen eighty-seven', 2001 -> 'two thousand one', 2020 -> 'twenty twenty', 1905 -> 'nineteen oh five'."""
    if 2000 <= n <= 2009:
        return cardinal(n)
    hi, lo = divmod(n, 100)
    if lo == 0:
        return f"{cardinal(hi)} hundred"
    return f"{cardinal(hi)} oh {_ONES[lo]}" if lo < 10 else f"{cardinal(hi)} {cardinal(lo)}"


def _ordinal(words: str) -> str:
    head, last = re.match(r"(.*?)([a-z]+)$", words).groups()
    last = _ORD.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th")
    return head + last


def _say(m: re.Match) -> str:
    cur, num, dec, suffix, scale = m.groups()
    n = int(num.replace(",", ""))
    if suffix and suffix.lower() in ("st", "nd", "rd", "th"):
        return _ordinal(cardinal(n)) + (scale or "")
    plain = not (cur or dec or suffix or "," in num)
    words = year(n) if plain and len(num) == 4 and 1100 <= n <= 2099 else cardinal(n)
    if dec:
        words += " point " + " ".join(_ONES[int(d)] for d in dec[1:])
    if suffix == "%":
        words += " percent"
    if scale:
        words += scale
    if cur:
        unit = {"₱": "peso", "$": "dollar"}[cur]
        words += f" {unit}" + ("" if n == 1 and not dec and not scale else "s")
    return words


def spoken(text: str) -> str:
    """Digits to words the way the narrator should say them; everything else unchanged."""
    return _NUM.sub(_say, text)


def norm(text: str) -> list[str]:
    """Lower-case letter tokens with accents and punctuation dropped, numbers spoken (pilot norm + numbers)."""
    s = unicodedata.normalize("NFKD", spoken(text).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", s.replace("-", " "))


def letter_match(script: str, heard: str) -> float:
    return difflib.SequenceMatcher(None, " ".join(norm(script)), " ".join(norm(heard)), autojunk=False).ratio()


# ---------------------------------------------------------------- audio helpers (no librosa needed)
def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as w:
        sr, ch, width, raw = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"expected 16-bit WAV, got {8 * width}-bit")
    y = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return (y.reshape(-1, ch).mean(axis=1) if ch > 1 else y), sr


def write_wav(path: Path, y: np.ndarray, sr: int) -> None:
    pcm = (np.clip(y, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())


def trim(y: np.ndarray, sr: int, top_db: float = TOP_DB, frame: int = 2048, hop: int = 512) -> np.ndarray:
    """librosa.effects.trim(top_db=38) re-done in numpy, then the pilot's 0.05 s / 0.12 s padding."""
    if not len(y):
        return y
    yp = np.pad(y, frame // 2)
    frames = np.lib.stride_tricks.sliding_window_view(yp, frame)[::hop]
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    if rms.max() <= 0:
        return y[:0]
    loud = np.flatnonzero(20 * np.log10(np.maximum(rms, 1e-10) / rms.max()) > -top_db)
    start, end = int(loud[0]) * hop, min(len(y), (int(loud[-1]) + 1) * hop)
    return y[max(0, start - int(PAD_BEFORE * sr)): min(len(y), end + int(PAD_AFTER * sr))]


# ---------------------------------------------------------------- word times onto the script's words
def map_words(script_text: str, heard: list[tuple[str, float, float]], dur: float) -> list[tuple[str, float, float]]:
    """Whisper's times on the script's own words, so captions keep the script spelling (and its digits)."""
    script_words = script_text.split()
    stok, owner = [], []
    for i, w in enumerate(script_words):
        for t in norm(w):
            stok.append(t); owner.append(i)
    htok, htime = [], []
    for w, s, e in heard:
        toks = norm(w)
        step = (e - s) / max(1, len(toks))
        for j, t in enumerate(toks):                       # "1987" heard -> four tokens sharing its time
            htok.append(t); htime.append((s + j * step, s + (j + 1) * step))
    times: list[tuple[float, float] | None] = [None] * len(script_words)
    for blk in difflib.SequenceMatcher(None, stok, htok, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            i, (s, e) = owner[blk.a + k], htime[blk.b + k]
            times[i] = (s, e) if times[i] is None else (min(times[i][0], s), max(times[i][1], e))
    known = [i for i, t in enumerate(times) if t]
    for i in range(len(times)):                            # interpolate unmatched words (pilot method)
        if times[i] is None:
            lo = max((k for k in known if k < i), default=None)
            hi = min((k for k in known if k > i), default=None)
            t0 = times[lo][1] if lo is not None else 0.0
            t1 = times[hi][0] if hi is not None else dur
            n = (hi if hi is not None else len(times)) - (lo if lo is not None else -1) - 1
            pos = i - (lo if lo is not None else -1)
            step = (t1 - t0) / max(1, n + 1)
            times[i] = (t0 + step * (pos - 1) + 0.02, t0 + step * pos)
    out = []
    for w, (s, e) in zip(script_words, times):
        s = min(max(0.0, s), dur); e = min(max(s, e), dur)
        out.append((w, round(s, 3), round(e, 3)))
    return out


# ---------------------------------------------------------------- outside calls (mocked in tests)
def _transcribe(path: Path) -> tuple[str, list[tuple[str, float, float]]]:
    from ..qa import _whisper, cfg                         # same faster-whisper model and language as the proofreader
    segments, _ = _whisper().transcribe(str(path), language=cfg().get("whisper_language") or None,
                                        word_timestamps=True, beam_size=5)
    words = [(w.word.strip(), w.start, w.end) for seg in segments for w in (seg.words or [])]
    return " ".join(w for w, _, _ in words), words


def _encode(wav: Path, mp3: Path) -> float:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k",
                    "-ar", "44100", str(mp3)], check=True)
    return duration(mp3)


def _function():
    import modal
    return modal.Function.from_name(APP, FUNCTION)


_LIMIT = re.compile(r"spend(?:ing)? limit|billing|credits?\b|quota|payment|budget|usage limit", re.I)


def _modal_error(e: Exception) -> Exception:
    from ..llm import UsageLimitError
    name = type(e).__name__
    if name == "ResourceExhaustedError" or _LIMIT.search(str(e)):
        return UsageLimitError(f"Modal credit or spend limit reached: {str(e)[:200]}")
    if name == "NotFoundError":
        return RuntimeError(f"Modal app {APP!r} is not deployed: run `modal deploy modal_apps/tfs_voice.py` ({e})")
    return e


def _narrate(chunks: list[list[str]], seed: int, takes: int):
    """Yields WAV bytes [line][take] for each chunk, in order, as soon as each chunk is done."""
    try:
        fn = _function()
        if len(chunks) == 1:
            yield fn.remote(chunks[0], seed=seed, takes=takes)
            return
        yield from fn.map(chunks, kwargs={"seed": seed, "takes": takes})
    except Exception as e:                                 # noqa: BLE001 - re-raised as the right type
        err = _modal_error(e)
        if err is e:
            raise
        raise err from e


# ---------------------------------------------------------------- the provider
def score_take(text: str, data: bytes, tmp: Path, tag: str) -> dict:
    y, sr = read_wav(data)
    seg = trim(y, sr)
    path = tmp / f"{tag}.wav"
    write_wav(path, seg, sr)
    heard, words = _transcribe(path)
    return {"path": path, "dur": len(seg) / sr, "heard": heard, "words": words, "match": letter_match(text, heard)}


def _pick(cands: list[dict]) -> dict:
    return max(cands, key=lambda c: c["match"])            # first take wins a tie


def synthesize_scenes(texts: list[str], out_dir: Path, ids: list[int] | None = None, seed: int = SEED,
                      takes: int = TAKES, threshold: float = THRESHOLD, retry_rounds: int = 1) -> list[Clip]:
    """One mp3 per scene from already-cleaned texts, cached as <id:03d>.mp3 + .json like tts.py."""
    ids = list(range(len(texts))) if ids is None else list(ids)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {i: out_dir / f"{sid:03d}.json" for i, sid in zip(range(len(texts)), ids)}
    mp3 = {i: out_dir / f"{sid:03d}.mp3" for i, sid in zip(range(len(texts)), ids)}
    todo = [i for i in range(len(texts)) if not meta[i].exists()]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for i in [i for i in todo if not norm(texts[i])]:   # nothing to say: a short silence, no words
            write_wav(tmp / "silence.wav", np.zeros(int(0.25 * 48000), np.float32), 48000)
            d = _encode(tmp / "silence.wav", mp3[i])
            meta[i].write_text(json.dumps({"words": [], "duration": d, "provider": "voxcpm"}), encoding="utf-8")
        todo = [i for i in todo if norm(texts[i])]
        best: dict[int, dict] = {}
        for rnd in range(retry_rounds + 1):
            if not todo:
                break
            round_seed = seed + RETRY_SEED_STEP * rnd
            lines = [spoken(texts[i]) for i in todo]
            chunks = [lines[k:k + CHUNK] for k in range(0, len(lines), CHUNK)]
            failed = []
            for c, result in enumerate(_narrate(chunks, round_seed, takes)):
                for j, line_takes in enumerate(result):
                    i = todo[c * CHUNK + j]
                    cands = [dict(score_take(texts[i], data, tmp, f"{ids[i]:03d}_r{rnd}_t{k}"), take=k)
                             for k, data in enumerate(line_takes)]
                    pick = _pick(cands)
                    log.info("scene %s: take %s letter match %.3f (others %s)", ids[i], pick["take"], pick["match"],
                             [round(x["match"], 3) for x in cands if x is not pick])
                    if pick["match"] < threshold:
                        if pick["match"] > best.get(i, {}).get("match", -1):
                            best[i] = pick
                        failed.append(i)
                        continue
                    d = _encode(pick["path"], mp3[i])
                    words = map_words(texts[i], pick["words"], pick["dur"])
                    meta[i].write_text(json.dumps({
                        "words": words, "duration": d, "provider": "voxcpm", "seed": round_seed, "take": pick["take"],
                        "letter_match": round(pick["match"], 3), "heard": pick["heard"]}, ensure_ascii=False),
                        encoding="utf-8")
            todo = failed
    if todo:
        detail = ", ".join(f"scene {ids[i]} best {best[i]['match']:.3f} heard {best[i]['heard'][:80]!r}" for i in todo)
        raise NarrationQualityError(f"narration below {threshold} letter match after {retry_rounds + 1} rounds: {detail}")
    clips = []
    for i in range(len(texts)):
        m = json.loads(meta[i].read_text(encoding="utf-8"))
        d = m.get("duration") or duration(mp3[i])
        clips.append(Clip(mp3[i], d, [tuple(w) for w in m["words"]]))
    return clips


def synthesize(scenes: list, out_dir: Path) -> list[Clip]:
    """Drop-in for tts.synthesize: same scene objects (id, text), same cache files."""
    takes = int(channel().get("tts", {}).get("voxcpm", {}).get("takes", 1))
    return synthesize_scenes([clean(s.text, False) for s in scenes], out_dir, ids=[s.id for s in scenes], takes=takes)

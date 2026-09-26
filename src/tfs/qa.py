"""Review team: checks a rendered piece before it is scheduled.

- Proofreader: Whisper (faster-whisper, on the runner's CPU) transcribes the finished video; each scene's words
  are compared with the script, and the `audio_qa` agent judges the scenes that differ (Taglish spelling noise
  vs. real problems: skipped words, wrong numbers or names, garbled audio).
- Visual QA: the `visual_qa` agent looks at a frame from every shot (plus the hook frame, thumbnail or carousel
  slides) next to the cast model sheets and what each frame was meant to show.

Returns a ReviewReport; pipeline.py applies the fixes (new image prompt, re-voice, re-render) and re-reviews.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from . import llm
from .config import ROOT, channel
from .llm import UsageLimitError
from .media.render import ff
from .media.tts import clean, duration
from .models import AudioQA, ReviewReport, Script, ShotList, VisualQA

log = logging.getLogger(__name__)
CAST = sorted((ROOT / "assets" / "characters").glob("*.png"))


def cfg() -> dict:
    return channel()["quality"].get("review", {})


def enabled() -> bool:
    return bool(cfg().get("enabled", True))


# ---------------------------------------------------------------- Proofreader (Whisper)
def words(text: str) -> list[str]:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", s)


def scene_match(expected: str, heard: str) -> float:
    a, b = words(expected), words(heard)
    if not a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


@lru_cache
def _whisper():
    from faster_whisper import WhisperModel
    return WhisperModel(cfg().get("whisper_model", "small"), device="cpu", compute_type="int8")


def proper_nouns(script: Script) -> str:
    """Names and places from the script, given to Whisper as hints so it spells a correctly-read name correctly
    (otherwise Whisper's own mishearing of Filipino names looks like a narrator error)."""
    names = set()
    for scene in script.scenes:
        for sentence in re.split(r"(?<=[.!?])\s+", clean(scene.text, False)):
            for word in sentence.split()[1:]:                    # skip the capitalised first word
                word = word.strip(",.;:!?\"'()“”‘’")
                if word[:1].isupper():
                    names.add(word)
    return ", ".join(sorted(names))[:600]


def transcribe(media: Path, hints: str = "") -> list[tuple[str, float, float]]:
    segments, _ = _whisper().transcribe(str(media), language=cfg().get("whisper_language") or None,
                                        word_timestamps=True, beam_size=5, hotwords=hints or None)
    return [(w.word.strip(), w.start, w.end) for seg in segments for w in (seg.words or [])]


def split_by_scene(heard: list[tuple[str, float, float]], bounds: list[float]) -> list[str]:
    """Assign each transcribed word to the scene whose time span holds its midpoint."""
    out = [[] for _ in range(len(bounds) - 1)]
    for word, start, end in heard:
        mid = (start + end) / 2
        for i in range(len(out)):
            if bounds[i] - 0.15 <= mid < bounds[i + 1] - 0.15 or (i == len(out) - 1 and mid >= bounds[i] - 0.15):
                out[i].append(word)
                break
    return [" ".join(w) for w in out]


def proofread(script: Script, starts: list[float], video: Path) -> tuple[dict[str, str], list[str], str, bool]:
    total = duration(video)
    heard = split_by_scene(transcribe(video, proper_nouns(script)), starts + [total])
    rows = []
    for scene, text in zip(script.scenes, heard):
        expected = clean(scene.text, keep_audio_tags=False)
        rows.append({"scene_id": scene.id, "speaker": scene.speaker, "expected": expected, "heard": text,
                     "match": round(scene_match(expected, text), 2)})
    flagged = [r for r in rows if r["match"] < cfg().get("min_scene_match", 0.8)]
    avg = sum(r["match"] for r in rows) / max(len(rows), 1)
    if not flagged:
        return {}, [], f"narration matches the script ({avg:.0%} word match)", False
    verdict = llm.structured("audio_qa", "Scenes whose transcription differs from the script:\n\n"
                             + json.dumps(flagged, ensure_ascii=False, indent=1), AudioQA)
    redo = {str(v.scene_id): v.tts_text for v in verdict.scenes if not v.ok}
    warnings = [f"voice, scene {v.scene_id} ({v.severity}): {v.problem}" for v in verdict.scenes if not v.ok]
    major = any(not v.ok and v.severity == "major" for v in verdict.scenes)
    return redo, warnings, f"{verdict.summary} ({avg:.0%} word match)", major


# ---------------------------------------------------------------- Visual QA
def grab(video: Path, t: float, out: Path) -> Path:
    ff(["-ss", f"{max(t, 0):.2f}", "-i", str(video.resolve()), "-frames:v", "1", "-vf", "scale=540:-2",
        "-q:v", "3", out.name], cwd=out.parent)
    return out


def _look(frames: list[tuple[str, Path, dict]], context: str) -> tuple[list, int, int, list[str]]:
    """Visual QA over frames in batches. Returns (verdicts, appeal, hook score, notes)."""
    per_call = cfg().get("frames_per_call", 12)
    verdicts, appeals, hooks, notes = [], [], [], []
    for i in range(0, len(frames), per_call):
        batch = frames[i:i + per_call]
        brief = [{"frame": label, "file": path.name, **info} for label, path, info in batch]
        user = (f"{context}\n\nCast model sheets: {', '.join(p.name for p in CAST)}.\n"
                f"Frames to review (answer once per frame, echoing its `frame` label):\n"
                + json.dumps(brief, ensure_ascii=False, indent=1))
        qa = llm.structured_with_images("visual_qa", user, [*CAST, *[p for _, p, _ in batch]], VisualQA)
        verdicts += qa.frames
        appeals.append(qa.appeal_score)
        if any(label == "hook" for label, _, _ in batch):
            hooks.append(qa.hook_frame_score)
        notes += qa.notes
    appeal = round(sum(appeals) / len(appeals)) if appeals else 0
    return verdicts, appeal, (hooks[0] if hooks else appeal), notes


def review_video(kind: str, d: Path, script: Script, shots: ShotList, starts: list[float], video: Path,
                 thumbnail: Path | None, hook_text: str, reused: set[int] | None = None) -> ReviewReport:
    frame_dir = d / "qa_frames"
    frame_dir.mkdir(exist_ok=True)
    total = duration(video)
    bounds = starts + [total]
    by_scene = {s.scene_id: s for s in shots.shots}
    source = {s.scene_id: (s.reuse_of_scene if s.kind == "reuse" else s.scene_id) for s in shots.shots}

    picks = list(range(len(script.scenes)))
    cap = cfg().get("max_frames", 48)
    if len(picks) > cap:
        step = len(picks) / cap
        picks = sorted({int(i * step) for i in range(cap)})
    frames: list[tuple[str, Path, dict]] = []
    if kind == "vertical":
        frames.append(("hook", grab(video, 0.4, frame_dir / "hook.jpg"),
                       {"meant_to_show": f"opening frame with the on-screen hook: {hook_text}"}))
    for i in picks:
        scene = script.scenes[i]
        shot = by_scene.get(scene.id)
        info = {"line": clean(scene.text, False)[:220]}
        if shot:
            info |= {"type": shot.kind if shot.kind != "card" else f"card:{shot.card_type}",
                     "style": shot.style if shot.kind != "card" else "",
                     "meant_to_show": (shot.image_prompt or f"{shot.card_title} {shot.card_lines}")[:350]}
        if (shot and shot.kind == "reuse") or scene.id in (reused or set()):
            info["reused"] = True
        t = (bounds[i] + bounds[i + 1]) / 2
        frames.append((f"scene {scene.id}", grab(video, t, frame_dir / f"scene{scene.id:03d}.jpg"), info))
    if thumbnail and thumbnail.exists():
        frames.append(("thumbnail", thumbnail, {"meant_to_show": "YouTube thumbnail (16:9); must read at phone size"}))

    fmt = "9:16 vertical (Shorts/Reels/TikTok) with burned captions" if kind == "vertical" else \
        "16:9 YouTube long-form"
    verdicts, appeal, hook_score, notes = _look(frames, f"Format: {fmt}.")

    redo_images, warnings = {}, list(notes)
    for v in verdicts:
        for p in v.problems:
            warnings.append(f"{v.frame}: {p}")
        if not v.blocking:
            continue
        if v.frame == "thumbnail" and v.fix_prompt:
            redo_images["thumbnail"] = v.fix_prompt
            continue
        m = re.search(r"\d+", v.frame)
        scene_id = int(m.group()) if m and v.frame.startswith("scene") else (script.scenes[0].id if v.frame == "hook"
                                                                             else None)
        shot = by_scene.get(scene_id) if scene_id is not None else None
        if shot and shot.kind != "card" and v.fix_prompt:
            redo_images[str(source.get(scene_id, scene_id))] = v.fix_prompt
        else:
            warnings.append(f"{v.frame}: blocking but not auto-fixable (card/caption) — {'; '.join(v.problems)}")

    redo_audio, voice_warnings, voice_summary, major = proofread(script, starts, video)
    warnings += voice_warnings
    return ReviewReport(passed=not redo_images and not redo_audio, major_audio=major, redo_images=redo_images,
                        redo_audio=redo_audio,
                        warnings=warnings, appeal=appeal, hook_frame=hook_score,
                        summary=f"visual appeal {appeal}/10, hook frame {hook_score}/10; {voice_summary}")


def review_slides(slides: list[Path], prompts: list[str]) -> ReviewReport:
    frames = [(f"slide {i}", p, {"meant_to_show": (prompts[i] if i < len(prompts) else "")[:350]})
              for i, p in enumerate(slides)]
    verdicts, appeal, hook_score, notes = _look(
        frames, "Format: Instagram/Facebook carousel, 4:5 slides; slide 0 is the cover (it is the hook frame).")
    redo, warnings = {}, list(notes)
    for v in verdicts:
        warnings += [f"{v.frame}: {p}" for p in v.problems]
        m = re.search(r"\d+", v.frame)
        if v.blocking and m:
            if v.fix_prompt and int(m.group()) < len(prompts) and prompts[int(m.group())]:
                redo[m.group()] = v.fix_prompt
            else:
                warnings.append(f"{v.frame}: blocking but not auto-fixable (text layout) — {'; '.join(v.problems)}")
    return ReviewReport(passed=not redo, redo_images=redo, redo_audio={}, warnings=warnings, appeal=appeal,
                        hook_frame=hook_score, summary=f"visual appeal {appeal}/10, cover {hook_score}/10")


def safe(fn, *args) -> ReviewReport:
    """A broken reviewer must never stop the channel: report and let the piece through (usage limits excepted)."""
    try:
        return fn(*args)
    except UsageLimitError:
        raise
    except Exception as e:
        log.exception("review failed")
        return ReviewReport(passed=True, redo_images={}, redo_audio={}, warnings=[f"review unavailable: {e}"],
                            appeal=0, hook_frame=0, summary="review unavailable")

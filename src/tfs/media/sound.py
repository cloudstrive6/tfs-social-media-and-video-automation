"""Music and sound effects.

Library: instrumental music beds by mood + a kit of sound effects, generated ONCE with ElevenLabs (paid plans
allow online commercial use) by `tfs build-sound-library`, kept in the private R2 state under library/ (never
in the public repo) and pulled at the start of every run.

Per video:
- the Sound Designer agent picks a music mood per stretch of the story and a few accent effects on script beats
  (anchored to a word, so they land exactly when it's said);
- code adds the effects that belong to the animations (card whoosh, stat pop + count ticks, map pins, stamp);
- `mix` ducks the music under the narration (sidechain) and lays the effects in; render.py loudness-normalises.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests

from ..config import channel, data_dir, require_env

log = logging.getLogger(__name__)
API = "https://api.elevenlabs.io/v1"

MUSIC = {
    "curious": "Curious light documentary underscore, plucked marimba and celesta, soft synth pad, gentle "
               "questioning feel, 95 BPM, instrumental, loop-friendly",
    "wonder": "Sense-of-wonder underscore, shimmering strings, soft choir pad without words, glockenspiel, "
              "slow build, 78 BPM, instrumental",
    "investigative": "Tense investigative documentary underscore, pulsing low synth bass, soft ticking percussion, "
                     "muted piano motif, dark and curious, 92 BPM, instrumental, steady, loop-friendly",
    "satire": "Playful satirical underscore, pizzicato strings, bassoon, light brushed snare, mischievous and "
              "sarcastic like a comedic history explainer, 110 BPM, instrumental",
    "somber": "Somber reflective underscore, solo piano with soft sustained strings, slow and restrained, "
              "70 BPM, instrumental",
    "hopeful": "Hopeful uplifting underscore, fingerpicked acoustic guitar, warm strings, light percussion, "
               "100 BPM, instrumental",
    "historical": "Understated cinematic historical underscore with Filipino colour: rondalla bandurria and "
                  "octavina melody over low strings and frame drum, 85 BPM, instrumental",
    "kulintang": "Filipino kulintang gong ensemble over modern cinematic drums and bass, mysterious and "
                 "rhythmic, 96 BPM, instrumental",
    "suspense": "Suspense build underscore, rising strings, heartbeat-like low kick, slow tension, 80 BPM, "
                "instrumental",
    "archival": "Nostalgic archival underscore, warm vintage piano and soft brass, gentle vinyl crackle, "
                "1960s newsreel feel, 90 BPM, instrumental",
    "news": "Urgent news-magazine underscore, driving synth arpeggio, tight modern drums, punchy, 120 BPM, "
            "instrumental",
    "lofi": "Lo-fi explainer beat, mellow electric piano, soft boom-bap drums, warm and chill, 85 BPM, instrumental",
}
SFX = {  # key: (prompt, seconds)
    "whoosh_soft": ("soft short air whoosh transition, clean, no reverb tail", 0.8),
    "whoosh_hard": ("fast punchy whoosh swipe transition", 0.9),
    "pop": ("bright cartoon pop, UI element appearing", 0.5),
    "click": ("crisp UI click", 0.5),
    "ding": ("single bright notification ding", 1.0),
    "cash_register": ("old cash register cha-ching", 1.5),
    "coins": ("handful of coins dropping on a table", 1.4),
    "gavel": ("single wooden judge gavel strike in a courtroom", 1.2),
    "stamp": ("heavy rubber stamp slammed on paper, thud", 0.7),
    "paper_slide": ("sheet of paper sliding onto a desk", 0.9),
    "typewriter": ("short burst of vintage typewriter keys with a bell", 1.8),
    "record_scratch": ("vinyl record scratch, comedic stop", 0.9),
    "rimshot": ("drum rimshot ba-dum-tss joke punchline", 1.2),
    "boing": ("cartoon boing spring", 0.9),
    "heartbeat": ("two slow heavy heartbeats, tense", 1.8),
    "impact": ("deep cinematic boom impact hit", 1.5),
    "clock_tick": ("clock ticking, four ticks", 2.0),
    "riser": ("short tension riser swelling up", 2.5),
    "crowd_murmur": ("indoor crowd murmur, hall of people talking quietly", 3.0),
    "camera_shutter": ("camera shutter click", 0.6),
    "map_pin": ("soft map pin drop plop", 0.5),
    "count_tick": ("tiny digital counter tick", 0.5),
    "error_buzz": ("game show wrong answer buzzer", 0.8),
    "gasp": ("small crowd gasping in surprise", 1.4),
    "applause": ("short polite applause", 2.0),
}
MUSIC_DB, SFX_DB = -15.0, -9.0          # relative to the narration, before ducking and loudnorm


def library_dir() -> Path:
    return data_dir() / "library"


def available() -> tuple[list[str], list[str]]:
    lib = library_dir()
    music = sorted(p.stem for p in (lib / "music").glob("*.mp3"))
    sfx = sorted(p.stem for p in (lib / "sfx").glob("*.mp3"))
    return music, sfx


# ---------------------------------------------------------------- one-time library build
def build_library(only_missing: bool = True) -> list[str]:
    cfg = channel().get("sound", {})
    headers = {"xi-api-key": require_env("ELEVENLABS_API_KEY")}
    lib = library_dir()
    (lib / "music").mkdir(parents=True, exist_ok=True)
    (lib / "sfx").mkdir(parents=True, exist_ok=True)
    made = []
    for key, (prompt, seconds) in SFX.items():
        out = lib / "sfx" / f"{key}.mp3"
        if only_missing and out.exists():
            continue
        r = requests.post(f"{API}/sound-generation", headers=headers, timeout=180,
                          params={"output_format": "mp3_44100_128"},
                          json={"text": prompt, "duration_seconds": max(0.5, seconds), "prompt_influence": 0.5})
        if r.status_code >= 400:
            raise RuntimeError(f"ElevenLabs sound-generation {r.status_code}: {r.text[:300]}")
        out.write_bytes(r.content)
        made.append(str(out))
    for key, prompt in MUSIC.items():
        out = lib / "music" / f"{key}.mp3"
        if only_missing and out.exists():
            continue
        r = requests.post(f"{API}/music", headers=headers, timeout=600,
                          params={"output_format": "mp3_44100_128"},
                          json={"prompt": prompt, "music_length_ms": int(cfg.get("music_seconds", 120) * 1000),
                                "model_id": cfg.get("music_model", "music_v1"), "force_instrumental": True})
        if r.status_code >= 400:
            raise RuntimeError(f"ElevenLabs music {r.status_code}: {r.text[:300]}")
        out.write_bytes(r.content)
        made.append(str(out))
    return made


# ---------------------------------------------------------------- per-video timeline
@dataclass
class Event:
    at: float          # seconds from the start of the video
    path: Path
    gain_db: float = 0.0


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def _word_time(clip, anchor: str) -> float | None:
    target = _norm(anchor)
    for word, start, _ in clip.words:
        if target and _norm(word).startswith(target[:max(3, len(target) - 2)]):
            return start
    return None


def timeline(plan, shots, clips, scene_ids: list[int], starts: list[float], total: float, kind: str):
    """(music segments [(start, end, path)], sfx events) for one video. `scene_ids[i]` is clip i's scene."""
    music, sfx = available()
    lib = library_dir()
    segments = []
    if music:
        cues = sorted(((c.from_scene, c.mood) for c in (plan.music if plan else []) if c.mood in music),
                      key=lambda c: c[0]) or [(0, "investigative" if "investigative" in music else music[0])]
        index = {sc: i for i, sc in enumerate(scene_ids)}
        times = [(starts[index.get(sc, 0)] if index.get(sc, 0) < len(starts) else 0.0, mood) for sc, mood in cues]
        times[0] = (0.0, times[0][1])
        for k, (t0, mood) in enumerate(times):
            t1 = times[k + 1][0] if k + 1 < len(times) else total
            if t1 - t0 > 1.5:
                segments.append((t0, t1, lib / "music" / f"{mood}.mp3"))

    events: list[Event] = []
    have = set(sfx)

    def add(at: float, key: str, gain: float = 0.0):
        if key in have and 0 <= at < total:
            events.append(Event(at, lib / "sfx" / f"{key}.mp3", gain))

    bounds = starts + [total]
    for i, shot in enumerate(shots):
        t0, dur = bounds[i], bounds[i + 1] - bounds[i]
        card = getattr(shot, "card", None)
        if card:
            ctype = card["card_type"]
            play = min(dur, 2.5 if ctype != "map" else 3.5)
            add(t0, "whoosh_soft", -2)
            if ctype == "stat":
                add(t0 + 0.08, "pop")
                for k in range(5):
                    add(t0 + play * (0.05 + 0.08 * k), "count_tick", -8)
            elif ctype == "bars":
                for k in range(min(5, len(card["lines"]))):
                    add(t0 + play * (0.12 + 0.12 * k), "pop", -4)
            elif ctype == "timeline":
                for k in range(min(5, len(card["lines"]))):
                    add(t0 + play * (0.1 + 0.6 * (k + 0.5) / max(1, len(card["lines"]))), "click", -3)
            elif ctype == "document":
                add(t0 + 0.05, "paper_slide", -3)
                add(t0 + play * 0.66, "stamp")
            elif ctype == "quote":
                add(t0 + 0.1, "typewriter", -10)
            elif ctype == "map":
                for k in range(min(5, len(card["lines"]))):
                    add(t0 + play * 0.9 * (0.5 + 0.06 * k), "map_pin", -2)
        elif kind == "vertical" and i > 0 and not getattr(shots[i - 1], "card", None):
            add(t0, "whoosh_soft", -12)                              # barely-there swish on cuts

    if plan:
        by_scene = {sid: (clip, start) for sid, clip, start in zip(scene_ids, clips, starts)}
        spacing = 5.0 if kind == "vertical" else 8.0
        placed: list[float] = []
        for cue in plan.sfx:
            if cue.sound not in have or cue.scene_id not in by_scene:
                continue
            clip, start = by_scene[cue.scene_id]
            t = _word_time(clip, cue.anchor_word)
            at = start + (t if t is not None else 0.0)
            if all(abs(at - p) >= spacing for p in placed):            # never a wall of effects
                placed.append(at)
                add(at, cue.sound)
    return segments, sorted(events, key=lambda e: e.at)


# ---------------------------------------------------------------- mixing
def mix(narration: Path, total: float, segments, events: list[Event], work: Path) -> Path:
    """Narration + ducked music + effects -> mix.wav (loudness is normalised later by render)."""
    inputs = ["-i", narration.name]
    filters = ["[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voice][key]"]
    music_labels = []
    n = 1
    for k, (t0, t1, path) in enumerate(segments):
        inputs += ["-stream_loop", "-1", "-i", str(path.resolve())]
        dur = t1 - t0
        fade = min(1.5, dur / 3)
        filters.append(f"[{n}:a]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
                       f"afade=t=in:d={fade:.2f},afade=t=out:st={dur - fade:.3f}:d={fade:.2f},"
                       f"adelay={int(t0 * 1000)}:all=1,volume={MUSIC_DB}dB[m{k}]")
        music_labels.append(f"[m{k}]")
        n += 1
    outs = ["[voice]"]
    if music_labels:
        filters.append("".join(music_labels) + f"amix=inputs={len(music_labels)}:normalize=0:duration=longest[bed]")
        filters.append("[bed][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=450[ducked]")
        outs.append("[ducked]")
    else:
        filters.append("[key]anullsink")
    for k, e in enumerate(events):
        inputs += ["-i", str(e.path.resolve())]
        filters.append(f"[{n}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={int(e.at * 1000)}:all=1,"
                       f"volume={SFX_DB + e.gain_db}dB[s{k}]")
        outs.append(f"[s{k}]")
        n += 1
    filters.append("".join(outs) + f"amix=inputs={len(outs)}:normalize=0:duration=first[mix]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
           "-map", "[mix]", "-t", f"{total:.3f}", "-ar", "48000", "mix.wav"]
    res = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(f"ffmpeg (mix) failed: {res.stderr[-1500:]}")
    return work / "mix.wav"


def describe_library() -> str:
    music, sfx = available()
    return json.dumps({"music_moods": music, "sound_effects": sfx})

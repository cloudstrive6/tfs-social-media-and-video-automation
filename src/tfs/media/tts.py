"""Narrator: per-scene speech with word timings (ElevenLabs) or estimated timings (Fish Audio)."""
from __future__ import annotations

import base64
import logging
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests

from ..config import channel, env, require_env

log = logging.getLogger(__name__)
V3_TAGS = {"laugh", "laughs", "whisper", "whispers", "sigh", "sighs", "sarcastic", "excited", "curious"}


@dataclass
class Clip:
    path: Path
    duration: float
    words: list[tuple[str, float, float]]   # (word, start, end) relative to the clip


def clean(text: str, keep_audio_tags: bool) -> str:
    """Strip writer markup the narrator must not read out loud."""
    text = re.sub(r"\[S\d+(?:,\s*S\d+)*\]", "", text)                 # source tags
    text = re.sub(r"\[CARD:[^\]]*\]", "", text, flags=re.I)            # on-screen card cues
    text = re.sub(r"\[pause\]", " ... ", text, flags=re.I)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)                        # *emphasis*

    def tag(m: re.Match) -> str:
        return m.group(0) if keep_audio_tags and m.group(1).lower() in V3_TAGS else ""
    text = re.sub(r"\[([a-zA-Z ]+)\]", tag, text)
    return re.sub(r"\s+", " ", text).strip()


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def _voice_for(speaker: str) -> str:
    key = re.sub(r"\W+", "_", speaker.strip().upper())
    return env(f"ELEVENLABS_VOICE_{key}") or require_env("ELEVENLABS_VOICE_ID")


def _words_from_alignment(al: dict) -> list[tuple[str, float, float]]:
    words, cur, start = [], "", None
    for ch, s, e in zip(al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]):
        if ch.isspace():
            if cur:
                words.append((cur, start, last_end))
            cur, start = "", None
            continue
        if start is None:
            start = s
        cur += ch
        last_end = e
    if cur:
        words.append((cur, start, last_end))
    return words


def _elevenlabs(text: str, speaker: str, out: Path, prev_text: str, next_text: str) -> list:
    cfg = channel()["tts"]["elevenlabs"]
    body = {
        "text": text,
        "model_id": cfg["model_id"],
        "voice_settings": {"stability": cfg["stability"], "similarity_boost": cfg["similarity_boost"],
                           "style": cfg["style"], "use_speaker_boost": True, "speed": cfg["speed"]},
    }
    # Josh is a Filipino voice; telling the model the text is Filipino ("fil") keeps names like "Contemplacion"
    # and Tagalog words from being read the English way. multilingual_v2 rejects the field, so never send it there.
    if cfg.get("language_code") and "multilingual_v2" not in cfg["model_id"]:
        body["language_code"] = cfg["language_code"]
    if cfg["model_id"] != "eleven_v3":           # request stitching keeps prosody continuous across scenes
        body |= {"previous_text": prev_text[-300:], "next_text": next_text[:300]}
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{_voice_for(speaker)}/with-timestamps"
    headers = {"xi-api-key": require_env("ELEVENLABS_API_KEY")}
    r = requests.post(url, params={"output_format": "mp3_44100_128"}, headers=headers, json=body, timeout=180)
    if r.status_code == 400 and "language_code" in body:     # a language setting must never stop a video
        log.warning("ElevenLabs rejected language_code=%s (%s); retrying without it",
                    body["language_code"], r.text[:300])
        body.pop("language_code")
        r = requests.post(url, params={"output_format": "mp3_44100_128"}, headers=headers, json=body, timeout=180)
    if r.status_code >= 400:
        if "quota_exceeded" in r.text:              # out of credits: wait for a top-up instead of failing items
            from ..llm import UsageLimitError
            raise UsageLimitError(f"ElevenLabs credits exhausted: {r.text[:200]}")
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:500]}")
    data = r.json()
    out.write_bytes(base64.b64decode(data["audio_base64"]))
    return _words_from_alignment(data["alignment"])


def _fishaudio(text: str, out: Path) -> list:
    cfg = channel()["tts"]["fishaudio"]
    r = requests.post("https://api.fish.audio/v1/tts", timeout=180,
                      headers={"Authorization": f"Bearer {require_env('FISH_AUDIO_API_KEY')}", "model": cfg["model"]},
                      json={"text": text, "reference_id": env("FISH_AUDIO_VOICE_ID") or cfg["reference_id"],
                            "format": "mp3", "latency": "normal"})
    r.raise_for_status()
    out.write_bytes(r.content)
    # No timestamps from this API: spread words proportionally to their length.
    d, tokens = duration(out), text.split()
    total = sum(len(t) for t in tokens) or 1
    words, t = [], 0.0
    for tok in tokens:
        span = d * len(tok) / total
        words.append((tok, t, t + span))
        t += span
    return words


def synthesize(scenes: list, out_dir: Path) -> list[Clip]:
    """One mp3 per scene (enables per-character voices and exact scene timing). Cached on disk."""
    provider = channel()["tts"]["provider"]
    keep_tags = channel()["tts"]["elevenlabs"]["model_id"] == "eleven_v3"
    texts = [clean(s.text, keep_tags) for s in scenes]
    out_dir.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, (scene, text) in enumerate(zip(scenes, texts)):
        path, meta = out_dir / f"{scene.id:03d}.mp3", out_dir / f"{scene.id:03d}.json"
        if not meta.exists():
            if provider == "fishaudio":
                words = _fishaudio(text, path)
            else:
                words = _elevenlabs(text, scene.speaker, path,
                                    " ".join(texts[max(0, i - 2):i]), " ".join(texts[i + 1:i + 3]))
            meta.write_text(json.dumps({"words": words}), encoding="utf-8")
        words = [tuple(w) for w in json.loads(meta.read_text(encoding="utf-8"))["words"]]
        clips.append(Clip(path, duration(path), words))
    return clips

"""Narrator: one clip per scene with word timings, from the VoxCPM2 narrator (tts_voxcpm.py: the local GPU worker
first, Modal after the deadline)."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Clip:
    path: Path
    duration: float
    words: list[tuple[str, float, float]]   # (word, start, end) relative to the clip


def clean(text: str, keep_audio_tags: bool = False) -> str:
    """Strip writer markup the narrator must not read out loud (source tags, [pause], *emphasis*, any [tag]).
    `keep_audio_tags` is accepted for old callers and ignored: the narrator reads no audio tags."""
    text = re.sub(r"\[S\d+(?:,\s*S\d+)*\]", "", text)                 # source tags
    text = re.sub(r"\[pause\]", " ... ", text, flags=re.I)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)                        # *emphasis*
    text = re.sub(r"\[[^\]]*\]", "", text)                             # any other bracketed cue
    return re.sub(r"\s+", " ", text).strip()


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def synthesize(scenes: list, out_dir: Path, item: str | None = None, deadline=None) -> list[Clip]:
    """One clip per scene, cached on disk. `item` and `deadline` let the local GPU worker narrate first."""
    from . import tts_voxcpm
    return tts_voxcpm.synthesize(scenes, out_dir, item=item, deadline=deadline)

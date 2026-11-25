"""Small render helpers shared by the atlas pipeline and the review team: ffmpeg, the .srt sidecar and YouTube
chapters. The picture itself is drawn by the atlas engine (atlas.py)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .tts import Clip


def ff(args: list[str], cwd: Path) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(f"ffmpeg failed: {res.stderr[-2000:]}")


def srt(clips: list[Clip], starts: list[float], out: Path) -> None:
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    lines, n = [], 1
    for clip, start in zip(clips, starts):
        for i in range(0, len(clip.words), 8):
            chunk = clip.words[i:i + 8]
            lines.append(f"{n}\n{ts(start + chunk[0][1])} --> {ts(start + chunk[-1][2])}\n"
                         f"{' '.join(w for w, _, _ in chunk)}\n")
            n += 1
    out.write_text("\n".join(lines), encoding="utf-8")


def chapters(scenes: list, starts: list[float]) -> list[tuple[float, str]]:
    out, last = [], None
    for scene, start in zip(scenes, starts):
        if scene.chapter != last:
            out.append((0.0 if not out else start, scene.chapter))
            last = scene.chapter
    return out

"""Video Editor: Ken-Burns shots + narration + music (+ burned captions for verticals) with FFmpeg.

All ffmpeg calls run with cwd=work_dir and relative file names, which sidesteps Windows
drive-letter escaping inside filter graphs.
"""
from __future__ import annotations

import logging
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import ROOT, channel
from .design import font, font_path
from .tts import Clip, duration

log = logging.getLogger(__name__)
GAP = 0.25  # seconds of air between scenes


@dataclass
class Shot:
    image: Path
    motion: str
    card: dict | None = None      # {"card_type", "title", "lines"}: rendered as an animated infographic


def ff(args: list[str], cwd: Path) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(f"ffmpeg failed: {res.stderr[-2000:]}")


def _zoompan(motion: str, frames: int) -> tuple[str, str, str]:
    f = max(frames - 1, 1)
    center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    return {
        "push_in": (f"1+0.12*on/{f}", center_x, center_y),
        "pull_out": (f"1.12-0.12*on/{f}", center_x, center_y),
        "pan_left": ("1.12", f"(iw-iw/zoom)*(1-on/{f})", center_y),
        "pan_right": ("1.12", f"(iw-iw/zoom)*on/{f}", center_y),
        "shake": ("1.08", f"{center_x}+sin(on*2.1)*14", f"{center_y}+cos(on*1.7)*10"),
        "static": ("1.0", center_x, center_y),
        "card": (f"1+0.03*on/{f}", center_x, center_y),   # gentle: never crops text off a card
    }.get(motion, (f"1+0.08*on/{f}", center_x, center_y))


def shot_clip(image: Path, frames: int, motion: str, size: tuple[int, int], fps: int, out: Path) -> None:
    w, h = size
    z, x, y = _zoompan(motion, frames)
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},format=yuv420p")
    ff(["-i", str(image.resolve()), "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "18", "-r", str(fps), out.name], cwd=out.parent)


def narration(clips: list[Clip], work: Path) -> tuple[Path, list[float]]:
    """Concatenate scene clips with a short gap. Returns (wav, scene start times)."""
    parts, starts, t = [], [], 0.0
    for i, clip in enumerate(clips):
        part = work / f"n{i:03d}.wav"
        ff(["-i", str(clip.path.resolve()), "-af", f"apad=pad_dur={GAP}", "-ar", "44100", "-ac", "2", part.name],
           cwd=work)
        starts.append(t)
        t += duration(part)
        parts.append(part)
    (work / "narration.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    ff(["-f", "concat", "-safe", "0", "-i", "narration.txt", "-c", "copy", "narration.wav"], cwd=work)
    return work / "narration.wav", starts


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


SENTENCE_END = (".", "?", "!", "…", "...")
CLAUSE_END = (",", ";", ":", "—", "–")
MAX_WORDS, MAX_CHARS = 3, 20
# never leave these dangling at the end of a caption group ("NG LABING-ANIM NA", "SA")
PARTICLES = {"ng", "sa", "ang", "na", "at", "ay", "mga", "si", "ni", "kay", "nang", "para", "kung", "pag", "o",
             "the", "of", "a", "an", "to", "and", "in", "on", "for", "at", "by", "with"}


def caption_chunks(words: list[tuple[str, float, float]]) -> list[list[tuple[str, float, float]]]:
    """Group spoken words into on-screen caption groups: at most 3 words / 20 characters, and a group always ends
    at the end of a sentence or clause, so the next sentence never shares the screen with the last one."""
    chunks, cur = [], []
    for w in words:
        if cur and len(" ".join(x[0] for x in cur + [w])) > MAX_CHARS:
            chunks.append(cur)                       # close before a word that would overflow the group
            cur = []
        cur.append(w)
        token = w[0].rstrip("\"'”’)")
        if token.endswith(SENTENCE_END + CLAUSE_END):
            chunks.append(cur)
            cur = []
        elif len(cur) >= MAX_WORDS:
            carry = []
            while len(cur) > 1 and (cur[-1][0].lower().strip("\"'“”‘’") in PARTICLES
                                    or cur[-1][0][:1] in "\"“‘'"):
                carry.insert(0, cur.pop())     # a particle or an opening quote starts the next group
            chunks.append(cur)
            cur = carry
    if cur:
        chunks.append(cur)
    return chunks


def _ass_escape(text: str) -> str:
    return text.upper().replace("{", "").replace("}", "").replace("\\", "")


def captions_ass(clips: list[Clip], starts: list[float], size: tuple[int, int], hook_text: str, out: Path) -> None:
    """Vertical captions: 1–3 word groups, the word being spoken highlighted (karaoke), each group shrunk to fit
    inside the frame, plus the on-screen hook line for the first 3 seconds."""
    w, h = size
    family = "Impact" if not font_path("display") or "impact" in font_path("display").lower() else \
        Path(font_path("display")).stem.split("-")[0]
    base = int(h * 0.1)
    margin = int(w * 0.07)
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Cap,{f},{cs},&H00FFFFFF,&H0016D1FC,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,10,4,2,{m},{m},{mv},1\n"
        "Style: Hook,{f},{hs},&H0016D1FC,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,9,3,8,{m},{m},{mt},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    ).format(w=w, h=h, f=family, cs=base, hs=int(h * 0.085), mv=int(h * 0.3), mt=int(h * 0.12), m=margin)
    events = []
    if hook_text:
        hook = _ass_escape(hook_text)
        hsize = _fit_size(hook, int(h * 0.085), (w - 2 * margin) * 2)       # the hook may wrap to 2 lines
        events.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(3.0)},Hook,,0,0,0,,{{\\fs{hsize}}}{hook}")
    yellow, white = "&H0016D1FC&", "&H00FFFFFF&"
    for clip, start in zip(clips, starts):
        groups = caption_chunks(clip.words)
        for g, chunk in enumerate(groups):
            texts = [_ass_escape(wd) for wd, _, _ in chunk]
            size_fs = _fit_size(" ".join(texts), base, w - 2 * margin, grow=1.1)
            nxt = groups[g + 1][0][1] if g + 1 < len(groups) else chunk[-1][2] + 0.25
            for k, (_, ws, we) in enumerate(chunk):
                t0 = start + (chunk[0][1] if k == 0 else ws)
                t1 = start + (chunk[k + 1][1] if k + 1 < len(chunk) else min(nxt, chunk[-1][2] + 0.25))
                if t1 <= t0:
                    continue
                parts = [(f"{{\\c{yellow}\\fscx110\\fscy110}}{t}{{\\c{white}\\fscx100\\fscy100}}" if i == k else t)
                         for i, t in enumerate(texts)]
                events.append(f"Dialogue: 0,{_ass_time(t0)},{_ass_time(t1)},Cap,,0,0,0,,{{\\fs{size_fs}}}"
                              + " ".join(parts))
    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def _fit_size(text: str, size: int, max_width: float, grow: float = 1.0) -> int:
    """Largest ASS font size (<= size) at which `text` (highlighted word scaled by `grow`) fits the width.
    libass treats Fontsize as the font's full line height (ascent+descent), so glyphs come out smaller than
    PIL's em-based size by size/(ascent+descent); measure with that scale so the fit is exact, not timid."""
    while size > 24:
        f = font("display", size)
        ascent, descent = f.getmetrics()
        if f.getlength(text) * size / (ascent + descent) * grow + size * 0.3 <= max_width:
            return size
        size -= 2
    return size


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


def _music() -> Path | None:
    folder = ROOT / channel()["video"]["music_dir"]
    tracks = [p for p in folder.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a")] if folder.exists() else []
    return random.choice(tracks) if tracks else None


def render(shots: list[Shot], clips: list[Clip], kind: str, work: Path, out: Path,
           hook_text: str = "") -> tuple[Path, list[float]]:
    """Returns the final mp4 and each scene's start time (for chapters)."""
    vcfg = channel()["video"]["long_form" if kind == "long_form" else "vertical"]
    size, fps = (vcfg["width"], vcfg["height"]), vcfg["fps"]
    work.mkdir(parents=True, exist_ok=True)

    wav, starts = narration(clips, work)
    total = duration(wav)
    bounds = starts + [total]

    # one Ken-Burns clip per scene; frame counts come from cumulative time so audio and video never drift
    names = []
    for i, shot in enumerate(shots):
        frames = round(bounds[i + 1] * fps) - round(bounds[i] * fps)
        name = work / f"s{i:03d}.mp4"
        if not name.exists():
            if shot.card:
                from .motion import animate_card
                animate_card(shot.card["card_type"], shot.card["title"], shot.card["lines"], size, fps,
                             max(frames, 2), name, backdrop=shot.card.get("backdrop"))
            else:
                shot_clip(shot.image, max(frames, 1), shot.motion, size, fps, name)
        names.append(name.name)
    (work / "shots.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
    ff(["-f", "concat", "-safe", "0", "-i", "shots.txt", "-c", "copy", "video.mp4"], cwd=work)

    srt(clips, starts, work / "captions.srt")
    inputs = ["-i", "video.mp4", "-i", "narration.wav"]
    music = _music()
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music.resolve())]
        audio = (f"[2:a]volume={channel()['video']['music_volume_db']}dB[m];"
                 "[1:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        audio = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"

    if kind == "vertical":
        captions_ass(clips, starts, size, hook_text, work / "captions.ass")
        fonts = work / "fonts"
        fonts.mkdir(exist_ok=True)
        if font_path("display"):
            shutil.copy(font_path("display"), fonts)
        video = ["-filter_complex", f"[0:v]subtitles=captions.ass:fontsdir=fonts[v];{audio}", "-map", "[v]",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "19"]
    else:
        video = ["-filter_complex", audio, "-map", "0:v", "-c:v", "copy"]

    ff([*inputs, *video, "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-t", f"{total:.3f}", "final.mp4"], cwd=work)
    shutil.move(work / "final.mp4", out)
    return out, starts


def chapters(scenes: list, starts: list[float]) -> list[tuple[float, str]]:
    out, last = [], None
    for scene, start in zip(scenes, starts):
        if scene.chapter != last:
            out.append((0.0 if not out else start, scene.chapter))
            last = scene.chapter
    return out

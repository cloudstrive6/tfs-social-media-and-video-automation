"""Animated infographics (MapWarden-style): every card is drawn frame by frame and piped straight into FFmpeg.

- stat      numbers count up, the value pops in with a little overshoot, the label slides up, an underline grows
- bars      "Label: 16" lines become bars that grow in turn while their numbers count up
- timeline  the spine draws itself downward; each point pops and its text slides in as the line reaches it
- quote     the quote writes itself word by word; the source fades in
- document  the paper slides up, a highlighter sweeps the key line, the MAY RESIBO stamp slams down
- map       camera flies in, regions fill, pins drop, labels pop, routes draw (see maps.MapScene)

In 9:16 everything stays in the top ~56% of the frame, clear of the burned captions.
"""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from typing import Callable, Iterator

from PIL import Image, ImageDraw, ImageFilter

from .design import BLUE, INK, PAPER, RED, WHITE, YELLOW, fit_text, font, glyphsafe

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


# ---------------------------------------------------------------- easing
def clamp(t: float) -> float:
    return max(0.0, min(1.0, t))


def phase(p: float, a: float, b: float) -> float:
    return clamp((p - a) / (b - a)) if b > a else float(p >= a)


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def back(t: float, s: float = 1.7) -> float:
    if t <= 0:
        return 0.0
    t -= 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


# ---------------------------------------------------------------- FFmpeg pipe
def write_clip(frames: Iterator[Image.Image], size: tuple[int, int], fps: int, out: Path) -> Path:
    w, h = size
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-r", str(fps), str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for img in frames:
            proc.stdin.write(img.convert("RGB").tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="ignore")
    if proc.wait():
        raise RuntimeError(f"ffmpeg (animation) failed: {err[-1500:]}")
    return out


# ---------------------------------------------------------------- shared look
SOURCE_TAG = re.compile(r"\s*\[S\d+(?:\s*,\s*S?\d+)*\]")


def tidy(text: str) -> str:
    """Card text never shows the writer's source tags ([S12], [S3, S4])."""
    return SOURCE_TAG.sub("", text or "").strip()


def _area(size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Where card content lives. 9:16: above the burned captions (top 58%) and clear of the Reels/TikTok
    button strip on the right edge; 16:9: the whole frame."""
    w, h = size
    if h > w * 1.3:
        return int(w * 0.05), int(h * 0.07), int(w * 0.85), int(h * 0.58)
    return 0, 0, w, h


def _background(size: tuple[int, int], color=INK, backdrop: Path | None = None) -> Image.Image:
    """Card backdrop: the neighbouring illustration, blurred and darkened (so the frame never looks half
    empty), or a textured flat colour when there is none."""
    w, h = size
    if backdrop and Path(backdrop).exists():
        art = Image.open(backdrop).convert("RGB")
        scale = max(w / art.width, h / art.height)
        art = art.resize((int(art.width * scale) + 1, int(art.height * scale) + 1), Image.BILINEAR)
        left, top = (art.width - w) // 2, (art.height - h) // 2
        art = art.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(radius=max(12, w // 40)))
        img = Image.blend(art, Image.new("RGB", size, color), 0.66)
    else:
        img = Image.new("RGB", size, color)
        d = ImageDraw.Draw(img)
        for i in range(0, w + h, max(40, w // 24)):                 # faint diagonal texture
            d.line([(i, 0), (i - h, h)], fill=tuple(min(255, c + 7) for c in color), width=2)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, int(h * 0.008)], fill=BLUE)
    d.rectangle([0, h - int(h * 0.008), w, h], fill=RED)
    return img


def _glow(img: Image.Image, p: float) -> Image.Image:
    """A slow drifting light so no frame is ever completely still."""
    w, h = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = w * (0.3 + 0.4 * p)
    cy = h * (0.25 + 0.05 * math.sin(p * math.pi * 2))
    r = max(w, h) * 0.35
    for k in range(6, 0, -1):
        rr = r * k / 6
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(0, 56, 168, 6))
    out = img.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


def _text_layer(text: str, fnt, fill, stroke: int = 0) -> Image.Image:
    text = glyphsafe(text, fnt)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    x0, y0, x1, y1 = probe.textbbox((0, 0), text, font=fnt, stroke_width=stroke)
    layer = Image.new("RGBA", (x1 - x0 + 4, y1 - y0 + 4), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((2 - x0, 2 - y0), text, font=fnt, fill=fill, stroke_width=stroke,
                               stroke_fill=(0, 0, 0))
    return layer


def _paste(img: Image.Image, layer: Image.Image, cx: float, cy: float, scale: float = 1.0,
           alpha: float = 1.0) -> None:
    if scale <= 0.01 or alpha <= 0.01:
        return
    if scale != 1.0:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.LANCZOS)
    if alpha < 1.0:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer.putalpha(a)
    img.paste(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)), layer)


def _count(text: str, t: float) -> str:
    """Every number in `text` shown at fraction t of its value, keeping its format (commas, decimals)."""
    def sub(m: re.Match) -> str:
        raw = m.group()
        value = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        shown = value * t
        s = f"{shown:,.{decimals}f}" if "," in raw else f"{shown:.{decimals}f}"
        return s
    return NUM.sub(sub, text)


# ---------------------------------------------------------------- card animations
def _stat(title: str, lines: list[str], size, n: int, backdrop=None) -> Iterator[Image.Image]:
    w, h = size
    x0, y0, x1, y1 = _area(size)
    aw, ah = x1 - x0, y1 - y0
    pad, cx = int(aw * 0.06), (x0 + x1) / 2
    big = lines[0] if lines else title
    label = title if lines else ""
    extra = lines[1:3]
    bg = _background(size, backdrop=backdrop)
    probe = ImageDraw.Draw(bg)
    bf, brows, blh = fit_text(probe, big, "display", aw - 2 * pad, int(ah * 0.38), start=int(ah * 0.3))
    lf, lrows, llh = fit_text(probe, label, "body", aw - 2 * pad, int(ah * 0.24), start=int(ah * 0.09)) if label \
        else (None, [], 0)
    ef, erows, elh = fit_text(probe, " · ".join(extra), "body", aw - 2 * pad, int(ah * 0.16),
                              start=int(ah * 0.055), min_size=20) if extra else (None, [], 0)
    top = y0 + (ah - (blh * len(brows) + int(ah * 0.06) + llh * len(lrows) + elh * len(erows) * 1.2)) / 2
    for i in range(n):
        p = i / max(n - 1, 1)
        img = _glow(bg, p)
        d = ImageDraw.Draw(img)
        pop = back(phase(p, 0.0, 0.25))
        count = ease_out(phase(p, 0.03, 0.45))
        y = top
        for row in brows:
            _paste(img, _text_layer(_count(row, count), bf, YELLOW, stroke=3), cx, y + blh / 2, 0.6 + 0.4 * pop,
                   phase(p, 0.0, 0.12))
            y += blh
        bar = ease_out(phase(p, 0.35, 0.6))
        d.rectangle([cx - aw * 0.3 * bar, y + ah * 0.015, cx + aw * 0.3 * bar, y + ah * 0.025], fill=RED)
        y += int(ah * 0.06)
        slide = ease_out(phase(p, 0.3, 0.55))
        for row in lrows:
            _paste(img, _text_layer(row, lf, WHITE, stroke=2), cx, y + llh / 2 + (1 - slide) * ah * 0.05, 1.0, slide)
            y += llh
        y += elh * 0.2
        for row in erows:
            _paste(img, _text_layer(row, ef, YELLOW, stroke=2), cx, y + elh / 2, 1.0, phase(p, 0.5, 0.7))
            y += elh
        yield img


def _bars(title: str, lines: list[str], size, n: int, backdrop=None) -> Iterator[Image.Image]:
    x0, y0, x1, y1 = _area(size)
    w, ah = x1 - x0, y1 - y0                   # layout width = the safe area
    pad = int(w * 0.06)
    bg = _background(size, backdrop=backdrop)
    probe = ImageDraw.Draw(bg)
    rows = []
    for line in lines[:5]:
        label, _, value = line.rpartition(":") if ":" in line else (line, "", "")
        m = NUM.search(value or line)
        rows.append((label.strip() or line, float(m.group().replace(",", "")) if m else 0.0, (value or "").strip()))
    top_value = max((v for _, v, _ in rows), default=1.0) or 1.0
    tf, tl, tlh = fit_text(probe, title.upper(), "display", w - 2 * pad, int(ah * 0.2), start=int(ah * 0.1))
    slot = (ah - tlh * len(tl) - pad) / max(len(rows), 1)
    lf = font("body", int(min(slot * 0.3, ah * 0.07)))
    vf = font("display", int(min(slot * 0.46, ah * 0.1)))
    colors = [YELLOW, RED, (90, 150, 255), WHITE, (120, 220, 160)]
    for i in range(n):
        p = i / max(n - 1, 1)
        img = _glow(bg, p)
        d = ImageDraw.Draw(img)
        y = y0 + pad * 0.6
        for row in tl:
            _paste(img, _text_layer(row, tf, YELLOW, stroke=2), x0 + w / 2, y + tlh / 2, 1.0, phase(p, 0.0, 0.15))
            y += tlh
        y += pad * 0.4
        for k, (label, value, raw) in enumerate(rows):
            grow = ease_out(phase(p, 0.12 + 0.12 * k, 0.5 + 0.12 * k))
            d.text((x0 + pad, y), glyphsafe(label, lf), font=lf, fill=WHITE, stroke_width=2, stroke_fill=(0, 0, 0))
            by = y + slot * 0.4
            full = (w - 2 * pad) * 0.72 * value / top_value
            d.rounded_rectangle([x0 + pad, by, x0 + pad + max(full * grow, 4), by + slot * 0.42],
                                radius=int(slot * 0.08), fill=colors[k % len(colors)])
            if grow > 0:
                d.text((x0 + pad + full * grow + pad * 0.3, by + slot * 0.21), _count(raw or f"{value:g}", grow),
                       font=vf, fill=WHITE, anchor="lm", stroke_width=2, stroke_fill=(0, 0, 0))
            y += slot
        yield img


def _timeline(title: str, lines: list[str], size, n: int, backdrop=None) -> Iterator[Image.Image]:
    x0, y0, x1, y1 = _area(size)
    w, ah = x1 - x0, y1 - y0
    pad = int(w * 0.06)
    bg = _background(size, backdrop=backdrop)
    probe = ImageDraw.Draw(bg)
    tf, tl, tlh = fit_text(probe, title.upper(), "display", w - 2 * pad, int(ah * 0.2), start=int(ah * 0.1))
    top, bottom = y0 + pad * 0.6 + tlh * len(tl) + pad * 0.5, y1 - pad * 0.4
    x = x0 + pad + int(w * 0.02)
    step = (bottom - top) / max(len(lines), 1)
    r = max(8, w // 90)
    items = [fit_text(probe, line, "body", x1 - x - 3 * r - pad, int(step * 0.9),
                      start=min(int(ah * 0.075), int(step * 0.5)), min_size=20) for line in lines]
    for i in range(n):
        p = i / max(n - 1, 1)
        img = _glow(bg, p)
        d = ImageDraw.Draw(img)
        y = y0 + pad * 0.6
        for row in tl:
            _paste(img, _text_layer(row, tf, YELLOW, stroke=2), x0 + w / 2, y + tlh / 2, 1.0, phase(p, 0.0, 0.12))
            y += tlh
        reach = top + (bottom - top) * ease_out(phase(p, 0.08, 0.7))
        d.line([x, top, x, reach], fill=WHITE, width=max(3, w // 300))
        for k, (lf, rows, lh) in enumerate(items):
            cy = top + step * k + step / 2
            if reach < cy - r:
                continue
            t = phase(reach, cy - r, cy + step * 0.5)
            rr = r * (0.4 + 0.6 * back(t))
            d.ellipse([x - rr, cy - rr, x + rr, cy + rr], fill=RED, outline=YELLOW, width=2)
            yy = cy - lh * len(rows) / 2
            for row in rows:
                layer = _text_layer(row, lf, WHITE, stroke=2)
                _paste(img, layer, x + 3 * r + layer.width / 2 + (1 - ease_out(t)) * w * 0.08, yy + lh / 2, 1.0, t)
                yy += lh
        yield img


def _quote(title: str, lines: list[str], size, n: int, backdrop=None) -> Iterator[Image.Image]:
    if lines and len(" ".join(lines).split()) > len(title.split()) * 1.5:
        title, lines = " ".join(lines), [title]          # source name was given as the title: swap
    title = title.strip("“”\"")
    x0, y0, x1, y1 = _area(size)
    w, ah = x1 - x0, y1 - y0
    pad = int(w * 0.06)
    bg = _background(size, backdrop=backdrop)
    probe = ImageDraw.Draw(bg)
    qf, qrows, qlh = fit_text(probe, f"“{title}”", "body", w - 2 * pad, int(ah * 0.62), start=int(ah * 0.085))
    attribution = "— " + " · ".join(lines) if lines else ""
    af, arows, alh = fit_text(probe, attribution, "body", w - 2 * pad, int(ah * 0.16), start=int(ah * 0.04),
                              min_size=18) if attribution else (None, [], 0)
    total_words = sum(len(r.split()) for r in qrows) or 1
    top = y0 + (ah - qlh * len(qrows) - alh * len(arows) - pad * 0.5) / 2
    for i in range(n):
        p = i / max(n - 1, 1)
        img = _glow(bg, p)
        d = ImageDraw.Draw(img)
        shown = int(total_words * ease_out(phase(p, 0.03, 0.6)) + 0.999)
        y, used = top, 0
        for row in qrows:
            words = row.split()
            take = max(0, min(len(words), shown - used))
            used += len(words)
            if take:
                d.text((x0 + pad, y), glyphsafe(" ".join(words[:take]), qf), font=qf, fill=WHITE, stroke_width=2,
                       stroke_fill=(0, 0, 0))
            y += qlh
        y += pad * 0.5
        fade = phase(p, 0.6, 0.78)
        for row in arows:
            layer = _text_layer(row, af, YELLOW, stroke=2)
            _paste(img, layer, x0 + pad + layer.width / 2, y + alh / 2, 1.0, fade)
            y += alh
        yield img


def _document(title: str, lines: list[str], size, n: int, backdrop=None) -> Iterator[Image.Image]:
    x0, y0, x1, y1 = _area(size)
    w, ah = x1 - x0, y1 - y0
    pad = int(w * 0.06)
    bg = _background(size, (22, 26, 36), backdrop=backdrop)
    sheet_w, sheet_h = w - pad, int(ah * 0.94)
    sheet = Image.new("RGB", (sheet_w, sheet_h), PAPER)
    sd = ImageDraw.Draw(sheet)
    ip = int(sheet_w * 0.06)
    tf, tl, tlh = fit_text(sd, title, "display", sheet_w - 2 * ip, int(sheet_h * 0.2), start=int(sheet_h * 0.1))
    y = ip
    for row in tl:
        sd.text((ip, y), row, font=tf, fill=INK)
        y += tlh
    y += int(sheet_h * 0.03)
    blocks = []
    for k, line in enumerate(lines[:4]):
        bf, rows, lh = fit_text(sd, line, "body", sheet_w - 2 * ip, int(sheet_h * 0.22), start=int(sheet_h * 0.07))
        blocks.append((y, rows, lh, bf))
        y += lh * len(rows) + lh // 2
    stamp = _text_layer("MAY RESIBO", font("display", int(sheet_h * 0.1)), RED).rotate(8, expand=True,
                                                                                       resample=Image.BICUBIC)
    for i in range(n):
        p = i / max(n - 1, 1)
        img = _glow(bg, p)
        page = sheet.copy()
        pd = ImageDraw.Draw(page)
        if blocks:
            by, rows, lh, bf = blocks[0]
            sweep = ease_out(phase(p, 0.3, 0.55))
            widest = max(pd.textlength(r, font=bf) for r in rows)
            pd.rectangle([ip - 8, by - 6, ip - 8 + (widest + 16) * sweep, by + lh * len(rows) + 4], fill=YELLOW)
        for by, rows, lh, bf in blocks:
            for row in rows:
                pd.text((ip, by), row, font=bf, fill=INK)
                by += lh
        rise = ease_out(phase(p, 0.0, 0.22))
        top = y0 + (ah - sheet_h) / 2 + (1 - rise) * ah * 0.4
        img.paste(page, (int(x0 + pad / 2), int(top)))
        slam = phase(p, 0.62, 0.72)
        if slam > 0:                                  # centred on the sheet: never under the side buttons
            _paste(img, stamp.copy(), x0 + w / 2, top + sheet_h - stamp.height * 0.7,
                   2.2 - 1.2 * ease_out(slam), slam)
        yield img


def _map(title: str, lines: list[str], size, n: int, backdrop=None) -> Iterator[Image.Image]:
    from .maps import MapScene

    scene = MapScene(title, lines or [title], size, ss=1, caption_safe=size[1] > size[0] * 1.3)
    hold = scene.frame(1.0)
    for i in range(n):
        p = i / max(n - 1, 1)
        yield hold if p >= 0.9 else scene.frame(min(1.0, p / 0.9))   # finish, then hold the final state


ANIMATIONS: dict[str, Callable] = {"stat": _stat, "bars": _bars, "timeline": _timeline, "quote": _quote,
                                   "document": _document, "map": _map}


def animate_card(card_type: str, title: str, lines: list[str], size: tuple[int, int], fps: int, frames: int,
                 out: Path, backdrop: Path | None = None) -> Path:
    """Render an animated card clip of exactly `frames` frames (the animation plays in the first ~2.5 s at most,
    then holds, so short shots still finish and long shots don't drag)."""
    anim = ANIMATIONS.get(card_type, _stat)
    play = min(frames, int(fps * 2.5)) if card_type != "map" else min(frames, int(fps * 3.5))
    gen = anim(tidy(title), [tidy(x) for x in lines if tidy(x)], size, max(play, 2), backdrop)
    last = None

    def all_frames():
        nonlocal last
        for k, img in enumerate(gen):
            if k >= frames:
                return
            last = img
            yield img
        hold = frames - play
        w, h = size
        for k in range(hold):                      # never a frozen frame: slow push-in while holding
            z = 1 + 0.035 * (k + 1) / hold
            cw, ch = w / z, h / z
            yield last.crop(((w - cw) / 2, (h - ch) / 2, (w + cw) / 2, (h + ch) / 2)).resize(size, Image.BILINEAR)

    return write_clip(all_frames(), size, fps, out)


def still(card_type: str, title: str, lines: list[str], size: tuple[int, int], backdrop: Path | None = None) -> Image.Image:
    """The finished state of an animated card, as a still (carousels, thumbnails, QA)."""
    frames = list(ANIMATIONS.get(card_type, _stat)(tidy(title), [tidy(x) for x in lines if tidy(x)], size, 2,
                                                   backdrop))
    return frames[-1]

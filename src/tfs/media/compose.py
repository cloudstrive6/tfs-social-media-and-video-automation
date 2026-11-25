"""Thumbnail compositing (Pillow): a real frame from the video plus an optional English overlay."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from ..config import ROOT
from .design import PAPER, YELLOW, cover, fit_text, vertical_gradient


LOGO = ROOT / "assets" / "logo.png"


def _logo(canvas: Image.Image, height: int, pos: str = "tr") -> None:
    if not LOGO.exists():
        return
    logo = Image.open(LOGO).convert("RGBA")
    logo = logo.resize((int(logo.width * height / logo.height), height), Image.LANCZOS)
    m = height // 2
    x = canvas.width - logo.width - m if "r" in pos else m
    y = m if "t" in pos else canvas.height - logo.height - m
    canvas.alpha_composite(logo, (x, y))


def thumbnail(image: Path, overlay_text: str, out: Path) -> Path:
    """1280x720 JPEG from a frame of the video; the overlay (at most a few English words) is optional."""
    canvas = cover(Image.open(image).convert("RGB"), (1280, 720)).convert("RGBA")
    if overlay_text:
        canvas.alpha_composite(vertical_gradient(canvas.size, 0, 170))
        d = ImageDraw.Draw(canvas)
        fnt, lines, lh = fit_text(d, overlay_text.upper(), "display", 1100, 260, start=150, min_size=70)
        y = 720 - 50 - lh * len(lines)
        for i, line in enumerate(lines):
            d.text((60, y), line, font=fnt, fill=YELLOW if i == len(lines) - 1 else PAPER,
                   stroke_width=10, stroke_fill=(0, 0, 0))
            y += lh
    _logo(canvas, 60)
    canvas.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    return out

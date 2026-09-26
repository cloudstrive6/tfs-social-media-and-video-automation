"""Thumbnail and carousel-slide compositing (Pillow)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from ..config import ROOT
from .design import BLUE, RED, THEMES, WHITE, YELLOW, cover, fit_text, font, vertical_gradient

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
    """1280x720 JPEG. Text is optional (Historically-style thumbnails are usually text-free)."""
    canvas = cover(Image.open(image).convert("RGB"), (1280, 720)).convert("RGBA")
    if overlay_text:
        canvas.alpha_composite(vertical_gradient(canvas.size, 0, 170))
        d = ImageDraw.Draw(canvas)
        fnt, lines, lh = fit_text(d, overlay_text.upper(), "display", 1100, 260, start=150, min_size=70)
        y = 720 - 50 - lh * len(lines)
        for i, line in enumerate(lines):
            d.text((60, y), line, font=fnt, fill=YELLOW if i == len(lines) - 1 else WHITE,
                   stroke_width=10, stroke_fill=(0, 0, 0))
            y += lh
    _logo(canvas, 60)
    canvas.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    return out


def slide(index: int, total: int, headline: str, body: str, source: str, theme: str,
          background: Path | None, out: Path, handle: str) -> Path:
    """1080x1350 (4:5) carousel slide."""
    size, pad = (1080, 1350), 84
    bg, head_c, body_c, accent = THEMES.get(theme, THEMES["dark"])
    canvas = Image.new("RGBA", size, (*bg, 255))
    is_cover = index == 0

    if background:
        art = cover(Image.open(background).convert("RGB"), size).convert("RGBA")
        canvas.alpha_composite(art)
        canvas.alpha_composite(vertical_gradient(size, 40 if is_cover else 120, 235, bg))

    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, size[0], 14], fill=BLUE)
    d.rectangle([0, 14, size[0], 22], fill=RED)

    if is_cover:
        fnt, lines, lh = fit_text(d, headline.upper(), "display", size[0] - 2 * pad, 560, start=150, min_size=64)
        y = size[1] - pad - 190 - lh * len(lines)
        for line in lines:
            d.text((pad, y), line, font=fnt, fill=head_c, stroke_width=4, stroke_fill=(0, 0, 0))
            y += lh
        bf, blines, blh = fit_text(d, body, "body", size[0] - 2 * pad, 150, start=46)
        y += 20
        for line in blines:
            d.text((pad, y), line, font=bf, fill=accent)
            y += blh
        d.text((size[0] - pad, size[1] - 60), "SWIPE >", font=font("display", 44), fill=WHITE, anchor="rs")
    else:
        d.text((pad, 90), f"{index + 1:02d}", font=font("display", 96), fill=accent)
        hf, hlines, hlh = fit_text(d, headline, "display", size[0] - 2 * pad, 420, start=104, min_size=54)
        y = 240
        for line in hlines:
            d.text((pad, y), line, font=hf, fill=head_c)
            y += hlh
        bf, blines, blh = fit_text(d, body, "body", size[0] - 2 * pad, size[1] - y - 260, start=50, min_size=30)
        y += 40
        for line in blines:
            d.text((pad, y), line, font=bf, fill=body_c)
            y += blh

    if source:
        sf, slines, slh = fit_text(d, "Source: " + source, "body", size[0] - 2 * pad, 80, start=26, min_size=18)
        y = size[1] - 110 - slh * (len(slines) - 1)
        for line in slines:
            d.text((pad, y), line, font=sf, fill=body_c)
            y += slh
    d.text((pad, size[1] - 50), handle, font=font("body", 28), fill=body_c, anchor="ls")
    d.text((size[0] // 2, size[1] - 50), f"{index + 1}/{total}", font=font("body", 28), fill=body_c,
           anchor="ms")
    _logo(canvas, 56, "tr")
    canvas.convert("RGB").save(out, "JPEG", quality=92)
    return out

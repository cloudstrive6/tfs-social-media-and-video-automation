"""Thumbnail and carousel-slide compositing (Pillow)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from ..config import ROOT
from .design import BLUE, INK, PAPER, RED, THEMES, WHITE, YELLOW, cover, fit_text, font, vertical_gradient

INK_RGB, PAPER_RGB = INK, PAPER

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


# Vector-engine art sits in its own band at full colour; the words sit on a solid panel under it (never on
# top of the characters). The engine draws each still at exactly its band's size.
SLIDE = (1080, 1350)
TOP = 22                                     # flag stripes
BAND = {"cover": 840, "text": 620, "panel": 1000}


def band_size(layout: str) -> tuple[int, int]:
    return SLIDE[0], BAND.get(layout, BAND["text"])


def _stripes(d: ImageDraw.ImageDraw) -> None:
    d.rectangle([0, 0, SLIDE[0], 14], fill=BLUE)
    d.rectangle([0, 14, SLIDE[0], TOP], fill=RED)


def _band(canvas: Image.Image, art: Path, height: int, accent) -> int:
    """Paste the art full-width under the stripes; returns the y where the text panel starts."""
    img = cover(Image.open(art).convert("RGB"), (SLIDE[0], height)).convert("RGBA")
    canvas.alpha_composite(img, (0, TOP))
    y = TOP + height
    ImageDraw.Draw(canvas).rectangle([0, y, SLIDE[0], y + 8], fill=accent)
    return y + 8


def _footer(d: ImageDraw.ImageDraw, index: int, total: int, source: str, handle: str, colour, pad: int,
            swipe: bool) -> int:
    """Source line, handle, page number (and SWIPE on the cover). Returns the top of the footer."""
    top = SLIDE[1] - 50
    if source:
        sf, slines, slh = fit_text(d, "Source: " + source, "body", SLIDE[0] - 2 * pad, 64, start=24, min_size=18)
        top = SLIDE[1] - 92 - slh * (len(slines) - 1)
        y = top
        for line in slines:
            d.text((pad, y), line, font=sf, fill=colour)
            y += slh
    d.text((pad, SLIDE[1] - 40), handle, font=font("body", 26), fill=colour, anchor="ls")
    d.text((SLIDE[0] // 2, SLIDE[1] - 40), f"{index + 1}/{total}", font=font("body", 26), fill=colour, anchor="ms")
    if swipe:
        d.text((SLIDE[0] - pad, SLIDE[1] - 40), "SWIPE >", font=font("display", 40), fill=YELLOW, anchor="rs")
    return top - 16


def slide(index: int, total: int, headline: str, body: str, source: str, theme: str,
          background: Path | None, out: Path, handle: str) -> Path:
    """1080x1350 (4:5) carousel slide: art band on top (if any), then headline + body on a solid panel."""
    pad = 72
    bg, head_c, body_c, accent = THEMES.get(theme, THEMES["dark"])
    canvas = Image.new("RGBA", SLIDE, (*bg, 255))
    is_cover = index == 0
    d = ImageDraw.Draw(canvas)
    _stripes(d)
    y = _band(canvas, background, BAND["cover" if is_cover else "text"], accent) + 28 if background else 90
    d = ImageDraw.Draw(canvas)
    bottom = _footer(d, index, total, source, handle, body_c, pad, is_cover)

    if not is_cover:
        num = f"{index + 1:02d}"
        if background:                                  # a badge on the art, not a line of its own
            nf = font("display", 64)
            w = d.textlength(num, font=nf) + 44
            d.rounded_rectangle([pad - 20, TOP + 26, pad - 20 + w, TOP + 116], radius=18, fill=(*bg, 255))
            d.text((pad + 2, TOP + 71), num, font=nf, fill=accent, anchor="lm")
        else:
            d.text((pad, y), num, font=font("display", 96), fill=accent)
            y += 130
    room = bottom - y
    head_h = int(room * (0.62 if is_cover else 0.42 if background else 0.5)) if body else room
    hf, hlines, hlh = fit_text(d, headline.upper() if is_cover else headline, "display", SLIDE[0] - 2 * pad, head_h,
                               start=132 if is_cover or not background else 96, min_size=48)
    bf, blines, blh = (fit_text(d, body, "body", SLIDE[0] - 2 * pad, room - hlh * len(hlines) - 18,
                                start=46 if is_cover else 44 if background else 58, min_size=28)
                       if body else (None, [], 0))
    if not background and not is_cover:              # a text-only slide: the block sits in the middle
        y += max(0, (room - hlh * len(hlines) - 18 - blh * len(blines)) // 2 - 40)
    for line in hlines:
        d.text((pad, y), line, font=hf, fill=head_c, stroke_width=3 if is_cover else 0, stroke_fill=(0, 0, 0))
        y += hlh
    y += 18
    for line in blines:
        d.text((pad, y), line, font=bf, fill=accent if is_cover else body_c)
        y += blh
    _logo(canvas, 56, "tr")
    canvas.convert("RGB").save(out, "JPEG", quality=92)
    return out


def panel_slide(index: int, total: int, caption: str, speech: str, source: str, art: Path | None,
                out: Path, handle: str) -> Path:
    """Comic/satire panel: the art (with its speech bubble, drawn by the engine on the speaker) in a bordered
    frame on top, the narrator's caption box below it. `speech` is drawn here only when there's no art."""
    pad = 56
    canvas = Image.new("RGBA", SLIDE, (*PAPER_RGB, 255))
    d = ImageDraw.Draw(canvas)
    _stripes(d)
    y = TOP
    if art:
        y = _band(canvas, art, BAND["panel"], INK_RGB)
        d = ImageDraw.Draw(canvas)
        d.rectangle([0, TOP, SLIDE[0] - 1, y - 1], outline=INK_RGB, width=8)
    elif speech:
        sf, slines, slh = fit_text(d, speech, "body", SLIDE[0] - 2 * pad - 120, 300, start=52, min_size=30)
        bw = max(d.textlength(line, font=sf) for line in slines) + 80
        bh = slh * len(slines) + 60
        x0, y0 = pad + 20, pad + 60
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=46, fill=WHITE, outline=INK_RGB, width=6)
        yy = y0 + 30
        for line in slines:
            d.text((x0 + 40, yy), line, font=sf, fill=INK_RGB)
            yy += slh
        y = y0 + bh + 40

    if caption:
        box_top = y + 24
        box_bottom = SLIDE[1] - 70
        cf, clines, clh = fit_text(d, caption.upper(), "display", SLIDE[0] - 2 * pad - 60,
                                   box_bottom - box_top - 56 - (34 if source else 0), start=64, min_size=32)
        d.rectangle([pad, box_top, SLIDE[0] - pad, box_bottom], fill=YELLOW, outline=INK_RGB, width=6)
        yy = box_top + 24
        for line in clines:
            d.text((pad + 30, yy), line, font=cf, fill=INK_RGB)
            yy += clh
        if source:
            sf, slines, slh = fit_text(d, "Source: " + source, "body", SLIDE[0] - 2 * pad - 60, 60, start=22,
                                       min_size=16)
            yy = box_bottom - 18 - slh * len(slines)
            for line in slines:
                d.text((pad + 30, yy), line, font=sf, fill=INK_RGB)
                yy += slh

    d.text((pad, SLIDE[1] - 28), handle, font=font("body", 24), fill=INK_RGB, anchor="ls")
    d.text((SLIDE[0] - pad, SLIDE[1] - 28), f"{index + 1}/{total}", font=font("body", 24), fill=INK_RGB, anchor="rs")
    _logo(canvas, 56, "tr")
    canvas.convert("RGB").save(out, "JPEG", quality=92)
    return out

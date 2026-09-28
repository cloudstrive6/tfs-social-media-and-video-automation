"""Thumbnail and carousel-slide compositing (Pillow)."""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from ..config import ROOT
from .design import BLUE, INK, PAPER, RED, WHITE, YELLOW, cover, fit_text, font, glyphsafe, vertical_gradient


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


# ---------------------------------------------------------------- carousel slides
# One design system for every slide (1080x1350, 4:5):
# - the art is an inset rounded card with a soft shadow on a gradient + dot-texture background (the cover gets a
#   full-bleed image fading into the headline), drawn by the vector engine at exactly the card's size;
# - one spacing grid: 80 px side margins, fixed gaps between number, headline, body and footer;
# - headlines are balanced (no lone last word) and their key phrase sits on a yellow highlighter box;
# - body copy has air between lines, with numbers, peso amounts and *marked* phrases in the accent colour;
# - a footer with a hairline, the source (muted), the handle and progress dots; the cover gets a SWIPE pill.
SLIDE = (1080, 1350)
PAD = 80
TOP = 22                                     # flag stripes
CARD_X, CARD_Y, CARD_R = 48, TOP + 34, 36
ART = {"cover": (1080, 800), "text": (1080 - 2 * CARD_X, 560), "panel": (1080 - 2 * CARD_X, 860)}
FOOTER_H = 128

PALETTES = {  # gradient top, gradient bottom, headline, body, accent, muted
    "dark": ((22, 27, 42), (9, 11, 19), WHITE, (214, 219, 232), YELLOW, (132, 140, 160)),
    "flag_blue": ((12, 64, 178), (0, 30, 104), WHITE, (226, 233, 255), YELLOW, (160, 180, 230)),
    "flag_red": ((214, 30, 52), (138, 8, 26), WHITE, (255, 228, 228), YELLOW, (240, 170, 176)),
    "paper": ((248, 242, 227), (234, 224, 200), INK, (58, 54, 48), RED, (128, 118, 102)),
}
NUMBER = re.compile(r"[₱$%]|\d")


def band_size(layout: str) -> tuple[int, int]:
    """Pixel size of a layout's art (what the engine should draw)."""
    return ART.get(layout, ART["text"])


def _background(theme: str) -> Image.Image:
    top, bottom, *_ = PALETTES.get(theme, PALETTES["dark"])
    w, h = SLIDE
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    canvas = grad.resize(SLIDE).convert("RGBA")
    dots = Image.new("RGBA", SLIDE, (0, 0, 0, 0))
    d = ImageDraw.Draw(dots)
    ink = (0, 0, 0, 16) if theme == "paper" else (255, 255, 255, 14)
    for y in range(20, h, 30):
        for x in range(20 + (y // 30 % 2) * 15, w, 30):
            d.ellipse([x - 1.6, y - 1.6, x + 1.6, y + 1.6], fill=ink)
    canvas.alpha_composite(dots)
    _stripes(ImageDraw.Draw(canvas))
    return canvas


def _stripes(d: ImageDraw.ImageDraw) -> None:
    d.rectangle([0, 0, SLIDE[0], 14], fill=BLUE)
    d.rectangle([0, 14, SLIDE[0], TOP], fill=RED)


def _card(canvas: Image.Image, art: Path, box: tuple[int, int, int, int], radius: int = CARD_R) -> None:
    """Art as a rounded card with a soft drop shadow."""
    x, y, w, h = box
    shadow = Image.new("RGBA", SLIDE, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x, y + 16, x + w, y + h + 16], radius=radius, fill=(0, 0, 0, 110))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    img = cover(Image.open(art).convert("RGB"), (w, h)).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    canvas.paste(img, (x, y), mask)


# -------- rich text: *marked* phrases and numbers get emphasis
def _tokens(text: str) -> list[tuple[str, bool]]:
    """Words with an emphasis flag: inside *asterisks*, or (when nothing is marked) any word with a number."""
    marked = "*" in text
    out, on = [], False
    for raw in text.replace("\n", " ").split():
        starts, ends = raw.startswith("*"), raw.rstrip(".,;:!?)\"'”").endswith("*")
        word = raw.replace("*", "")
        if not word:
            on = not on if starts else on
            continue
        if starts:
            on = True
        out.append((word, on if marked else bool(NUMBER.search(word))))
        if ends:
            on = False
    return out


def _wrap_tokens(d, tokens, fnt, max_w: int) -> list[list[tuple[str, bool]]]:
    lines, line = [], []
    for tok in tokens:
        trial = " ".join(w for w, _ in line + [tok])
        if line and d.textlength(trial, font=fnt) > max_w:
            lines.append(line)
            line = [tok]
        else:
            line.append(tok)
    if line:
        lines.append(line)
    # no lone last word: pull one down from the line above when it fits
    if len(lines) > 1 and len(lines[-1]) == 1 and len(lines[-2]) > 2:
        moved = [lines[-2][-1], *lines[-1]]
        if d.textlength(" ".join(w for w, _ in moved), font=fnt) <= max_w:
            lines[-2], lines[-1] = lines[-2][:-1], moved
    return lines


def _fit_rich(d, text: str, role: str, max_w: int, max_h: int, start: int, min_size: int, leading: float):
    """Largest size whose wrapped lines fit the box. Returns (font, lines, line_height)."""
    tokens = [(glyphsafe(w, font(role, start)), e) for w, e in _tokens(text)]
    size = start
    while True:
        fnt = font(role, size)
        lines = _wrap_tokens(d, tokens, fnt, max_w)
        lh = int(size * leading)
        if (lh * len(lines) <= max_h and all(d.textlength(" ".join(w for w, _ in ln), font=fnt) <= max_w
                                              for ln in lines)) or size <= min_size:
            return fnt, lines, lh
        size -= 2


def _draw_rich(d, lines, fnt, lh: int, x: int, y: int, colour, emphasis, marker=None, align_w: int = 0) -> int:
    """Draw wrapped lines; emphasised words in `emphasis` colour, or on a `marker` box (headlines).
    Returns the y below the block."""
    space = d.textlength(" ", font=fnt)
    asc, desc = fnt.getmetrics()
    for ln in lines:
        width = d.textlength(" ".join(w for w, _ in ln), font=fnt)
        cx = x + (align_w - width) / 2 if align_w else x
        for word, emph in ln:
            ww = d.textlength(word, font=fnt)
            if emph and marker:
                pad = fnt.size * 0.12
                d.rounded_rectangle([cx - pad, y + asc * 0.08, cx + ww + pad, y + asc + desc * 0.35],
                                    radius=int(fnt.size * 0.12), fill=marker)
                d.text((cx, y), word, font=fnt, fill=INK)
            else:
                d.text((cx, y), word, font=fnt, fill=emphasis if emph else colour)
            cx += ww + space
        y += lh
    return y


def _headline_block(d, headline: str, body: str, theme: str, x: int, y: int, w: int, h: int, *, head_start: int,
                    body_start: int, head_share: float, center: bool = False, upper: bool = False,
                    vcenter: bool = False) -> None:
    _, _, head_c, body_c, accent, _ = PALETTES.get(theme, PALETTES["dark"])
    gap = 40
    head_h = int(h * head_share) if body else h
    hf, hl, hlh = _fit_rich(d, headline.upper() if upper else headline, "display", w, head_h, head_start, 50, 1.14)
    used = hlh * len(hl)
    bf, bl, blh = (_fit_rich(d, body, "body", w, h - used - gap, body_start, 30, 1.38) if body else (None, [], 0))
    total = used + (gap + blh * len(bl) if bl else 0)
    if center or vcenter:
        y += max(0, (h - total) // 2)
    y = _draw_rich(d, hl, hf, hlh, x, y, head_c, head_c, marker=YELLOW, align_w=w if center else 0)
    if bl:
        _draw_rich(d, bl, bf, blh, x, y + gap, body_c, accent, align_w=w if center else 0)


def _footer(d, index: int, total: int, source: str, handle: str, theme: str, swipe: bool) -> int:
    """Hairline, source, handle and progress dots. Returns the y where the footer starts."""
    *_, accent, muted = PALETTES.get(theme, PALETTES["dark"])
    w, h = SLIDE
    top = h - FOOTER_H
    if source:
        sf, sl, slh = _fit_rich(d, "Source: " + source, "body", w - 2 * PAD, 58, 22, 16, 1.25)
        top = h - 70 - slh * len(sl)
        for i, line in enumerate(sl):
            d.text((PAD, top + i * slh), " ".join(t for t, _ in line), font=sf, fill=muted)
    d.line([PAD, top - 16, w - PAD, top - 16], fill=(*muted, 120) if len(muted) == 3 else muted, width=2)
    d.text((PAD, h - 30), handle, font=font("body", 24), fill=muted, anchor="ls")
    if swipe:
        pill = font("display", 34)
        tw = d.textlength("SWIPE  →", font=pill)
        d.rounded_rectangle([w - PAD - tw - 44, h - 76, w - PAD, h - 18], radius=29, fill=YELLOW)
        d.text((w - PAD - 22, h - 47), "SWIPE  →", font=pill, fill=INK, anchor="rm")
    else:
        r, step = 7, 24
        x0 = w - PAD - step * (total - 1)
        for i in range(total):
            cx, cy = x0 + i * step, h - 40
            fill = accent if i == index else muted
            rr = r if i == index else r - 3
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=fill)
    return top - 40


def _save(canvas: Image.Image, out: Path) -> Path:
    _logo(canvas, 56, "tr")
    canvas.convert("RGB").save(out, "JPEG", quality=93)
    return out


def slide(index: int, total: int, headline: str, body: str, source: str, theme: str,
          background: Path | None, out: Path, handle: str) -> Path:
    """Cover (index 0), art slide (art card + text) or text-only slide."""
    theme = theme if theme in PALETTES else "dark"
    canvas = _background(theme)
    w, h = SLIDE
    accent = PALETTES[theme][4]
    if index == 0:
        if background:                                   # full-bleed image fading into the headline area
            art = cover(Image.open(background).convert("RGB"), ART["cover"]).convert("RGBA")
            canvas.alpha_composite(art, (0, TOP))
            top_c = PALETTES[theme][1]
            fade = Image.new("RGBA", SLIDE, (0, 0, 0, 0))
            fd = ImageDraw.Draw(fade)
            f0, f1 = TOP + ART["cover"][1] - 260, TOP + ART["cover"][1]
            for yy in range(f0, f1):
                a = int(255 * ((yy - f0) / (f1 - f0)) ** 1.6)
                fd.line([0, yy, w, yy], fill=(*top_c, a))
            fd.rectangle([0, f1, w, h], fill=(*top_c, 255))
            canvas.alpha_composite(fade)
            _stripes(ImageDraw.Draw(canvas))
        d = ImageDraw.Draw(canvas)
        bottom = _footer(d, index, total, source, handle, theme, swipe=True)
        y0 = TOP + ART["cover"][1] - 70 if background else 200
        _headline_block(d, headline, body, theme, PAD, y0, w - 2 * PAD, bottom - y0, head_start=124,
                        body_start=40, head_share=0.66, upper=True)
        return _save(canvas, out)

    d = ImageDraw.Draw(canvas)
    bottom = _footer(d, index, total, source, handle, theme, swipe=False)
    if background:
        cw, ch = ART["text"]
        _card(canvas, background, (CARD_X, CARD_Y, cw, ch))
        d = ImageDraw.Draw(canvas)
        num = f"{index + 1:02d}"
        nf = font("display", 54)
        nw = d.textlength(num, font=nf)
        bx, by = CARD_X + 24, CARD_Y + 24
        d.rounded_rectangle([bx, by, bx + nw + 36, by + 76], radius=20, fill=accent)
        d.text((bx + 18 + nw / 2, by + 38), num, font=nf, fill=INK if accent == YELLOW else WHITE, anchor="mm")
        y0 = CARD_Y + ch + 44
        _headline_block(d, headline, body, theme, PAD, y0, w - 2 * PAD, bottom - y0, head_start=84,
                        body_start=46, head_share=0.42)
    else:                                                # text-only: a centred statement
        d.text((PAD, 110), f"{index + 1:02d}", font=font("display", 88), fill=accent)
        d.rectangle([PAD, 222, PAD + 120, 232], fill=accent)
        y0 = 270
        _headline_block(d, headline, body, theme, PAD, y0, w - 2 * PAD, bottom - y0, head_start=112,
                        body_start=50, head_share=0.5, vcenter=True)
    return _save(canvas, out)


def panel_slide(index: int, total: int, caption: str, speech: str, source: str, art: Path | None,
                out: Path, handle: str) -> Path:
    """Comic panel: the art card (the engine drew the speech bubble on the speaker) and the narrator's caption
    box under it. `speech` is drawn here only when there's no art."""
    canvas = _background("paper")
    w, h = SLIDE
    d = ImageDraw.Draw(canvas)
    y = CARD_Y
    if art:
        cw, ch = ART["panel"]
        _card(canvas, art, (CARD_X, CARD_Y, cw, ch), radius=24)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle([CARD_X, CARD_Y, CARD_X + cw, CARD_Y + ch], radius=24, outline=INK, width=6)
        y = CARD_Y + ch
    elif speech:
        sf, sl, slh = _fit_rich(d, speech, "body", w - 2 * PAD - 80, 320, 54, 30, 1.25)
        bw = max(d.textlength(" ".join(t for t, _ in ln), font=sf) for ln in sl) + 80
        bh = slh * len(sl) + 60
        x0, y0 = PAD, CARD_Y + 60
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=46, fill=WHITE, outline=INK, width=6)
        _draw_rich(d, sl, sf, slh, x0 + 40, y0 + 30, INK, RED)
        y = y0 + bh + 40
    footer_top = h - 64
    if caption:
        box_top, box_bottom = y + 28, footer_top - 8
        inner_w = w - 2 * CARD_X - 64
        src_h = 0
        if source:
            sf, sl, slh = _fit_rich(d, "Source: " + source, "body", inner_w, 52, 20, 15, 1.2)
            src_h = slh * len(sl) + 24
        cf, cl, clh = _fit_rich(d, caption.upper(), "display", inner_w, box_bottom - box_top - 48 - src_h, 66, 34, 1.08)
        d.rounded_rectangle([CARD_X, box_top, w - CARD_X, box_bottom], radius=20, fill=YELLOW, outline=INK, width=6)
        text_h = clh * len(cl) + src_h
        yy = box_top + max(24, (box_bottom - box_top - text_h) // 2)
        yy = _draw_rich(d, cl, cf, clh, CARD_X + 32, yy, INK, RED)
        if source:
            yy += 14
            for line in sl:
                d.text((CARD_X + 32, yy), " ".join(t for t, _ in line), font=sf, fill=(70, 62, 30))
                yy += slh
    d.text((PAD, h - 26), handle, font=font("body", 24), fill=(90, 84, 72), anchor="ls")
    r, step = 7, 24
    x0 = w - PAD - step * (total - 1)
    for i in range(total):
        rr = r if i == index else r - 3
        d.ellipse([x0 + i * step - rr, h - 36 - rr, x0 + i * step + rr, h - 36 + rr],
                  fill=RED if i == index else (170, 160, 140))
    return _save(canvas, out)

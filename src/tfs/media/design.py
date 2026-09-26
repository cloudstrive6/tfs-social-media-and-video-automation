"""Brand palette, font loading and text layout helpers shared by cards, thumbnails and carousels."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import ROOT, channel

BLUE, RED, YELLOW = (0, 56, 168), (206, 17, 38), (252, 209, 22)
INK, PAPER, WHITE = (14, 16, 24), (242, 234, 214), (255, 255, 255)

THEMES = {  # background, headline, body, accent
    "dark": ((14, 16, 24), WHITE, (205, 210, 222), YELLOW),
    "flag_blue": (BLUE, WHITE, (220, 228, 255), YELLOW),
    "flag_red": (RED, WHITE, (255, 222, 222), YELLOW),
    "paper": (PAPER, INK, (60, 56, 50), RED),
}

FALLBACK_FONTS = {
    "display": ["C:/Windows/Fonts/impact.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "body": ["C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}


@lru_cache
def font_path(role: str) -> str | None:
    configured = channel()["video"]["font" if role == "display" else "caption_font"]
    for p in [ROOT / configured, *map(Path, FALLBACK_FONTS[role])]:
        if p.exists():
            return str(p)
    return None


def font(role: str, size: int) -> ImageFont.FreeTypeFont:
    path = font_path(role)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


def _glyph(ch: str, fnt) -> bytes:
    im = Image.new("L", (int(fnt.size * 1.5), int(fnt.size * 1.5)))
    ImageDraw.Draw(im).text((0, 0), ch, font=fnt, fill=255)
    return im.tobytes()


def glyphsafe(text: str, fnt) -> str:
    """Never draw a tofu box: swap characters the font can't draw for newspaper-style equivalents (₱ -> P),
    their plain form (① -> 1, ﬁ -> fi), or drop them."""
    import unicodedata

    missing = _glyph(chr(0xFFFF), fnt)
    for ch, alt in (("₱", "P"), ("✓", ""), ("→", ">"), ("—", "-")):
        if ch in text and _glyph(ch, fnt) == missing:
            text = text.replace(ch, alt)
    out = []
    for ch in text:
        if ch.isascii() or ch.isspace() or _glyph(ch, fnt) != missing:
            out.append(ch)
            continue
        plain = unicodedata.normalize("NFKC", ch)
        out.append(plain if plain != ch and all(c.isascii() or _glyph(c, fnt) != missing for c in plain) else "")
    return "".join(out)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit_text(draw, text: str, role: str, max_width: int, max_height: int, start: int, min_size: int = 28):
    """Largest font size at which `text` wraps into the box. Returns (font, lines, line_height)."""
    size = start
    while size > min_size:
        fnt = font(role, size)
        lines = wrap(draw, glyphsafe(text, fnt), fnt, max_width)
        lh = int(size * 1.12)
        widest = max((draw.textlength(line, font=fnt) for line in lines), default=0)
        if lh * len(lines) <= max_height and widest <= max_width:
            return fnt, lines, lh
        size -= 4
    fnt = font(role, min_size)
    return fnt, wrap(draw, glyphsafe(text, fnt), fnt, max_width), int(min_size * 1.12)


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize + center-crop to fill `size`."""
    w, h = size
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def vertical_gradient(size: tuple[int, int], top_alpha: int, bottom_alpha: int, color=(0, 0, 0)) -> Image.Image:
    w, h = size
    grad = Image.new("L", (1, h))
    for y in range(h):
        grad.putpixel((0, y), int(top_alpha + (bottom_alpha - top_alpha) * y / (h - 1)))
    overlay = Image.new("RGBA", size, (*color, 0))
    overlay.putalpha(grad.resize(size))
    return overlay

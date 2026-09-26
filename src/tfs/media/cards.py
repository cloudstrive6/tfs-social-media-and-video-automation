"""Programmatic motion-graphic cards: stats, quotes, timelines, documents, places. Always sharp and legible."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .design import BLUE, INK, PAPER, RED, WHITE, YELLOW, fit_text, font, glyphsafe


CAPTION_SAFE = 0.54   # vertical: card content stays in the top 54%; burned captions sit ~58-72% down


def render_card(card_type: str, title: str, lines: list[str], size: tuple[int, int], out: Path) -> Path:
    if card_type == "map":                  # real geography: card_lines are the place names to highlight
        from .maps import render_map
        return render_map(title, lines or [title], size, out)
    w, h = size
    if h > w * 1.3:                         # 9:16: lay the card out in the upper area, clear of the captions
        inner = _draw(card_type, title, lines, (w, int(h * CAPTION_SAFE)), stripes=False)
        img = Image.new("RGB", size, inner.getpixel((w // 2, 2)))
        img.paste(inner, (0, int(h * 0.06)))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, w, int(h * 0.008)], fill=BLUE)
        d.rectangle([0, h - int(h * 0.008), w, h], fill=RED)
        img.save(out)
        return out
    _draw(card_type, title, lines, size).save(out)
    return out


def _draw(card_type: str, title: str, lines: list[str], size: tuple[int, int], stripes: bool = True) -> Image.Image:
    w, h = size
    pad = int(min(w, h) * 0.08)
    paper = card_type == "document"
    img = Image.new("RGB", size, PAPER if paper else INK)
    d = ImageDraw.Draw(img)
    fg = INK if paper else WHITE
    if stripes:  # flag stripe
        d.rectangle([0, 0, w, int(h * 0.012)], fill=BLUE)
        d.rectangle([0, h - int(h * 0.012), w, h], fill=RED)

    if card_type == "stat":
        big = lines[0] if lines else title
        fnt, rows, lh = fit_text(d, big, "display", w - 2 * pad, int(h * 0.45), start=int(h * 0.3))
        y = int(h * 0.22)
        for r in rows:
            d.text((w / 2, y), r, font=fnt, fill=YELLOW, anchor="mt")
            y += lh
        fnt2, rows2, lh2 = fit_text(d, title, "body", w - 2 * pad, int(h * 0.25), start=int(h * 0.07))
        y += int(h * 0.04)
        for r in rows2:
            d.text((w / 2, y), r, font=fnt2, fill=fg, anchor="mt")
            y += lh2

    elif card_type == "quote":
        fnt, rows, lh = fit_text(d, f"“{title}”", "body", w - 2 * pad, int(h * 0.55), start=int(h * 0.08))
        y = int(h * 0.2)
        for r in rows:
            d.text((pad, y), r, font=fnt, fill=fg)
            y += lh
        if lines:
            af, al, alh = fit_text(d, "— " + " · ".join(lines), "body", w - 2 * pad, max(int(h - pad - y - lh // 2), 40),
                                   start=int(h * 0.035), min_size=18)
            y += lh // 2
            for row in al:
                d.text((pad, y), row, font=af, fill=YELLOW)
                y += alh

    elif card_type == "timeline":
        tf, tl, tlh = fit_text(d, title.upper(), "display", w - 2 * pad, int(h * 0.16), start=int(h * 0.07))
        for j, row in enumerate(tl):
            d.text((pad, pad + j * tlh), row, font=tf, fill=YELLOW)
        n = max(len(lines), 1)
        top, bottom = int(h * 0.3), h - pad
        x = pad + int(w * 0.02)
        d.line([x, top, x, bottom], fill=WHITE, width=max(3, w // 400))
        step = (bottom - top) / n
        r = max(8, w // 120)
        for i, line in enumerate(lines):
            y = top + step * i + step / 2
            d.ellipse([x - r, y - r, x + r, y + r], fill=RED)
            lf, rows, lh = fit_text(d, line, "body", w - x - 3 * r - pad, int(step * 0.9),
                                    start=min(int(h * 0.045), int(step * 0.45)), min_size=20)
            y0 = y - lh * len(rows) / 2
            for row in rows:
                d.text((x + 3 * r, y0), row, font=lf, fill=fg)
                y0 += lh

    elif card_type == "document":
        tf, tl, tlh = fit_text(d, title, "display", w - 2 * pad, int(h * 0.12), start=int(h * 0.06))
        for j, row in enumerate(tl):
            d.text((pad, pad + j * tlh), row, font=tf, fill=INK)
        y = pad + int(h * 0.16)
        for i, line in enumerate(lines):
            body, rows, lh = fit_text(d, line, "body", w - 2 * pad, int(h * 0.2), start=int(h * 0.042))
            if i == 0:  # highlight the key line
                d.rectangle([pad - 10, y - 6, w - pad, y + lh * len(rows) + 6], fill=YELLOW)
            for r in rows:
                d.text((pad, y), r, font=body, fill=INK)
                y += lh
            y += lh // 2
        d.text((w - pad, h - pad), "MAY RESIBO", font=font("display", int(h * 0.05)), fill=RED, anchor="rb")

    else:  # generic place card (no map data)
        tf, tl, tlh = fit_text(d, title.upper(), "display", w - 2 * pad, int(h * 0.3), start=int(h * 0.12))
        y = h * 0.45 - tlh * len(tl)
        for row in tl:
            d.text((w / 2, y), row, font=tf, fill=WHITE, anchor="mt")
            y += tlh
        if lines:
            lf, ll, llh = fit_text(d, " · ".join(lines), "body", w - 2 * pad, int(h * 0.15), start=int(h * 0.045))
            y += llh / 2
            for row in ll:
                d.text((w / 2, y), row, font=lf, fill=YELLOW, anchor="mt")
                y += llh

    return img

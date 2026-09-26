"""2.5D motion for illustrations (free; the base layer until AI image-to-video is switched on).

The subject is cut out with rembg (model `isnet-anime`, trained on drawn art), the hole it leaves in the
background is filled (OpenCV inpaint), and the two layers move separately: the camera move chosen by the
Visual Director with parallax (the subject moves ~1.8x the background), plus a subtle breathing scale and bob
on the subject so a shot is never a frozen picture. When no clear subject is found, it falls back to the plain
Ken-Burns move.
"""
from __future__ import annotations

import logging
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image

from ..config import channel
from .motion import write_clip

log = logging.getLogger(__name__)
OVERSCAN = 1.16                  # layers are drawn larger than the frame so they can move without edges


@lru_cache
def _session():
    from rembg import new_session
    return new_session(channel()["video"].get("cutout_model", "isnet-anime"))


def layers(image: Path) -> tuple[Image.Image, Image.Image] | None:
    """(background RGB, subject RGBA), cached next to the image. None when there is no clear subject."""
    fg_path, bg_path = image.with_suffix(".fg.png"), image.with_suffix(".bg.png")
    if fg_path.exists() and bg_path.exists():
        return Image.open(bg_path).convert("RGB"), Image.open(fg_path).convert("RGBA")
    if image.with_suffix(".nofg").exists():
        return None
    import cv2
    import numpy as np
    from rembg import remove

    src = Image.open(image).convert("RGB")
    fg = remove(src, session=_session(), post_process_mask=True).convert("RGBA")
    alpha = np.array(fg.getchannel("A"))
    cover = float((alpha > 128).mean())
    if not 0.04 <= cover <= 0.7:
        image.with_suffix(".nofg").write_text(f"{cover:.3f}")
        return None
    hole = cv2.dilate((alpha > 8).astype("uint8") * 255, np.ones((13, 13), "uint8"), iterations=3)
    small = 2 if max(src.size) > 900 else 1                     # inpaint at half size: fast, and it's hidden
    arr = np.array(src)[:, :, ::-1]
    filled = cv2.inpaint(cv2.resize(arr, None, fx=1 / small, fy=1 / small),
                         cv2.resize(hole, None, fx=1 / small, fy=1 / small, interpolation=cv2.INTER_NEAREST),
                         9, cv2.INPAINT_TELEA)
    filled = cv2.resize(filled, (arr.shape[1], arr.shape[0]))
    keep = (hole == 0)[:, :, None]
    bg = Image.fromarray(np.where(keep, arr, filled)[:, :, ::-1])
    bg.save(bg_path)
    fg.save(fg_path)
    return bg, fg


def _window(layer: Image.Image, size: tuple[int, int], zoom: float, ox: float, oy: float) -> Image.Image:
    """The part of an overscanned layer the camera sees, resized to the frame."""
    w, h = size
    lw, lh = layer.size
    k = lw / (w * OVERSCAN)                                    # layer px per frame px at zoom 1
    cw, ch = w * k / zoom, h * k / zoom
    cx, cy = lw / 2 - ox * k, lh / 2 - oy * k
    cx = min(max(cx, cw / 2), lw - cw / 2)
    cy = min(max(cy, ch / 2), lh - ch / 2)
    return layer.crop((int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2))).resize(
        size, Image.BILINEAR)


def _moves(motion: str, p: float, t: float, size: tuple[int, int]) -> tuple:
    """(bg zoom, bg dx, bg dy, fg zoom, fg dx, fg dy) at progress p / time t."""
    w, h = size
    breathe = 1 + 0.012 * math.sin(2 * math.pi * t / 2.6)
    bob = h * 0.005 * math.sin(2 * math.pi * t / 1.9)
    if motion == "push_in":
        zb, zf, dx = 1 + 0.05 * p, 1 + 0.1 * p, 0.0
    elif motion == "pull_out":
        zb, zf, dx = 1.05 - 0.05 * p, 1.1 - 0.1 * p, 0.0
    elif motion in ("pan_left", "pan_right"):
        sign = 1 if motion == "pan_left" else -1
        zb, zf, dx = 1.04, 1.06, sign * w * 0.035 * (p - 0.5) * 2
    elif motion == "shake":
        zb, zf, dx = 1.05, 1.07, w * 0.008 * math.sin(t * 38) * max(0.0, 1 - p * 2)
    else:                                                     # static and anything else: drift, never frozen
        zb, zf, dx = 1 + 0.02 * p, 1 + 0.035 * p, 0.0
    shake_y = h * 0.006 * math.cos(t * 31) * max(0.0, 1 - p * 2) if motion == "shake" else 0.0
    return zb, dx, shake_y, zf * breathe, dx * 1.8, bob + shake_y * 1.5


def parallax_clip(image: Path, frames: int, motion: str, size: tuple[int, int], fps: int, out: Path) -> bool:
    """Render the 2.5D clip. Returns False (caller falls back to Ken Burns) when there is no clear subject."""
    try:
        lay = layers(image)
    except Exception:
        log.exception("cut-out failed for %s", image.name)
        return False
    if not lay:
        return False
    bg, fg = lay
    w, h = size
    scale = max(w * OVERSCAN / bg.width, h * OVERSCAN / bg.height)
    target = (int(bg.width * scale) + 2, int(bg.height * scale) + 2)
    bg_big, fg_big = bg.resize(target, Image.LANCZOS), fg.resize(target, Image.LANCZOS)

    def gen():
        for i in range(frames):
            p, t = i / max(frames - 1, 1), i / fps
            zb, bx, by, zf, fx, fy = _moves(motion, p, t, size)
            frame = _window(bg_big, size, zb, bx, by).convert("RGBA")
            frame.alpha_composite(_window(fg_big, size, zf, fx, fy))
            yield frame

    write_clip(gen(), size, fps, out)
    return True

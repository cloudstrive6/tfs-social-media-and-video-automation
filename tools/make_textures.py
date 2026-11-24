"""TFS v2 textures: cream paper with fold creases and grain, and a green cutting mat with a grid (both made in code,
so they are owned). Writes ../build/textures/{paper,paper_v,mat,mat_v}.jpg. Run with a Python that has numpy and PIL:
D:/AI-Video/VoxCPM/.venv/Scripts/python.exe -I make_textures.py"""
import pathlib
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = pathlib.Path(__file__).resolve().parent.parent / "build" / "textures"
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)


def blur_noise(w, h, scale, sigma):
    small = rng.random((h // scale + 2, w // scale + 2)).astype(np.float32)
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(sigma))
    return np.asarray(img, dtype=np.float32) / 255.0


def paper(w, h, name):
    base = np.array([236, 227, 207], dtype=np.float32)
    mottle = (blur_noise(w, h, 40, 30) - 0.5) * 22 + (blur_noise(w, h, 6, 2) - 0.5) * 8
    fibre = (rng.random((h, w)).astype(np.float32) - 0.5) * 10
    img = np.clip(base + (mottle + fibre)[..., None], 0, 255)
    im = Image.fromarray(img.astype(np.uint8))
    d = ImageDraw.Draw(im, "RGBA")
    # fold creases: a soft shadow line beside a light line, one vertical and one horizontal
    for (x0, y0, x1, y1) in ((int(w * 0.52), 0, int(w * 0.505), h), (0, int(h * 0.47), w, int(h * 0.49))):
        for off, col in ((-2, (90, 70, 40, 38)), (2, (255, 252, 240, 60))):
            dx, dy = (off, 0) if x0 else (0, off)
            d.line((x0 + dx, y0 + dy, x1 + dx, y1 + dy), fill=col, width=3)
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    im.save(OUT / f"{name}.jpg", quality=92)


def mat(w, h, name):
    base = np.array([38, 92, 74], dtype=np.float32)
    mottle = (blur_noise(w, h, 30, 20) - 0.5) * 14 + (rng.random((h, w)).astype(np.float32) - 0.5) * 6
    im = Image.fromarray(np.clip(base + mottle[..., None], 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im, "RGBA")
    step = max(w, h) // 32
    for x in range(0, w, step):
        d.line((x, 0, x, h), fill=(210, 230, 215, 70 if (x // step) % 5 else 130), width=1 if (x // step) % 5 else 2)
    for y in range(0, h, step):
        d.line((0, y, w, y), fill=(210, 230, 215, 70 if (y // step) % 5 else 130), width=1 if (y // step) % 5 else 2)
    im.save(OUT / f"{name}.jpg", quality=92)


paper(1920, 1080, "paper"); paper(1080, 1920, "paper_v")
mat(1920, 1080, "mat"); mat(1080, 1920, "mat_v")
print("textures ->", OUT)

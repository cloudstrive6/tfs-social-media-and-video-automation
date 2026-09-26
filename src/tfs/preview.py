"""`tfs preview-styles`: one real sample per art style + a sample comic panel, for human approval."""
from __future__ import annotations

from pathlib import Path

from . import notify
from .characters import CAST, run as make_characters
from .config import ROOT, channel, data_dir
from .media import compose, images

SAMPLES = {
    "story": ("Kuya Standard standing on a flooded Manila street at dusk, calmly pointing at a brand-new "
              "concrete dike that is completely dry on the wrong side, Juan knee-deep in water looking confused", "16:9"),
    "satire": ("Tito Trapo cutting a ribbon on a tiny dike while a giant money bag labelled with a peso sign "
               "leaks coins behind him; ordinary citizens stand in floodwater watching", "4:5"),
    "comic": ("Two-panel comic moment: Juan asks a hard-hat contractor archetype where the pumping station is; "
              "the contractor proudly points at an empty lot with one lonely signpost", "4:5"),
    "archival": ("Spanish-colonial Intramuros, 1800s: a friar and a gobernadorcillo counting tribute coins by "
                 "candlelight while farmers wait outside the gate", "16:9"),
}


def run() -> list[str]:
    if not all((ROOT / "assets" / "characters" / f"{name}.png").exists() for name in CAST):
        make_characters()
    out_dir = data_dir() / "style_preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for style, spec in SAMPLES.items():
        prompt, aspect = spec if isinstance(spec, tuple) else (spec, "16:9")
        made.append(str(images.generate(prompt, out_dir / f"{style}.png", aspect, style=style)))
    handle = channel()["channel"]["handle"].lower()
    made.append(str(compose.panel_slide(2, 8, "Ang dike: ₱5.4B. Ang tubig: wala.", "Bagong-bago pa po 'yan, Sir!",
                                        "COA 2025 Annual Audit Report", out_dir / "satire.png",
                                        out_dir / "carousel_panel_sample.jpg", handle)))
    notify.send_photos([Path(m) for m in made], "🎨 Style preview: " + ", ".join(Path(m).stem for m in made))
    return made

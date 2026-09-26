"""`tfs make-characters`: model sheets for the recurring cast, saved to assets/characters/.

images.py attaches a sheet whenever a prompt names that character, which keeps designs consistent.
"""
from __future__ import annotations

from .config import ROOT
from .media import images

SHEET = ("Character model sheet on a plain warm-grey background: the same character shown three times side by "
         "side (front view, three-quarter view, side view), full body, neutral standing pose, consistent colours "
         "and proportions, soft even studio lighting, no background scenery. ")
CAST = {
    "kuya_standard": "Kuya Standard: calm, witty Filipino narrator in his 30s. Round bald head, dot eyes, slight "
                     "knowing smile, royal-blue barong-style shirt with red-and-yellow cuffs and rolled-up sleeves, "
                     "dark trousers, brown loafers.",
    "juan": "Juan: confused, good-hearted Filipino everyman in his 20s. Round head with messy black hair, big dot "
            "eyes, worried eyebrows, plain light-blue T-shirt, faded jeans shorts, rubber tsinelas.",
    "tito_trapo": "Tito Trapo: FICTIONAL corrupt-politician archetype (not any real person). Round head, slicked-back "
                  "shiny black hair, too-wide grin, tight cream barong tagalog over a round belly, red sash, oversized "
                  "gold watch and rings, polished black shoes.",
}


def run() -> list[str]:
    out_dir = ROOT / "assets" / "characters"
    out_dir.mkdir(parents=True, exist_ok=True)
    return [str(images.generate(SHEET + desc, out_dir / f"{name}.png", "16:9", style="story"))
            for name, desc in CAST.items()]

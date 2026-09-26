"""Illustration generator (Gemini image by default, OpenAI optional) with character reference sheets."""
from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path

from PIL import Image

from ..config import ROOT, channel, require_env

log = logging.getLogger(__name__)
CHAR_DIR = ROOT / "assets" / "characters"   # e.g. juan.png, tito_trapo.png, kuya_standard.png


def _references(prompt: str) -> list[Image.Image]:
    """Attach reference sheets for any recurring character named in the prompt (keeps designs consistent)."""
    if not CHAR_DIR.exists():
        return []
    lowered = prompt.lower().replace("_", " ")
    return [Image.open(p) for p in sorted(CHAR_DIR.glob("*.png"))
            if p.stem.replace("_", " ").lower() in lowered][:3]


def _gemini(prompt: str, aspect: str) -> bytes:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=require_env("GEMINI_API_KEY"))
    resp = client.models.generate_content(
        model=channel()["images"]["gemini_model"],
        contents=[prompt, *_references(prompt)],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"],
                                           image_config=types.ImageConfig(aspect_ratio=aspect)),
    )
    for part in resp.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data
    raise RuntimeError("Gemini returned no image (likely a safety block)")


def _openai(prompt: str, aspect: str) -> bytes:
    from openai import OpenAI

    size = {"16:9": "1536x1024", "9:16": "1024x1536", "4:5": "1024x1536", "1:1": "1024x1024"}[aspect]
    resp = OpenAI().images.generate(model=channel()["images"]["openai_model"], prompt=prompt, size=size)
    return base64.b64decode(resp.data[0].b64_json)


STYLES = ("story", "satire", "comic", "archival")


def full_prompt(prompt: str, style: str = "story") -> str:
    img = channel()["images"]
    style_text = img["styles"].get(style, img["styles"]["story"])
    return f"{prompt}\n\nArt style: {style_text}\n{img['base']}\nNever: {img['never']}"


def generate(prompt: str, out: Path, aspect: str = "16:9", style: str = "story", retries: int = 3) -> Path:
    if out.exists():
        return out
    full = full_prompt(prompt, style)
    fn = _openai if channel()["images"]["provider"] == "openai" else _gemini
    for attempt in range(retries):
        try:
            Image.open(io.BytesIO(fn(full, aspect))).convert("RGB").save(out)
            return out
        except Exception as e:
            log.warning("image attempt %s failed: %s", attempt + 1, e)
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"image generation failed for {out.name}")

"""Thumbnail Artist, Title Writer, SEO & Discovery Writer and Atlas Designer (style v2)."""
from __future__ import annotations

import json

from .. import llm
from ..config import channel
from ..models import Script, SeoPack, ThumbnailPlan, TitlePlan


def _ctx(item: dict, script: Script | None = None) -> str:
    d = item["data"]
    out = json.dumps({k: d.get(k) for k in ("working_title", "pillar", "primary_keyword", "brief", "owner_request")
                      if d.get(k)}, ensure_ascii=False)
    if script:
        out += "\n\n# Final script\n" + "\n".join(f"[{s.speaker}] {s.text}" for s in script.scenes)
    return out


def thumbnails(item: dict, script: Script) -> ThumbnailPlan:
    """A real frame from the finished video plus an optional English overlay (never generated art)."""
    return llm.structured("thumbnail_artist", _ctx(item, script), ThumbnailPlan)


def titles(item: dict, script: Script, thumb_moment: str) -> TitlePlan:
    kind = "YouTube Short" if item["kind"] == "vertical" else "YouTube long-form video"
    return llm.structured(
        "title_writer",
        f"Write titles for a {kind}. The chosen thumbnail shows: {thumb_moment}\n\n" + _ctx(item, script),
        TitlePlan,
    )


def seo(item: dict, script: Script | None, title: str, chapters: list[tuple[float, str]], extra: str = "") -> SeoPack:
    chapter_lines = "\n".join(f"{int(t // 60):02d}:{int(t % 60):02d} {name}" for t, name in chapters)
    links = channel()["channel"]["links"]
    pack = llm.structured(
        "seo_writer",
        f"Format: {item['kind']}\nFinal title: {title}\n"
        f"Chapter start times (long-form only):\n{chapter_lines or '(none)'}\n"
        f"Channel links: {json.dumps(links)}\n"
        f"Sources:\n" + "\n".join(script.sources if script else []) + "\n\n" + _ctx(item, script) + extra,
        SeoPack,
    )
    from ..publish.limits import enforce_seo
    return enforce_seo(pack)


def atlas_plan(item: dict, script: Script, dossier: str, vertical: bool, notes: str = "") -> "AtlasPlan":
    """Atlas Designer (style v2): maps, real photos, documents, cards and charts for every scene, each cutaway
    anchored on the word it shows."""
    from ..models import AtlasPlan

    fmt = ("Format: 9:16 Short (35 to 58 s). Keep text short; at least one real photo every 12 s."
           if vertical else "Format: 16:9 long-form. At least one real photo every 20 s; one hero shot at most.")
    return llm.structured(
        "atlas_designer",
        f"{fmt}\n\n{_ctx(item)}\n\n"
        f"# Script (final, fact-checked; one AtlasScene per scene id, at_word copied from that scene's text)\n"
        f"{script.model_dump_json()}\n\n# Dossier (exact law text for doc shots, facts for cards)\n{dossier[:30000]}"
        + (f"\n\n# Review team notes on the last render: fix these scenes{notes}" if notes else ""),
        AtlasPlan,
    )

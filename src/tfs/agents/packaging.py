"""Thumbnail Artist, Title Writer, SEO & Discovery Writer, Visual Director, Carousel Designer."""
from __future__ import annotations

import json

from .. import llm
from ..config import channel
from ..models import Carousel, Script, SeoPack, ShotList, ThumbnailPlan, TitlePlan


def _ctx(item: dict, script: Script | None = None) -> str:
    d = item["data"]
    out = json.dumps({k: d.get(k) for k in ("working_title", "pillar", "primary_keyword", "brief")},
                     ensure_ascii=False)
    if script:
        out += "\n\n# Final script\n" + "\n".join(f"[{s.speaker}] {s.text}" for s in script.scenes)
    return out


def thumbnails(item: dict, script: Script) -> ThumbnailPlan:
    return llm.structured(
        "thumbnail_artist",
        f"Channel style prompt to include in every image_prompt:\n{channel()['images']['style_prompt']}\n\n"
        + _ctx(item, script),
        ThumbnailPlan,
    )


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
    return llm.structured(
        "seo_writer",
        f"Format: {item['kind']}\nFinal title: {title}\n"
        f"Chapter start times (long-form only):\n{chapter_lines or '(none)'}\n"
        f"Channel links: {json.dumps(links)}\n"
        f"Sources:\n" + "\n".join(script.sources if script else []) + "\n\n" + _ctx(item, script) + extra,
        SeoPack,
    )


def shot_list(item: dict, script: Script) -> ShotList:
    return llm.structured(
        "visual_director",
        f"Format: {item['kind']}\nChannel style prompt (prepend to every image_prompt):\n"
        f"{channel()['images']['style_prompt']}\nNever: {channel()['images']['never']}\n\n"
        "Return exactly one shot per scene id.\n\n# Scenes\n" + script.model_dump_json(),
        ShotList,
    )


def carousel(item: dict, dossier: str) -> Carousel:
    return llm.structured(
        "carousel_designer",
        f"Language: {channel()['channel']['language']}\nChannel style prompt for image_prompt fields:\n"
        f"{channel()['images']['style_prompt']}\n\n{_ctx(item)}\n\n# Dossier\n{dossier}",
        Carousel,
    )

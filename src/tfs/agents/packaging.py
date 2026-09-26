"""Thumbnail Artist, Title Writer, SEO & Discovery Writer, Visual Director, Carousel Designer."""
from __future__ import annotations

import json

from .. import llm
from ..config import channel
from ..models import Carousel, Script, SeoPack, ShotList, ThumbnailPlan, TitlePlan


def _style_kit() -> str:
    img = channel()["images"]
    styles = "\n".join(f"- {name}: {text}" for name, text in img["styles"].items())
    return f"Style kit (pick one per image):\n{styles}\nShared rules: {img['base']}\nNever: {img['never']}"


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
        "Thumbnails use the 'story' style (or 'satire' for pure political commentary). Describe the scene only;\n"
        "the style text is appended automatically.\n" + _style_kit() + "\n\n" + _ctx(item, script),
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
        f"Format: {item['kind']}\n{_style_kit()}\n\n"
        "Describe only the scene in image_prompt (subject, action, expression, setting, camera); the style text is "
        "appended automatically from the `style` you choose. Return exactly one shot per scene id.\n\n# Scenes\n"
        + script.model_dump_json(),
        ShotList,
    )


def carousel(item: dict, dossier: str) -> Carousel:
    return llm.structured(
        "carousel_designer",
        f"Language: {channel()['channel']['language']}\n{_style_kit()}\n"
        "For slide art, describe the scene only and set `style`.\n\n"
        f"{_ctx(item)}\n\n# Dossier\n{dossier}",
        Carousel,
    )

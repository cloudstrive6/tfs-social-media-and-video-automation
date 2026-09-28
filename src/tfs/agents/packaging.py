"""Thumbnail Artist, Title Writer, SEO & Discovery Writer, Carousel Designer, Motion Designer, Visual Critic
(and the older Visual Director / Pre-flight Art Director)."""
from __future__ import annotations

import json
from pathlib import Path

from .. import llm
from ..config import channel
from ..models import Carousel, Script, SeoPack, ShotList, ThumbnailPlan, TitlePlan


def _style_kit() -> str:
    img = channel()["images"]
    styles = "\n".join(f"- {name}: {text}" for name, text in img["styles"].items())
    return f"Style kit (pick one per image):\n{styles}\nShared rules: {img['base']}\nNever: {img['never']}"


def _vocabulary() -> str:
    from ..media import vector
    return vector.vocabulary()


def _ctx(item: dict, script: Script | None = None) -> str:
    d = item["data"]
    out = json.dumps({k: d.get(k) for k in ("working_title", "pillar", "primary_keyword", "brief", "owner_request")
                      if d.get(k)}, ensure_ascii=False)
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


def shot_list(item: dict, script: Script) -> ShotList:
    return llm.structured(
        "visual_director",
        f"Format: {item['kind']}\n{_style_kit()}\n\n"
        "Describe only the scene in image_prompt (subject, action, expression, setting, camera); the style text is "
        "appended automatically from the `style` you choose. Return exactly one shot per scene id.\n\n# Scenes\n"
        + script.model_dump_json(),
        ShotList,
    )


def preflight_shots(item: dict, script: Script, shots: ShotList, dossier: str) -> ShotList:
    """Pre-flight Art Director: fixes the shot list against the house rules before any image is generated."""
    return llm.structured(
        "preflight_art",
        f"Format: {item['kind']}\n\n# Script (final, fact-checked)\n{script.model_dump_json()}\n\n"
        f"# Shot list to check\n{shots.model_dump_json()}\n\n# Dossier (for card facts)\n{dossier[:30000]}",
        ShotList,
    )


def sound_plan(item: dict, script: Script, shots: ShotList, library: str) -> "SoundPlan":
    from ..models import SoundPlan

    brief = [{"scene_id": sc.id, "chapter": sc.chapter, "text": sc.text,
              "shot": next((f"{s.kind}:{s.card_type}" if s.kind == "card" else s.kind
                            for s in shots.shots if s.scene_id == sc.id), "")} for sc in script.scenes]
    return llm.structured(
        "sound_designer",
        f"Format: {item['kind']}\nLibrary: {library}\n\n# Scenes\n" + json.dumps(brief, ensure_ascii=False),
        SoundPlan,
    )


def _format_note(kind: str) -> str:
    if kind == "vertical":
        return ("Format: vertical 9:16 (Shorts/Reels/TikTok). Faces, bubbles and props sit in the top 58% of the "
                "frame: captions and platform buttons cover the rest.")
    if kind == "long_form":
        return "Format: YouTube long-form, 16:9."
    return f"Format: {kind}."


def motion_plan(item: dict, script: Script, dossier: str) -> "MotionPlan":
    """Motion Designer: every scene as a set, cast, props, bubble or animated card for the vector engine."""
    from ..media import vector
    from ..models import MotionPlan

    return llm.structured(
        "motion_designer",
        f"{_format_note(item['kind'])}\n\n# Vocabulary\n{vector.vocabulary()}\n\n{_ctx(item)}\n\n"
        f"# Script (final, fact-checked; one ScenePlan per scene id)\n{script.model_dump_json()}\n\n"
        f"# Dossier (for card facts)\n{dossier[:30000]}",
        MotionPlan,
    )


def motion_revise(item: dict, script: Script, plan: "MotionPlan", notes: dict[int, list[str]],
                  dossier: str) -> "MotionPlan":
    """Motion Designer, second pass: fix the scenes the Visual Critic (or the review team) flagged."""
    from ..media import vector
    from ..models import MotionPlan

    flagged = "\n".join(f"- scene {sid}: " + " / ".join(p) for sid, p in sorted(notes.items()))
    return llm.structured(
        "motion_designer",
        f"{_format_note(item['kind'])}\n\n# Vocabulary\n{vector.vocabulary()}\n\n"
        f"# Script\n{script.model_dump_json()}\n\n# Current plan\n{plan.model_dump_json()}\n\n"
        f"# Critic notes: fix these scenes, keep every other scene exactly as it is\n{flagged}\n\n"
        f"# Dossier (for card facts)\n{dossier[:20000]}",
        MotionPlan,
    )


def motion_stills(item: dict, briefs: list[str], purpose: str) -> "MotionPlan":
    """Motion Designer for single images (thumbnail, carousel art): one ScenePlan per brief, scene_id = index."""
    from ..media import vector
    from ..models import MotionPlan

    listing = "\n".join(f"- scene_id {i}: {b}" for i, b in enumerate(briefs))
    return llm.structured(
        "motion_designer",
        f"Format: {purpose}. Each scene is ONE still image, not a video: pick the single most telling moment, "
        "use `kind: scene` (no cards), `enter: none`, and a bubble only if the brief quotes one. Keep the "
        "subject large and clear (scale 0.65–0.75 in wide frames). Vary the sets: never the same background on "
        f"two stills in a row, and no set more than twice.\n\n# Vocabulary\n{vector.vocabulary()}\n\n{_ctx(item)}\n\n"
        f"# Stills to design\n{listing}",
        MotionPlan,
    )


def visual_critique(item: dict, script: Script, plan: "MotionPlan", stills: list, dossier: str) -> "VisualCritique":
    """Visual Critic: one mid-scene still per scene, checked before the full render. Batched, in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    from ..media import vector
    from ..models import VisualCritique

    lines = {sc.id: sc.text for sc in script.scenes}
    batches = [list(zip(plan.scenes, stills))[i:i + 10] for i in range(0, len(plan.scenes), 10)]

    def look(batch) -> VisualCritique:
        brief = [{"scene_id": sp.scene_id, "file": Path(img).name, "line": lines.get(sp.scene_id, ""),
                  "plan": sp.model_dump(exclude={"scene_id"})} for sp, img in batch]
        return llm.structured_with_images(
            "visual_critic",
            f"{_format_note(item['kind'])}\n\n# What the engine can draw\n{vector.vocabulary()}\n\n"
            "# Stills (answer once per scene_id)\n" + json.dumps(brief, ensure_ascii=False, indent=1)
            + f"\n\n# Dossier (for card facts)\n{dossier[:15000]}",
            [img for _, img in batch], VisualCritique)

    with ThreadPoolExecutor(max_workers=3) as pool:
        parts = list(pool.map(look, batches))
    return VisualCritique(scenes=[s for p in parts for s in p.scenes], notes=[n for p in parts for n in p.notes])


def preflight_carousel(item: dict, car: Carousel, dossier: str) -> Carousel:
    """Pre-flight Art Director for carousels: image prompts + slide text checked before anything is drawn."""
    return llm.structured(
        "preflight_art",
        "Format: carousel (Instagram/Facebook, 4:5 slides; slide 0 is the cover). Check every slide's "
        "`image_prompt` with the illustration rules and every slide's `headline`, `body` and `source` with the "
        "card rules (facts against the dossier, English, naming policy). Keep the same number of slides, in order."
        f"\n\n# What the cartoon engine can draw\n{_vocabulary()}"
        f"\n\n# Slides to check\n{car.model_dump_json()}\n\n# Dossier\n{dossier[:30000]}",
        Carousel,
    )


def carousel(item: dict, dossier: str) -> Carousel:
    return llm.structured(
        "carousel_designer",
        "Language: original English (written natively, never translated from Taglish).\n\n"
        "# What the cartoon engine can draw (slide art)\n"
        f"{_vocabulary()}\n\n{_ctx(item)}\n\n# Dossier\n{dossier}",
        Carousel,
    )

"""Thumbnail Artist, Title Writer, SEO & Discovery Writer and Atlas Designer (style v2)."""
from __future__ import annotations

import json

from .. import llm
from ..config import channel
from ..models import PackagingCheck, Script, SeoPack, ThumbnailPlan, TitlePlan


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


def check_packaging(script: Script, dossier: str, thumbnail_text: str, titles: TitlePlan,
                    pack: SeoPack) -> PackagingCheck:
    """Packaging Legal & Fact Check: titles, thumbnail text and captions are written after the fact-checker
    cleared the script and are what most people read, so they get the same naming policy (2026-11-27). There is
    no fallback: if the check cannot run, the piece fails and nothing is booked."""
    from ..publish.limits import enforce_seo

    current = PackagingCheck(thumbnail_text=thumbnail_text, title=titles.primary, alternates=titles.alternates,
                             seo=pack)
    ask = (f"# Script (final, fact-checked)\n{script.model_dump_json()}\n\n# Packaging to check\n"
           f"{current.model_dump_json()}\n\n# Dossier (the only evidence)\n{dossier[:30000]}")
    checked = llm.structured("packaging_checker", ask, PackagingCheck)
    lost = _lost_lines(pack, checked.seo)
    if lost and not checked.unsafe:                 # links and chapter lines are format, never content: one retry
        checked = llm.structured("packaging_checker", ask + "\n\n# Your last answer dropped these; keep them exactly:\n"
                                 + "\n".join(lost), PackagingCheck)
        lost = _lost_lines(pack, checked.seo)
    if checked.unsafe:
        raise ValueError(f"packaging cannot be made safe: {'; '.join(checked.issues)[:500]}")
    if lost:
        raise ValueError(f"packaging check dropped links or chapter lines: {lost[:5]}")
    if not checked.title.strip():                  # an empty title would be a broken upload, never a safe one
        raise ValueError("packaging check returned an empty title")
    return checked.model_copy(update={"seo": enforce_seo(checked.seo),
                                      "thumbnail_text": checked.thumbnail_text if thumbnail_text else ""})


def _lost_lines(before: SeoPack, after: SeoPack) -> list[str]:
    """URLs anywhere in the captions, and YouTube chapter lines, that the check removed."""
    import re

    def urls(p: SeoPack) -> set[str]:
        text = " ".join([p.youtube_description, p.instagram_caption, p.facebook_caption, p.tiktok_caption])
        return {u.rstrip(".,)") for u in re.findall(r"https?://\S+", text)}

    def chapters(p: SeoPack) -> set[str]:
        return set(re.findall(r"(?m)^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s", p.youtube_description))

    return sorted(urls(before) - urls(after)) + sorted(chapters(before) - chapters(after))


def atlas_plan(item: dict, script: Script, dossier: str, vertical: bool, notes: str = "") -> "AtlasPlan":
    """Atlas Designer (style v2): maps, real photos, documents, cards and charts for every scene, each cutaway
    anchored on the word it shows."""
    from ..models import AtlasPlan

    fmt = ("Format: 9:16 Short (35 to 58 s). Keep text short; at least one real photo every 12 s."
           if vertical else "Format: 16:9 long-form. At least one real photo every 20 s; one hero shot at most.")
    plan = llm.structured(
        "atlas_designer",
        f"{fmt}\n\n{_ctx(item)}\n\n"
        f"# Script (final, fact-checked; one AtlasScene per scene id, at_word copied from that scene's text)\n"
        f"{script.model_dump_json()}\n\n# Dossier (exact law text for doc shots, facts for cards)\n{dossier[:30000]}"
        + (f"\n\n# Review team notes on the last render: fix these scenes{notes}" if notes else ""),
        AtlasPlan,
    )
    return check_screen_text(plan, script, dossier)


# Text fields an on-screen check may rewrite; everything else (kinds, timing words, layout, numbers to plot) is kept
SHOT_TEXT = ("text", "sub", "kicker", "head", "sec", "body", "hl", "src", "label", "left", "right", "foot", "word",
             "stamp", "big", "small", "callout", "name", "role")
ITEM_TEXT = ("big", "small", "label", "value", "date", "text")
SIDE_TEXT = ("name", "big", "small")


def merge_screen_text(plan, checked):
    """The checked plan's text on the designer's structure. None if the structure changed (then the check is
    ignored and the designer's plan is used)."""
    if [s.scene_id for s in plan.scenes] != [s.scene_id for s in checked.scenes]:
        return None
    scenes = []
    for sc, ck in zip(plan.scenes, checked.scenes):
        if [s.k for s in sc.shots] != [s.k for s in ck.shots]:
            return None
        shots = []
        for s, c in zip(sc.shots, ck.shots):
            upd = {f: getattr(c, f) for f in SHOT_TEXT}
            for lst in ("items", "rows", "chips"):
                mine, theirs = getattr(s, lst), getattr(c, lst)
                if len(mine) == len(theirs):
                    upd[lst] = [m.model_copy(update={f: getattr(t, f) for f in ITEM_TEXT}) for m, t in zip(mine, theirs)]
            for side in ("ph", "nz"):
                upd[side] = getattr(s, side).model_copy(update={f: getattr(getattr(c, side), f) for f in SIDE_TEXT})
            shots.append(s.model_copy(update=upd))
        scenes.append(sc.model_copy(update={"shots": shots}))
    return plan.model_copy(update={"scenes": scenes})


def check_screen_text(plan, script: Script, dossier: str):
    """On-Screen Fact Check: every card, stamp, label and badge must be as true as the fact-checked narration
    (2026-11-25: a closing card said "no legal channel" after the fact-checker had removed that claim from the
    script). A failed or structure-changing check keeps the designer's plan."""
    import logging

    from ..llm import UsageLimitError
    from ..models import AtlasPlan

    try:
        checked = llm.structured(
            "screen_checker",
            f"# Script (final, fact-checked)\n{script.model_dump_json()}\n\n# Shot plan to check\n{plan.model_dump_json()}"
            f"\n\n# Dossier (the only evidence)\n{dossier[:30000]}",
            AtlasPlan,
        )
    except UsageLimitError:
        raise
    except Exception:
        logging.getLogger(__name__).exception("on-screen fact check failed; using the designer's plan")
        return plan
    merged = merge_screen_text(plan, checked)
    if merged is None:
        logging.getLogger(__name__).warning("on-screen fact check changed the plan's structure; ignored")
        return plan
    return merged

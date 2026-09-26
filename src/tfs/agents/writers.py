"""Researcher -> Head Writer -> Hook Master -> Fact-Check & Legal."""
from __future__ import annotations

import json

from .. import llm
from ..config import channel
from ..models import FactCheck, HookReview, Script


def _brief(item: dict) -> str:
    d = item["data"]
    return json.dumps({k: d.get(k) for k in ("working_title", "pillar", "primary_keyword", "brief", "topic")},
                      ensure_ascii=False, default=str)


WORDS_PER_SECOND = 1.8          # Josh at speed 1.1, Taglish with numbers written out as words


def max_words(kind: str) -> int:
    """Spoken-word ceiling for a format (None-like 10**6 for long form, which is bounded by minutes)."""
    if kind == "vertical":
        return int(channel()["video"]["vertical"]["target_seconds"][1] * WORDS_PER_SECOND)
    return 10 ** 6


def spoken_words(script: Script) -> int:
    from ..media.tts import clean
    return sum(len(clean(s.text, keep_audio_tags=False).split()) for s in script.scenes)


def _length(kind: str) -> str:
    v = channel()["video"]
    if kind == "long_form":
        lo, hi = v["long_form"]["target_minutes"]
        return f"long-form narration of {lo}-{hi} minutes (~{lo * 150}-{hi * 150} spoken words)"
    if kind == "vertical":
        lo, hi = v["vertical"]["target_seconds"]
        return (f"vertical video narration of {lo}-{hi} seconds: HARD LIMIT {max_words(kind)} spoken words in total "
                f"(the narrator reads Taglish at ~{WORDS_PER_SECOND} words per second; aim for {int(lo * WORDS_PER_SECOND)}-"
                f"{max_words(kind)})")
    return "carousel (no narration)"


def research(item: dict) -> str:
    depth = 25 if item["kind"] == "long_form" else 10
    return llm.research(
        "researcher",
        f"Build the dossier for this piece:\n{_brief(item)}\n\n"
        "Search broadly (English and Filipino sources), then write the dossier in the required format.",
        max_searches=depth,
    )


def write_script(item: dict, dossier: str, issue_number: int, feedback: str = "") -> Script:
    return llm.structured(
        "scriptwriter",
        f"Write a {_length(item['kind'])} in `{channel()['channel']['language']}`.\n"
        f"Issue number: {issue_number}\nBrief:\n{_brief(item)}\n\n# Dossier\n{dossier}"
        + (f"\n\n# Editor feedback on the previous draft — fix all of it\n{feedback}" if feedback else ""),
        Script,
    )


def hook_pass(item: dict, script: Script) -> HookReview:
    return llm.structured(
        "hook_master",
        f"Format: {_length(item['kind'])}\nBrief:\n{_brief(item)}\n\n# Script\n{script.model_dump_json()}",
        HookReview,
    )


def fact_check(script: Script, dossier: str, kind: str = "") -> FactCheck:
    fmt = f"# Format\n{_length(kind)}\n\n" if kind in ("long_form", "vertical") else ""
    return llm.structured(
        "fact_checker",
        f"{fmt}# Dossier (the only evidence you may rely on)\n{dossier}\n\n# Script\n{script.model_dump_json()}",
        FactCheck,
    )


def narration_edit(script: Script) -> Script:
    """Narration Editor: numbers/dates/acronyms as spoken, no emphasis hyphens, no word split across scenes."""
    edited = llm.structured("narration_editor", f"# Script\n{script.model_dump_json()}", Script)
    ids = [s.id for s in script.scenes]
    if [s.id for s in edited.scenes] != ids:        # must be the same scenes; otherwise keep the original
        return script
    return edited

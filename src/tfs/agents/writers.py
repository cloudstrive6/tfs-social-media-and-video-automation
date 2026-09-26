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


def _length(kind: str) -> str:
    v = channel()["video"]
    if kind == "long_form":
        lo, hi = v["long_form"]["target_minutes"]
        return f"long-form narration of {lo}-{hi} minutes (~{lo * 150}-{hi * 150} spoken words)"
    if kind == "vertical":
        lo, hi = v["vertical"]["target_seconds"]
        return f"vertical video narration of {lo}-{hi} seconds (~{lo * 2.6:.0f}-{hi * 2.6:.0f} words)"
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


def fact_check(script: Script, dossier: str) -> FactCheck:
    return llm.structured(
        "fact_checker",
        f"# Dossier (the only evidence you may rely on)\n{dossier}\n\n# Script\n{script.model_dump_json()}",
        FactCheck,
    )

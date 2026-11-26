"""Researcher -> Head Writer -> Hook Master -> Fact-Check & Legal."""
from __future__ import annotations

import json
import logging
import re

from .. import llm
from ..config import channel
from ..models import FactCheck, HookReview, Script
from ..taglish_lint import TL_BARE, TL_NUM, TL_ORD, script_problems

log = logging.getLogger(__name__)


def _brief(item: dict) -> str:
    d = item["data"]
    return json.dumps({k: d.get(k) for k in ("working_title", "pillar", "primary_keyword", "brief", "topic",
                                           "owner_request") if d.get(k)},
                      ensure_ascii=False, default=str)


WORDS_PER_SECOND = 1.8          # Taglish narration pace, numbers read in English


def max_words(kind: str) -> int:
    """Spoken-word ceiling for a format."""
    v = channel()["video"]
    if kind == "vertical":
        return int(v["vertical"]["target_seconds"][1] * WORDS_PER_SECOND)
    if kind == "long_form":
        return int(v["long_form"]["target_minutes"][1] * 60 * WORDS_PER_SECOND)
    return 10 ** 6


def min_words(kind: str) -> int:
    """Spoken-word floor (long-form must reach its minimum length)."""
    if kind == "long_form":
        return int(channel()["video"]["long_form"]["target_minutes"][0] * 60 * WORDS_PER_SECOND)
    return 0


def spoken_words(script: Script) -> int:
    from ..media.tts import clean
    return sum(len(clean(s.text, keep_audio_tags=False).split()) for s in script.scenes)


def _length(kind: str) -> str:
    v = channel()["video"]
    if kind == "long_form":
        lo, hi = v["long_form"]["target_minutes"]
        return (f"long-form narration of {lo}-{hi} minutes: between {min_words(kind)} and {max_words(kind)} spoken "
                f"words in total (the narrator reads ~{WORDS_PER_SECOND} words per second); both limits are hard")
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


def fact_check(script: Script, dossier: str, kind: str = "", hook_text: str = "") -> FactCheck:
    fmt = f"# Format\n{_length(kind)}\n\n" if kind in ("long_form", "vertical") else ""
    if kind == "carousel":
        fmt = ("# Format\nInstagram/Facebook carousel: each scene is one slide's headline and body, written in "
               "original English. Change wording only where a fact, a name or a legal rule requires it, and keep any "
               "rewrite in natural, complete English sentences (never Taglish, never clipped fragments). Keep "
               "*asterisk* highlights around the same phrase.\n\n")
    if hook_text:
        fmt += f"# On-screen hook text (check it too; return it corrected in on_screen_hook_text)\n{hook_text}\n\n"
    return llm.structured(
        "fact_checker",
        f"{fmt}# Dossier (the only evidence you may rely on)\n{dossier}\n\n# Script\n{script.model_dump_json()}",
        FactCheck,
    )


_TAG = re.compile(r"\[S\d+[a-z]?\]")
_DIGITS = re.compile(r"\d[\d,.]*\d|\d")
_TL_SMALL = ({w.split()[0]: n for n, w in TL_NUM.items()} | {w.split()[0]: n for n, w in TL_ORD.items()}
             | {w: n for n, w in TL_BARE.items()} | {"ika" + w: n for n, w in TL_BARE.items() if n > 1}
             | {"una": 1, "ikalawa": 2, "ikatlo": 3})
_TL_SMALL_RX = re.compile(r"\b(" + "|".join(sorted(_TL_SMALL, key=len, reverse=True)) + r")\b", re.I)
_SMALL_TOKEN = re.compile(r"\d[\d,.]*\d|\d|\b[A-Za-z]+\b")


def _big(text: str) -> list[str]:
    """Numbers that must survive a language-only retry exactly: everything but a bare 1 to 10."""
    return sorted(d for d in _DIGITS.findall(text) if not (d.isdigit() and 1 <= int(d) <= 10))


def _small(text: str) -> list[int]:
    """Small counts in order, as digits or Tagalog numerals ("7", "pitong", "ikapito" are all 7), so a retry may
    spell a small count out (Bryce, 2026-11-26) but may not drop, change or swap one."""
    out = []
    for tok in _SMALL_TOKEN.findall(text):
        if tok.isdigit() and 1 <= int(tok) <= 10:
            out.append(int(tok))
        elif tok.lower() in _TL_SMALL:
            out.append(_TL_SMALL[tok.lower()])
    return out


def _same_small(x: str, y: str) -> bool:
    """Counts other than 1 match in order; 1s may only be added ("isang" and "unang" are also plain words)."""
    a, b = _small(x), _small(y)
    return [n for n in a if n != 1] == [n for n in b if n != 1] and b.count(1) >= a.count(1)


def _same_content(a: Script, b: Script) -> bool:
    """A language-only retry: same sources, and per scene the same id, chapter, speaker, visual, [S#] tags and
    numbers, with no sentence dropped (at least 80% of the words kept). Fact-checked content cannot change."""
    if a.sources != b.sources or len(a.scenes) != len(b.scenes):
        return False
    for x, y in zip(a.scenes, b.scenes):
        if (x.id, x.chapter, x.speaker, x.visual) != (y.id, y.chapter, y.speaker, y.visual):
            return False
        if _TAG.findall(x.text) != _TAG.findall(y.text):
            return False
        if _big(x.text) != _big(y.text) or not _same_small(x.text, y.text):
            return False
        if len(y.text.split()) < 0.8 * len(x.text.split()):
            return False
    return True


def narration_edit(script: Script) -> Script:
    """Narration Editor: numbers/dates/acronyms as spoken, no emphasis hyphens, no word split across scenes.
    Then the Taglish lint (Bryce, 2026-11-25: "Sa 7 buwan ng 2026"): if the edit still has unnatural patterns,
    one more pass with the problems listed; the retry is kept only if it keeps the scenes and has fewer problems.
    What remains is logged, never fatal."""
    ids = [s.id for s in script.scenes]
    edited = llm.structured("narration_editor", f"# Script\n{script.model_dump_json()}", Script)
    if [s.id for s in edited.scenes] != ids:        # must be the same scenes; otherwise keep the original
        return script
    problems = script_problems([s.text for s in edited.scenes])
    if not problems:
        return edited
    feedback = "\n".join(f"- {p}" for p in problems)
    try:
        retry = llm.structured(
            "narration_editor",
            f"# Script\n{edited.model_dump_json()}\n\n# Unnatural Taglish still in this script: fix each one "
            f"(rules 7 to 10), change nothing else\n{feedback}",
            Script,
        )
    except Exception as e:                          # the first edit is good enough to keep; never lose it here
        log.warning("narration: Taglish retry failed (%s); keeping the first edit", e)
        retry = None
    if retry is not None and _same_content(edited, retry):
        left = script_problems([s.text for s in retry.scenes])
        if len(left) < len(problems):
            edited, problems = retry, left
    if problems:
        log.warning("narration: Taglish lint left %d problem(s): %s", len(problems), "; ".join(problems))
    return edited

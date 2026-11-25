"""Machine checks for Taglish that a Filipino listener hears as unnatural (Bryce, 2026-11-25: "Sa 7 buwan ng 2026"
is not how anyone says it). The narrator reads digits in English (`tts_voxcpm.spoken`), so a digit must sit next
to words that go with an English number. Guide with sources: Bryce-Brain wiki/answers/tfs-natural-taglish-2026-11.md.

Each problem is a short string naming the words and the fix, so it can go back to a writer as feedback.
"""
from __future__ import annotations

import re

_SRC = re.compile(r"\[S\d+[a-z]?\]")
# Tagalog time units: an English number is never followed by these ("seven buwan" is wrong; "7 months" or
# "pitong buwan" are natural; TFS writes "7 months").
_TL_UNITS = {"segundo": "seconds", "minuto": "minutes", "oras": "hours", "araw": "days", "linggo": "weeks",
             "buwan": "months", "taon": "years", "dekada": "decades", "siglo": "centuries"}
_DIGIT_TL_UNIT = re.compile(r"(?<![\w.,])(\d[\d,.]*)\s+(?:na\s+)?(" + "|".join(_TL_UNITS) + r")\b", re.I)
# "sa 7 months ng 2026" or "sa 7 months": no "loob ng", "unang" or "first", so it reads as a garbled date.
# "sa 6 years na termino" (a span used as a modifier) is fine.
_BARE_SPAN = re.compile(r"\bsa\s+(\d+)\s+(months|weeks|days|years|hours|buwan|linggo|araw|taon|oras)\b"
                        r"(?!\s+na\b)(?:\s+ng\s+\d{4})?", re.I)
_IKA_DIGIT = re.compile(r"\bika-?\s?\d+", re.I)
_TL_SCALE = re.compile(r"\d[\d,.]*\s*(trilyon|trilyong|bilyon|bilyong|milyon|milyong)\b", re.I)
_PORSYENTO = re.compile(r"\d[\d,.]*\s*(porsyento|porsiyento|bahagdan)\b", re.I)
_TL_MONTHS = ("Enero Pebrero Marso Abril Mayo Hunyo Hulyo Agosto Setyembre Oktubre Nobyembre Disyembre").split()
_EN_MONTHS = ("January February March April May June July August September October November December").split()
_TL_MONTH_DIGIT = re.compile(r"\b(" + "|".join(_TL_MONTHS) + r")\s+\d+|\d+\s+(?:ng\s+)?(" + "|".join(_TL_MONTHS) + r")\b")
# A yes or no question that opens with a bare root verb ("Bayaran mo ba iyon?") where Tagalog needs the
# aspect form ("Babayaran mo ba iyon?"). After "kailangan", "dapat", "pwede" the root form is right.
_ROOT_Q = re.compile(r"(?:^|[.?!]\s+|,\s+)([A-Za-z]+(?:an|in|han|hin))\s+"
                     r"(?:(mo|ko|natin|namin|ninyo|nila|niya|nyo|iyon|ito)\s+)?(?:ba|bang)\b")
_NOT_VERBS = {"saan", "nasaan", "kailan", "kanino", "ilan", "alin", "kailangan", "pwedeng", "dahilan", "ngayon",
              "naman", "lamang", "tayo", "kasalanan", "pamahalaan", "bayan", "batasan", "halalan", "kalaban",
              "paaralan", "simbahan", "hukuman", "lungsod", "senador", "ganoon", "ganiyan"}


def _is_root(word: str) -> bool:
    w = word.lower()
    if w in _NOT_VERBS or len(w) < 5:
        return False
    if w[:2] == w[2:4]:                                   # reduplicated: babayaran, gagawin (contemplated)
        return False
    if w[1:3] == "in" or w.startswith("in"):              # infix -in-: binayaran, ginawa, inaprubahan (completed)
        return False
    if w.startswith(("ma", "na", "pa", "ka", "nag", "mag", "pag", "i")):   # affixed forms, not a bare root
        return False
    return True


def problems(text: str) -> list[str]:
    """Unnatural Taglish patterns in one narration line (source tags ignored)."""
    t = _SRC.sub("", text)
    out = []
    for m in _DIGIT_TL_UNIT.finditer(t):
        out.append(f'"{m.group(0)}": an English number takes an English unit, write "{m.group(1)} '
                   f'{_TL_UNITS[m.group(2).lower()]}"')
    for m in _BARE_SPAN.finditer(t):
        n, unit = m.group(1), m.group(2).lower()
        unit = _TL_UNITS.get(unit, unit)
        out.append(f'"{m.group(0)}": say which span, "sa loob ng {n} {unit}" (add "ng <year>" if needed) or '
                   f'"mula <month> hanggang <month> <year>"')
    for m in _IKA_DIGIT.finditer(t):
        out.append(f'"{m.group(0)}": the narrator would say "ika-" plus an English number; write "7th" style '
                   f'("sa 7th month") or a date')
    for m in _TL_SCALE.finditer(t):
        out.append(f'"{m.group(0)}": digits take English scale words (trillion, billion, million)')
    for m in _PORSYENTO.finditer(t):
        out.append(f'"{m.group(0)}": write the percent sign ("55.9%"), read as "percent"')
    for m in _TL_MONTH_DIGIT.finditer(t):
        tl = m.group(1) or m.group(2)
        out.append(f'"{m.group(0).strip()}": dates with digits use English months '
                   f'("{_EN_MONTHS[_TL_MONTHS.index(tl)]}")')
    for m in _ROOT_Q.finditer(t):
        if _is_root(m.group(1)):
            out.append(f'"{m.group(0).strip(" ,.?!")}": a question about what will happen needs the aspect form '
                       f'(for example "Babayaran mo ba", "Kailangan mo bang bayaran")')
    return out


def script_problems(lines: list[str]) -> list[str]:
    """Problems for a whole script, each prefixed with its scene number (1-based)."""
    return [f"scene {i}: {p}" for i, line in enumerate(lines, 1) for p in problems(line)]

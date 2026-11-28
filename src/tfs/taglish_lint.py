"""Machine checks for Taglish that a Filipino listener hears as unnatural (owner, 2026-11-25: "Sa 7 buwan ng 2026"
is not how anyone says it; 2026-11-26: "Isang chief justice", not "one chief justice"). The narrator reads digits in
English (`tts_voxcpm.spoken`), so small counts (1 to 10) are written as Tagalog linked numerals and big figures stay
digits next to English words. Guide with sources: the studio notes wiki/answers/tfs-natural-taglish-2026-11.md.

Each problem is a short string naming the words and the fix, so it can go back to a writer as feedback.
"""
from __future__ import annotations

import re

_SRC = re.compile(r"\[S\d+[a-z]?\]")
# Tagalog time units: an English number is never followed by these ("seven buwan" is wrong). A small count becomes
# "pitong buwan"; above 10 the unit goes English ("24 months").
_TL_UNITS = {"segundo": "seconds", "minuto": "minutes", "oras": "hours", "araw": "days", "linggo": "weeks",
             "buwan": "months", "taon": "years", "dekada": "decades", "siglo": "centuries"}
_DIGIT_TL_UNIT = re.compile(r"(?<![\w.,])(\d[\d,.]*)\s+(?:na\s+)?(" + "|".join(_TL_UNITS) + r")\b", re.I)
# "sa 7 months ng 2026" or "sa 7 months": no "loob ng", "unang" or "first", so it reads as a garbled date.
# "sa 6 years na termino" (a span used as a modifier) is fine.
_EN_TO_TL = {"second": "segundo", "seconds": "segundo", "minute": "minuto", "minutes": "minuto", "hour": "oras",
             "hours": "oras", "day": "araw", "days": "araw", "week": "linggo", "weeks": "linggo", "month": "buwan",
             "months": "buwan", "year": "taon", "years": "taon", "decade": "dekada", "decades": "dekada"}
_BARE_SPAN = re.compile(r"\bsa\s+(\d+)\s+(months|weeks|days|years|hours|buwan|linggo|araw|taon|oras)\b"
                        r"(?!\s+na\b)(?:\s+ng\s+\d{4})?", re.I)
_IKA_DIGIT = re.compile(r"\bika-?\s?(\d+)", re.I)
# Small counts (owner, 2026-11-26): Tagalog linked numerals, even before an English noun.
TL_NUM = {1: "isang", 2: "dalawang", 3: "tatlong", 4: "apat na", 5: "limang", 6: "anim na", 7: "pitong",
          8: "walong", 9: "siyam na", 10: "sampung"}
TL_ORD = {1: "unang", 2: "ikalawang", 3: "ikatlong", 4: "ikaapat na", 5: "ikalimang", 6: "ikaanim na",
          7: "ikapitong", 8: "ikawalong", 9: "ikasiyam na", 10: "ikasampung"}
_EN_NUM = "one two three four five six seven eight nine ten".split()
_SMALL_DIGIT = re.compile(r"(?<![\w.,₱$#/:-])(10|[1-9])(?![\d.,:%\w])\s+(?:na\s+)?([A-Za-z][\w-]*)")
_SMALL_ORD = re.compile(r"(?<![\w.,])(10|[1-9])(st|nd|rd|th)\s+([A-Za-z][\w-]*)", re.I)
_EN_WORD_COUNT = re.compile(r"(?<![\w-])(" + "|".join(_EN_NUM) + r")\s+([A-Za-z][\w-]*)", re.I)
_EN_NUMBER_WORDS = set(_EN_NUM) | set("eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen "
                                      "twenty thirty forty fifty sixty seventy eighty ninety hundred thousand".split())
TL_BARE = {1: "isa", 2: "dalawa", 3: "tatlo", 4: "apat", 5: "lima", 6: "anim", 7: "pito", 8: "walo", 9: "siyam",
           10: "sampu"}
# Not a count of things: references, names with numbers, dates and votes ("Section 3 ng", "Grade 7", "July 4",
# "20 to 3"). A number after these words is a label, so it stays a digit.
_REF_BEFORE = {"article", "articles", "section", "sections", "step", "rule", "title", "chapter", "book", "act",
               "ra", "no", "blg", "bill", "phase", "level", "alert", "signal", "number", "republic", "to", "vs",
               "grade", "order", "eo", "proclamation", "category", "district", "top", "batch", "room", "gate",
               "floor", "round", "stage", "season", "episode", "part", "volume", "version", "station", "line",
               "zone", "region", "lane", "terminal", "building", "block", "lot", "street", "kanto", "pahina",
               "page", "item", "talata", "seksyon", "artikulo", "tier", "class", "type", "covid", "form", "unit",
               *[m.lower() for m in ("January February March April May June July August September October "
                                     "November December Enero Pebrero Marso Abril Mayo Hunyo Hulyo Agosto "
                                     "Setyembre Oktubre Nobyembre Disyembre").split()]}
# Words after a digit that mean it is not counting a noun ("3 percent", "5 hanggang 10", "3 o'clock").
_NOT_COUNTED = {"ng", "at", "to", "ay", "ni", "kay", "percent", "million", "billion", "trillion", "hundred",
                "thousand", "point", "of", "or", "and", "am", "pm", "a", "p", "by", "in", "out", "for", "reading",
                "na", "ba", "din", "rin", "naman", "is", "was", "the", "hanggang", "hangga", "who", "which",
                "that", "more", "times", "x"}
# After these the count stands alone, so it takes the bare numeral ("isa lang", "dalawa o tatlong", "isa sa bawat").
_BARE_AFTER = {"sa", "o", "lang", "lamang", "ang", "pa", "muna", "kada"}
# Big figures in Tagalog words ("dalawampu't apat", "labinsiyam", "isang daang taon", "limang bilyong piso").
_TL_SMALL_WORD = r"(?:isang|dalawang|tatlong|apat\s+na|limang|anim\s+na|pitong|walong|siyam\s+na|sampung)"
_TL_BIG = re.compile(r"\b(?:dalawampu|tatlumpu|apatnapu|limampu|animnapu|pitumpu|walumpu|siyamnapu)\w*"
                     r"|\blabi[nm](?:g-)?\w+|\bsandaan\w*"
                     r"|\b" + _TL_SMALL_WORD + r"\s+(?:daan|libo|milyon|bilyon|trilyon)\w*", re.I)
_TL_WORD_PORSYENTO = re.compile(r"\b" + _TL_SMALL_WORD + r"\s+porsi?yento\b", re.I)
_TL_SCALE = re.compile(r"\d[\d,.]*\s*(trilyon|trilyong|bilyon|bilyong|milyon|milyong)\b", re.I)
_PORSYENTO = re.compile(r"\d[\d,.]*\s*(porsyento|porsiyento|bahagdan)\b", re.I)
_TL_MONTHS = ("Enero Pebrero Marso Abril Mayo Hunyo Hulyo Agosto Setyembre Oktubre Nobyembre Disyembre").split()
_EN_MONTHS = ("January February March April May June July August September October November December").split()
_TL_MONTH_DIGIT = re.compile(r"\b(" + "|".join(_TL_MONTHS) + r")\s+\d+|\d+\s+(?:ng\s+)?(" + "|".join(_TL_MONTHS) + r")\b")
# A yes or no question that opens with a bare root verb ("Bayaran mo ba iyon?") where Tagalog needs the
# aspect form ("Babayaran mo ba iyon?"). After "kailangan", "dapat", "pwede" the root form is right.
_ROOT_Q = re.compile(r"(?:^|[.?!]\s+|,\s+)([A-Za-z]+(?:an|in|han|hin))\s+"
                     r"(?:(mo|ko|natin|namin|ninyo|nila|niya|nyo|iyon|yon|ito)\s+)?(?:ba|bang)\b")
_NOT_VERBS = {"saan", "nasaan", "kailan", "kanino", "ilan", "alin", "kailangan", "pwedeng", "dahilan", "ngayon",
              "naman", "lamang", "tayo", "kasalanan", "pamahalaan", "bayan", "batasan", "halalan", "kalaban",
              "paaralan", "simbahan", "hukuman", "lungsod", "senador", "ganoon", "ganiyan"}


# "iyong" is two words on the page (owner, 2026-11-25): "that/the X" (iyon + -ng), which everyone says "yung",
# and formal "your X" (iyo + -ng), which people say "X mo". Either way the narrator would read it stiffly.
_IYONG = re.compile(r"\biyong\b", re.I)
_YUNG_SPELLING = re.compile(r"(?<![\w'])(?:'yung|'yong|yong)\b", re.I)    # one caption spelling: "yung"
_NG_YUNG = re.compile(r"\b(?:ng|sa)\s+yung\b", re.I)
# The owner, 2026-11-27: "yon sounds more natural" than "iyon"; "pwede is what we normally use"; law dates as
# "ikalawang Lunes ng Mayo", not "second Monday ng May".
_IYON = re.compile(r"\biyon\b", re.I)
_PUWEDE = re.compile(r"\bpuwede\w*", re.I)
_EN_ORD_WEEKDAY = re.compile(r"\b(first|second|third|fourth|fifth|last)\s+(Monday|Tuesday|Wednesday|Thursday|"
                             r"Friday|Saturday|Sunday)\b", re.I)
_TL_ORD_WORD = {"first": "unang", "second": "ikalawang", "third": "ikatlong", "fourth": "ikaapat na",
                "fifth": "ikalimang", "last": "huling"}
_TL_WEEKDAY = {"monday": "Lunes", "tuesday": "Martes", "wednesday": "Miyerkoles", "thursday": "Huwebes",
               "friday": "Biyernes", "saturday": "Sabado", "sunday": "Linggo"}


def _prev_word(text: str, pos: int) -> str:
    words = re.findall(r"[A-Za-z]+", text[:pos])
    return words[-1].lower() if words else ""


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
    for m in _SMALL_DIGIT.finditer(t):
        n, word = int(m.group(1)), m.group(2)
        if word.lower() in _NOT_COUNTED or _prev_word(t, m.start()) in _REF_BEFORE:
            continue
        if word.lower() in _BARE_AFTER:
            fix = f"{TL_BARE[n]} {word}"
        else:
            fix = f"{TL_NUM[n]} {_EN_TO_TL.get(word.lower(), word)}"
        out.append(f'"{m.group(0)}": a small count is a Tagalog word, write "{fix}" '
                   f'(the narrator reads "{n}" as "{_EN_NUM[n - 1]}")')
    for m in _EN_WORD_COUNT.finditer(t):
        n, word = _EN_NUM.index(m.group(1).lower()) + 1, m.group(2)
        prev = _prev_word(t, m.start())
        if (word.lower() in _NOT_COUNTED | {"muna", "lang", "pa"} or word[0].isupper() or prev in _REF_BEFORE
                or prev in _EN_NUMBER_WORDS):
            continue
        out.append(f'"{m.group(0)}": a small count is a Tagalog word, write '
                   f'"{TL_NUM[n]} {_EN_TO_TL.get(word.lower(), word)}"')
    for m in _SMALL_ORD.finditer(t):
        if "reading" in t[m.end(2):m.end(2) + 30].lower() or _prev_word(t, m.start()) in _REF_BEFORE:
            continue
        out.append(f'"{m.group(0)}": a small ordinal is a Tagalog word, write "{TL_ORD[int(m.group(1))]} ..."')
    for m in _TL_BIG.finditer(t):
        out.append(f'"{m.group(0)}": big figures stay digits, read in English ("24 na senador", "₱170,000")')
    for m in _TL_WORD_PORSYENTO.finditer(t):
        out.append(f'"{m.group(0)}": percentages are digits with the percent sign ("3%"), read as "percent"')
    for m in _DIGIT_TL_UNIT.finditer(t):
        num = m.group(1)
        if num.isdigit() and 1 <= int(num) <= 10:
            continue                                      # the small-count check above already names the fix
        out.append(f'"{m.group(0)}": an English number takes an English unit, write "{num} '
                   f'{_TL_UNITS[m.group(2).lower()]}"')
    for m in _BARE_SPAN.finditer(t):
        n, unit = int(m.group(1)), m.group(2).lower()
        if 1 <= n <= 10:
            span = f"{TL_NUM[n]} {_EN_TO_TL.get(unit, unit)}"
        else:
            span = f"{n} {_TL_UNITS.get(unit, unit)}"
        out.append(f'"{m.group(0)}": say which span, "sa loob ng {span}", "sa unang {span} ng <year>" or '
                   f'"mula <month> hanggang <month> <year>"')
    for m in _IKA_DIGIT.finditer(t):
        n = int(m.group(1))
        fix = f'"{TL_ORD[n]} ..."' if 1 <= n <= 10 else "a date or an English ordinal"
        out.append(f'"{m.group(0)}": the narrator would say "ika-" plus an English number; write {fix}')
    for m in _TL_SCALE.finditer(t):
        out.append(f'"{m.group(0)}": digits take English scale words (trillion, billion, million)')
    for m in _PORSYENTO.finditer(t):
        out.append(f'"{m.group(0)}": write the percent sign ("55.9%"), read as "percent"')
    for m in _TL_MONTH_DIGIT.finditer(t):
        tl = m.group(1) or m.group(2)
        out.append(f'"{m.group(0).strip()}": dates with digits use English months '
                   f'("{_EN_MONTHS[_TL_MONTHS.index(tl)]}")')
    for m in _IYON.finditer(t):
        out.append(f'"{m.group(0)}": write "yon" (owner: "yon sounds more natural")')
    for m in _PUWEDE.finditer(t):
        out.append(f'"{m.group(0)}": write "{m.group(0).lower().replace("puwede", "pwede")}" (the everyday spelling)')
    for m in _EN_ORD_WEEKDAY.finditer(t):
        o, d = m.group(1).lower(), m.group(2).lower()
        out.append(f'"{m.group(0)}": say it in Tagalog, "{_TL_ORD_WORD[o]} {_TL_WEEKDAY[d]}" '
                   f'("ikalawang Lunes ng Mayo")')
    for m in _IYONG.finditer(t):
        out.append(f'"{m.group(0)}": write "yung [thing]" when it means "the/that", or "[thing] mo" when it means '
                   f'"your" ("ang share mo", not "ang iyong share")')
    for m in _YUNG_SPELLING.finditer(t):
        out.append(f'"{m.group(0)}": spell it "yung" so captions stay consistent')
    for m in _NG_YUNG.finditer(t):
        out.append(f'"{m.group(0)}": no "yung" after ng or sa; write "{m.group(0).split()[0]} [thing]"')
    for m in _ROOT_Q.finditer(t):
        if _is_root(m.group(1)):
            out.append(f'"{m.group(0).strip(" ,.?!")}": a question about what will happen needs the aspect form '
                       f'(for example "Babayaran mo ba", "Kailangan mo bang bayaran")')
    return out


def script_problems(lines: list[str]) -> list[str]:
    """Problems for a whole script, each prefixed with its scene number (1-based)."""
    return [f"scene {i}: {p}" for i, line in enumerate(lines, 1) for p in problems(line)]

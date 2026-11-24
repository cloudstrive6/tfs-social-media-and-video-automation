"""Licensed b-roll from Wikimedia Commons: search, licence filter, download, the TFS grade and a per-item licence log.

Automates what was done by hand for the approved v2 pilot (revamp-2026-11/v2-scripts/dl2.py, pilot/engine/
grade_assets.py and update_asset_log.py). Policy (docs: Bryce-Brain wiki/answers/tfs-style-v2-spec-2026-11.md):

- Allowed licences: public domain (incl. PD-*), CC0 and CC BY (any version). Never BY-SA, NC, ND, GFDL-only,
  "fair use" or a missing licence.
- Philippine government works (RA 8293 s.176) are treated like news clips: government MOVING footage is a fair-use
  clip, and automated episodes use no fair-use clips at all, so it is rejected here. Government STILL photos are
  allowed, flagged `government_origin` and credited and logged like everything else.
- Photos must be JPEG or PNG and at least 1280 px wide; videos (webm, ogv) follow the same licence rule.
- Every asset gets a row in `<item_dir>/licences.json` (source URL, licence, author, credit, date read, where used).

Wikimedia etiquette: one identifying User-Agent on every request, polite pacing, back off on 429/503.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import item_dir as _item_dir
from ..config import now

log = logging.getLogger(__name__)

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = ("TheFilipinoStandardBot/1.0 (https://github.com/cloudstrive6/tfs-social-media-and-video-automation) "
              "python-urllib")
MAX_TRIES = 3
MIN_INTERVAL = 1.0              # seconds between requests to Wikimedia (politeness)
MAX_WAIT = 120.0                # cap on one back-off wait
MIN_PHOTO_WIDTH = 1280                     # 1080 px verticals; the paper grade softens photos (was 1600 until 2026-11-24)
MAX_VIDEO_BYTES = 400_000_000   # originals above this are not downloaded (a 55 min ceremony webm is 600 MB)
PHOTO_MIMES = {"image/jpeg", "image/png"}
VIDEO_EXTS = {".webm", ".ogv"}
VIDEO_MIMES = {"video/webm", "video/ogg", "application/ogg"}

# Seams for tests (and for anyone who wants a different transport): replaced with fakes offline.
_urlopen = urllib.request.urlopen
_sleep = time.sleep
_clock = time.monotonic
_last_request = [0.0]


# ---------------------------------------------------------------- HTTP
def _retry_after(err: urllib.error.HTTPError, attempt: int) -> float:
    value = (err.headers.get("Retry-After") if err.headers is not None else None) or ""
    try:
        wait = float(value)
    except ValueError:
        wait = 5.0 * (2 ** attempt)          # no (or an HTTP-date) Retry-After: 5, 10, 20 s
    return max(0.0, min(MAX_WAIT, wait))


def _get(url: str, timeout: float = 120) -> bytes:
    """GET with the TFS User-Agent; retries 429/503 (Retry-After respected), at most MAX_TRIES attempts."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(MAX_TRIES):
        gap = MIN_INTERVAL - (_clock() - _last_request[0])
        if gap > 0:
            _sleep(gap)
        _last_request[0] = _clock()
        try:
            with _urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == MAX_TRIES - 1:
                raise
            wait = _retry_after(e, attempt)
            log.warning("Commons HTTP %s, waiting %.0f s (try %d of %d)", e.code, wait, attempt + 1, MAX_TRIES)
            _sleep(wait)
    raise RuntimeError("unreachable")


def _clean_url(url: str) -> str:
    """Drop Wikimedia's utm_* tracking parameters so logged URLs are stable."""
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "" and url.startswith("//"):
        parts = urllib.parse.urlsplit("https:" + url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("utm_")]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


# ---------------------------------------------------------------- text helpers
_HIDDEN = re.compile(r"<(span|div)[^>]*display:\s*none[^>]*>.*?</\1>", re.S | re.I)


def strip_html(value: str) -> str:
    """Plain text from Commons extmetadata HTML: hidden spans removed, tags stripped, entities decoded."""
    text = _HIDDEN.sub("", value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"(Unknown author\s*)+", "Unknown author", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([,.;:)])", r"\1", text).replace("( ", "(")


def clean_author(value: str) -> str:
    author = strip_html(value)
    if not author or author.lower() in {"unknown", "unknown author", "anonymous"}:
        return "Unknown author"
    return author


def credit_text(author: str, licence: str, kind: str = "photo") -> str:
    """On-screen credit, e.g. 'Photo: Judgefloro, Wikimedia Commons, Public domain'."""
    label = "Video" if kind == "video" else "Photo"
    return f"{label}: {clean_author(author)}, Wikimedia Commons, {licence}"


# ---------------------------------------------------------------- licence rules
_CC_BY = re.compile(r"^cc[\s-]+by(?:[\s-]+(\d(?:\.\d)?))?(?:[\s-]+[a-z]{2}(?:[\s-][a-z]+)?)?$", re.I)
_CC0 = re.compile(r"^(cc0|cc[\s-]zero|cc[\s-]?0)(?:[\s-]+1\.0)?(?:[\s-]+universal)?$", re.I)
_PD = re.compile(r"^(public[\s-]domain|pd)(?:[\s-].*)?$", re.I)


def normalise_licence(short: str, code: str = "") -> str:
    """Commons LicenseShortName (falling back to the License code like 'cc-by-4.0') as one readable label."""
    s = strip_html(short or "")
    if not s and code:
        c = code.strip().lower()
        if c == "pd" or c.startswith("pd-"):
            s = "Public domain"
        elif c.startswith("cc-"):
            bits = c[3:].split("-")
            ver = [b for b in bits if re.fullmatch(r"\d(\.\d)?", b)]
            names = [b.upper() for b in bits if b not in ver]
            s = "CC " + "-".join(names) + (" " + ver[0] if ver else "")
            s = s.replace("CC ZERO", "CC0").replace("CC CC0", "CC0")
        elif c == "cc0":
            s = "CC0"
        else:
            s = code
    return s


def licence_ok(licence: str) -> tuple[bool, str]:
    """(allowed, reason) under the TFS rule: PD / PD-* / CC0 / CC BY x.y only."""
    s = (licence or "").strip()
    low = s.lower()
    if not s:
        return False, "missing licence"
    if "fair use" in low or "non-free" in low or "not licensed" in low or "all rights reserved" in low:
        return False, "fair use or unlicensed"
    tokens = set(re.split(r"[\s\-_/,()]+", low))
    if tokens & {"sa", "nc", "nd"} or any(w in low for w in ("sharealike", "share alike", "noncommercial",
                                                                 "non-commercial", "noderiv", "no deriv")):
        return False, f"disallowed licence ({s}): no BY-SA, NC or ND"
    if "gfdl" in low:
        return False, f"disallowed licence ({s}): GFDL-only"
    if _PD.match(s):
        return True, "public domain"
    if _CC0.match(s):
        return True, "CC0"
    if _CC_BY.match(s):
        return True, "CC BY"
    return False, f"licence not on the allowed list ({s})"


def licence_url_for(licence: str, given: str = "") -> str:
    if given:
        return _clean_url(given)
    if _CC0.match(licence or ""):
        return "https://creativecommons.org/publicdomain/zero/1.0/"
    m = _CC_BY.match(licence or "")
    if m and m.group(1):
        return f"https://creativecommons.org/licenses/by/{m.group(1)}/"
    return ""


# ---------------------------------------------------------------- policy helpers
GOVERNMENT_PATTERNS = [            # matched without case
    r"\bPhilippine News Agency\b", r"\bPresidential Communications\b", r"\bPresidential Photographers?\b",
    r"\bRadio Television Malaca[nñ]ang\b", r"\bMalaca[nñ]ang Photo Bureau\b", r"\bMalaca[nñ]ang Palace\s*$",
    r"\bOffice of the President of the Philippines\b", r"\bPhilippine Information Agency\b",
    r"\bSenate of the Philippines\b", r"\bSenate (?:PRIB|Public Relations)\b", r"\bPhilippine Senate\b",
    r"\bHouse of Representatives of the Philippines\b", r"\bPress and Public Affairs Bureau\b",
    r"\bCongress of the Philippines\b",
    r"\bSupreme Court (?:of the Philippines|Public Information Office|PIO)\b", r"\bPhilippine Supreme Court\b",
    r"\bNational Historical Commission of the Philippines\b",
    r"\bPhilippine Government\b", r"\bGovernment of the Philippines\b", r"\bArmed Forces of the Philippines\b",
    r"\bPhilippine Sports Commission\b", r"\.gov\.ph\b",
]
GOVERNMENT_ACRONYMS = ["PNA", "PCO", "PCOO", "PIA", "RTVM", "NHCP", "PRIB"]   # matched case-sensitively ("Pia" is a name)
_GOV = re.compile("|".join(GOVERNMENT_PATTERNS), re.I | re.M)
_GOV_ACR = re.compile(r"\b(" + "|".join(GOVERNMENT_ACRONYMS) + r")\b")

# Titles or descriptions that suggest minors are the subject: the vision step rejects or checks these by eye.
REJECT_HINTS = ["children", "child", "kids", "kid", "students", "student", "pupils", "pupil", "schoolchildren",
                "minors", "bata", "mga bata", "kabataan", "estudyante"]
_HINTS = re.compile(r"\b(" + "|".join(re.escape(h) for h in sorted(REJECT_HINTS, key=len, reverse=True)) + r")\b",
                    re.I)


def _meta_text(meta, keys) -> str:
    if isinstance(meta, Candidate):
        meta = asdict(meta)
    parts = []
    for k in keys:
        v = meta.get(k) if isinstance(meta, dict) else None
        if isinstance(v, dict):                     # raw extmetadata form {"value": ...}
            v = v.get("value")
        if isinstance(v, (list, tuple)):
            v = " ".join(map(str, v))
        if v:
            parts.append(str(v))
    return " | ".join(parts)


def government_agency(meta) -> str | None:
    """The Philippine government body named as the author or source, if any (meta: Candidate, log row or dict)."""
    text = html.unescape(_meta_text(meta, ("author", "credit", "artist_html", "credit_html", "Artist", "Credit",
                                           "source_credit")))
    text = text.replace(" | ", "\n")                # one field per line, so "...Palace$" means the whole field
    m = _GOV.search(text) or _GOV_ACR.search(text)
    return m.group(0).strip() if m else None


def is_government_origin(meta) -> bool:
    return government_agency(meta) is not None


def minor_hints(meta) -> list[str]:
    """REJECT_HINTS words found in the title, description or categories."""
    text = _meta_text(meta, ("title", "description", "categories", "subject", "ImageDescription", "ObjectName"))
    return sorted({m.group(1).lower() for m in _HINTS.finditer(text)})


# ---------------------------------------------------------------- candidates
@dataclass
class Candidate:
    title: str
    page_url: str
    direct_url: str
    thumb_url: str
    width: int
    height: int
    size: int
    mime: str
    kind: str                       # photo | video | other
    licence: str
    licence_url: str
    author: str
    query: str = ""
    duration: float | None = None
    description: str = ""
    categories: list[str] = field(default_factory=list)
    credit: str = ""                # Commons "Credit" field (usually the source), plain text
    restrictions: str = ""
    artist_html: str = ""
    credit_html: str = ""
    government_origin: bool = False
    hints: list[str] = field(default_factory=list)
    allowed: bool = False
    reason: str = ""

    @property
    def credit_text(self) -> str:
        return credit_text(self.author, self.licence, self.kind)


def _kind(title: str, mime: str) -> str:
    ext = os.path.splitext(title.lower())[1]
    if ext in VIDEO_EXTS or (mime in VIDEO_MIMES and not mime.startswith("audio")):
        return "video"
    if mime.startswith("image/"):
        return "photo"
    return "other"


def evaluate(c: Candidate) -> tuple[bool, str]:
    """Licence plus media rules for one candidate."""
    ok, why = licence_ok(c.licence)
    if not ok:
        return False, why
    if c.kind == "photo":
        if c.mime not in PHOTO_MIMES:
            return False, f"photo format {c.mime} (JPEG or PNG only)"
        if c.width < MIN_PHOTO_WIDTH:
            return False, f"too small ({c.width} px wide, need {MIN_PHOTO_WIDTH})"
    elif c.kind == "video":
        if os.path.splitext(c.title.lower())[1] not in VIDEO_EXTS:
            return False, "video format (webm or ogv only)"
        if c.government_origin:
            return False, ("government moving footage counts as a fair-use clip; automated episodes use none "
                           f"({government_agency(c)})")
    else:
        return False, f"not a photo or video ({c.mime})"
    return True, why


def _value(meta: dict, key: str) -> str:
    v = (meta.get(key) or {}).get("value", "")
    return v if isinstance(v, str) else str(v)


def parse_response(data: dict, query: str = "") -> list[Candidate]:
    """Candidates from an action=query&generator=search&prop=imageinfo response (formatversion 1 or 2)."""
    if "error" in data:
        raise RuntimeError(f"Commons API error: {data['error'].get('code')}: {data['error'].get('info')}")
    pages = (data.get("query") or {}).get("pages") or []
    if isinstance(pages, dict):
        pages = list(pages.values())
    pages = sorted(pages, key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        if not p.get("imageinfo"):
            continue
        ii = p["imageinfo"][0]
        meta = ii.get("extmetadata") or {}
        title = p["title"].split(":", 1)[1] if p["title"].startswith("File:") else p["title"]
        mime = ii.get("mime", "")
        licence = normalise_licence(_value(meta, "LicenseShortName"), _value(meta, "License"))
        c = Candidate(
            title=title, page_url=_clean_url(ii.get("descriptionurl", "")), direct_url=_clean_url(ii.get("url", "")),
            thumb_url=_clean_url(ii.get("thumburl", "")), width=int(ii.get("width") or 0),
            height=int(ii.get("height") or 0), size=int(ii.get("size") or 0), mime=mime, kind=_kind(title, mime),
            licence=licence, licence_url=licence_url_for(licence, _value(meta, "LicenseUrl")),
            author=clean_author(_value(meta, "Artist")), query=query, duration=ii.get("duration"),
            description=strip_html(_value(meta, "ImageDescription"))[:500],
            categories=[x for x in _value(meta, "Categories").split("|") if x],
            credit=strip_html(_value(meta, "Credit"))[:300], restrictions=_value(meta, "Restrictions"),
            artist_html=_value(meta, "Artist"), credit_html=_value(meta, "Credit"))
        c.government_origin = is_government_origin(c)
        c.hints = minor_hints(c)
        c.allowed, c.reason = evaluate(c)
        out.append(c)
    return out


def search(query: str, limit: int = 20, allowed_only: bool = True) -> list[Candidate]:
    """Search Commons files (namespace 6). By default only candidates that pass the licence and media rules;
    `allowed_only=False` returns every result with `allowed` and `reason` filled in."""
    params = {"action": "query", "format": "json", "formatversion": "2", "generator": "search",
              "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": max(1, min(int(limit), 50)),
              "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 2000}
    data = json.loads(_get(API + "?" + urllib.parse.urlencode(params), timeout=60).decode("utf-8"))
    found = parse_response(data, query)
    for c in found:
        if not c.allowed:
            log.info("skip %s: %s", c.title, c.reason)
    return [c for c in found if c.allowed] if allowed_only else found


# ---------------------------------------------------------------- download
def safe_name(title: str, ext: str) -> str:
    stem = os.path.splitext(title)[0]
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()[:80] or "file"
    return stem + ext


def fetch(candidate: Candidate, dest_dir: Path | str) -> Path:
    """Download the 2000 px thumbnail (photos) or the original file (videos). Skips files already there."""
    ok, why = evaluate(candidate)
    if not ok:
        raise ValueError(f"refusing to fetch {candidate.title}: {why}")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    if candidate.kind == "video":
        if candidate.size and candidate.size > MAX_VIDEO_BYTES:
            raise ValueError(f"{candidate.title} is {candidate.size / 1e6:.0f} MB, over the {MAX_VIDEO_BYTES / 1e6:.0f} MB cap")
        url, ext = candidate.direct_url, os.path.splitext(candidate.title)[1].lower()
    else:
        url = candidate.thumb_url or candidate.direct_url
        ext = ".png" if urllib.parse.urlsplit(url).path.lower().endswith(".png") else ".jpg"
    out = dest / safe_name(candidate.title, ext)
    if out.exists() and out.stat().st_size > 0:
        return out
    part = out.with_name(out.name + ".part")
    part.write_bytes(_get(url, timeout=600))
    os.replace(part, out)
    return out


# ---------------------------------------------------------------- grade (port of pilot/engine/grade_assets.py)
TARGET = 9.0                                                  # SATAVG every colour asset is pulled to
SAT_MIN, SAT_MAX = 0.35, 2.8
TONE = ("eq=contrast=0.96,curves=all='0/0.05 1/0.97',"
        "colorbalance=rs=-0.03:gs=0.008:bs=0.035:rm=-0.01:bm=0.01")   # lifted blacks, faint teal shadows
BW = "hue=s=0,eq=contrast=1.08,curves=all='0/0.06 1/0.95'"         # archive: black and white for the film gate


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is not on PATH")
    return exe


def satavg(path: Path | str, vf: str = "null", video: bool = False) -> float | None:
    """Mean SATAVG of the file after the filter chain (videos sampled at 2 fps)."""
    chain = (("fps=2," if video else "") + f"scale=640:-2,format=yuv420p,{vf},signalstats,"
             "metadata=print:key=lavfi.signalstats.SATAVG")
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-threads", "2", "-i", str(path), "-vf", chain, "-an", "-f", "null",
                        "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    vals = [float(v) for v in re.findall(r"SATAVG=([\d.]+)", r.stderr)]
    return sum(vals) / len(vals) if vals else None


def grade(path: Path | str, out_path: Path | str, kind: str, gate: bool = False) -> dict:
    """One TFS look: colour assets pulled to SATAVG 9 with TONE (lifted blacks, teal shadows); `gate` (archive)
    goes black and white. Video is scaled and cropped to 1920x1080 and frame-blended to 60 fps, audio dropped.
    Returns {"out", "kind", "gate", "sat_before", "saturation", "satavg"} with the measured SATAVG after."""
    src, out = Path(path), Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    video = kind == "video"
    before, k = None, None
    if gate:
        look = BW
    else:
        before = satavg(src, TONE, video)
        k = max(SAT_MIN, min(SAT_MAX, TARGET / max(before if before is not None else TARGET, 0.5)))
        look = f"{TONE},eq=saturation={k:.3f}"
    if video:
        subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-threads", "2", "-i", str(src), "-an", "-vf",
                        f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,{look},"
                        "minterpolate=fps=60:mi_mode=blend",
                        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out)], check=True)
    else:
        for attempt in range(3):                              # retry: memory is tight while other renders run
            r = subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-threads", "2", "-i", str(src), "-vf",
                                f"scale='min(2400,iw)':-2,format=yuv420p,{look}", "-frames:v", "1", "-update", "1",
                                "-q:v", "3", str(out)])
            if r.returncode == 0:
                break
        else:
            raise RuntimeError(f"ffmpeg could not grade {src.name}")
    after = satavg(out, "null", video)
    return {"out": str(out), "kind": kind, "gate": gate,
            "sat_before": round(before, 2) if before is not None else None,
            "saturation": round(k, 3) if k is not None else None,
            "satavg": round(after, 1) if after is not None else None}


# ---------------------------------------------------------------- licence log
class LicenceLog:
    """`<item_dir>/licences.json`: one row per b-roll asset, updated in place (rows matched by id)."""

    FILENAME = "licences.json"

    def __init__(self, directory: Path | str):
        self.path = Path(directory) / self.FILENAME
        self.rows: list[dict] = (json.loads(self.path.read_text(encoding="utf-8"))
                                 if self.path.exists() else [])

    @classmethod
    def for_item(cls, item_id: str) -> "LicenceLog":
        return cls(_item_dir(item_id))

    def get(self, asset_id: str) -> dict | None:
        return next((r for r in self.rows if r.get("id") == asset_id), None)

    def _next_id(self) -> str:
        taken = {r.get("id") for r in self.rows}
        n = len(self.rows) + 1
        while f"B{n:03d}" in taken:
            n += 1
        return f"B{n:03d}"

    def upsert(self, row: dict) -> dict:
        row = dict(row)
        row.setdefault("id", self._next_id())
        row.setdefault("used_at", [])
        current = self.get(row["id"])
        if current is None:
            self.rows.append(row)
            return row
        current.update({k: v for k, v in row.items() if k != "used_at" or v})
        return current

    def add(self, candidate: Candidate, file: Path | str = "", asset_id: str | None = None, subject: str = "",
            status: str = "downloaded") -> dict:
        notes = f"Licence read from Commons API extmetadata. {candidate.width}x{candidate.height}"
        if candidate.kind == "video" and candidate.duration:
            notes += f", {candidate.duration:.1f} s"
        notes += "."
        if candidate.government_origin:
            notes += (f" Government-origin still ({government_agency(candidate)}): credited and logged; government "
                      "stills do not count toward the fair-use cap.")
        if candidate.hints:
            notes += f" Minor hints in metadata: {', '.join(candidate.hints)}; check by eye."
        row = {"id": asset_id or self._next_id(), "file": Path(file).name if file else "", "kind": candidate.kind,
               "subject": subject or candidate.query, "query": candidate.query, "source": "commons",
               "title": candidate.title, "source_url": candidate.page_url, "direct_url": candidate.direct_url,
               "licence": candidate.licence, "licence_url": candidate.licence_url, "author": candidate.author,
               "credit_text": candidate.credit_text, "date_read": now().date().isoformat(), "status": status,
               "government_origin": candidate.government_origin, "notes": notes, "used_at": []}
        return self.upsert(row)

    def mark_used(self, asset_id: str, video: str, from_s: float, to_s: float, word: str = "") -> dict:
        row = self.get(asset_id)
        if row is None:
            raise KeyError(asset_id)
        use = {"video": video, "from_s": round(float(from_s), 3), "to_s": round(float(to_s), 3), "word": word}
        if use not in row.setdefault("used_at", []):
            row["used_at"].append(use)
        return row

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.rows, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        return self.path

    def check(self) -> list[str]:
        """Problems that block publishing: missing or disallowed licence, missing credit, CC BY without a licence
        URL, missing source URL, duplicate ids."""
        problems, seen = [], set()
        for r in self.rows:
            rid = r.get("id") or "?"
            if rid in seen:
                problems.append(f"{rid}: duplicate id")
            seen.add(rid)
            lic = (r.get("licence") or "").strip()
            if not lic:
                problems.append(f"{rid}: missing licence")
            else:
                ok, why = licence_ok(lic)
                if not ok:
                    problems.append(f"{rid}: disallowed licence: {why}")
                elif why == "CC BY" and not r.get("licence_url"):
                    problems.append(f"{rid}: CC BY without a licence URL")
            if not (r.get("credit_text") or "").strip():
                problems.append(f"{rid}: missing credit")
            if not r.get("source_url"):
                problems.append(f"{rid}: missing source URL")
            if r.get("kind") == "video" and r.get("government_origin"):
                problems.append(f"{rid}: government moving footage (fair-use clip; automated episodes use none)")
        return problems

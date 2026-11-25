"""Atlas engine (style v2, approved 2026-11-24): paper-and-map explainers with real b-roll, documents, cards,
charts and a Blender hero shot, rendered by HyperFrames from one JSON shot list.

The browser runtime is engine/runtime/atlas.js (GSAP) with its pure helpers in atlas_lib.js. Each shot is a dict
with `k` (map, bigtext, title, doc, cards, bars, timeline, compare, seats, split, broll, and the v3 blocks of
2026-11-25: globe, checklist, linechart, barchart, waffle, balance, dates, media), `t0`/`t1` in seconds and its own
fields; any shot may carry a `stamp`. `words` drives the word-highlight captions (a word with `key` gets a box). Verticals (9:16) get the @thefilipinostandard watermark. Audio is mixed separately
(media/sfx_v2.py) and muxed by the pipeline.

Ported from the approved pilot: Z:/Video Production Files/The Filipino Standard/revamp-2026-11/pilot/engine/
build_pilot.py (geometry, plan, build) and atlas.js.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from ..config import ROOT, channel

log = logging.getLogger(__name__)
ENGINE = ROOT / "engine"
GEO = ROOT / "assets" / "geo"
TEXTURES = ROOT / "assets" / "textures"
FONTS = ("Anton-Regular.ttf", "Montserrat-ExtraBold.ttf")
GAP = 0.35                      # silence between narration lines, as in the pilot

# ---------------------------------------------------------------- geometry (Natural Earth, public domain)
K = 20.0
LON0, LAT0 = 95.0, 25.0


def P(lon: float, lat: float) -> tuple[float, float]:
    return ((lon - LON0) * K, (LAT0 - lat) * K)


def _rings(polys):
    out = []
    for r in polys:
        if r and isinstance(r[0][0], list):
            out.extend(r)
        else:
            out.append(r)
    return out


def _d(polys, step: int = 1) -> str:
    parts = []
    for ring in _rings(polys):
        pts = ring[::step] if len(ring) > 40 else ring
        if len(pts) < 3:
            continue
        parts.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in (P(a, b) for a, b in pts)) + "Z")
    return "".join(parts)


def _in_box(polys, box=(90, -55, 185, 30)) -> bool:
    for ring in _rings(polys):
        for lon, lat in ring[:: max(1, len(ring) // 20)]:
            if box[0] <= lon <= box[2] and box[1] <= lat <= box[3]:
                return True
    return False


VIEWS = {"ph": (116.5, 4.5, 127.0, 21.0), "nz": (166.0, -47.5, 179.0, -34.0),
         "both": (110.0, -48.0, 180.0, 22.0), "luzon": (119.0, 12.8, 125.0, 19.0),
         "visayas": (121.0, 9.0, 126.5, 13.2), "mindanao": (121.5, 4.8, 127.0, 10.2),
         "ncr": (120.6, 14.2, 121.4, 14.9)}


def _view(lon0, lat0, lon1, lat1, aspect, pad=0.12):
    x0, y0 = P(lon0, lat1)
    x1, y1 = P(lon1, lat0)
    w, h = (x1 - x0) * (1 + pad), (y1 - y0) * (1 + pad)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if w / h < aspect:
        w = h * aspect
    else:
        h = w / aspect
    return [round(cx - w / 2, 1), round(cy - h / 2, 1), round(w, 1), round(h, 1)]


@lru_cache(maxsize=4)
def geo(aspect: float) -> dict:
    countries = json.loads((GEO / "countries.json").read_text(encoding="utf-8"))
    provs = json.loads((GEO / "ph_provinces.json").read_text(encoding="utf-8"))
    world = "".join(_d(c["polys"], 2) for c in countries if c["iso"] != "PHL" and _in_box(c["polys"]))
    ph = _d(next(c for c in countries if c["iso"] == "PHL")["polys"])
    nz = _d(next(c for c in countries if c["iso"] == "NZL")["polys"])
    grid = "".join(f"M{P(95, lat)[0]:.0f} {P(95, lat)[1]:.0f}H{P(180, lat)[0]:.0f}" for lat in range(-50, 26, 5))
    grid += "".join(f"M{P(lon, 25)[0]:.0f} {P(lon, 25)[1]:.0f}V{P(lon, -50)[1]:.0f}" for lon in range(95, 181, 5))
    return {"world": world, "ph": ph, "phProv": "".join(_d(p["polys"]) for p in provs), "nz": nz, "stroke": 0.6,
            "grid": {"d": grid, "w": 0.5, "dash": "3 6"},
            "views": {k: _view(*v, aspect) for k, v in VIEWS.items()}}


# ---------------------------------------------------------------- globe (orthographic, drawn by atlas_lib.js)
def _simplify(ring, tol):
    """Drop points closer than `tol` degrees to the last kept one (the globe is small on screen)."""
    out = [ring[0]]
    for pt in ring[1:]:
        if abs(pt[0] - out[-1][0]) + abs(pt[1] - out[-1][1]) >= tol:
            out.append(pt)
    return out if len(out) >= 4 else []


@lru_cache(maxsize=1)
def _countries() -> list[dict]:
    return json.loads((GEO / "countries.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _places() -> list[dict]:
    return json.loads((GEO / "places.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def globe_geo() -> list[dict]:
    """Every country as rounded lon/lat rings for the globe: [{"iso", "rings"}]. Natural Earth, public domain."""
    out = []
    for c in _countries():
        rings = []
        for ring in _rings(c["polys"]):
            r = _simplify(ring, 0.35)
            if r:
                rings.append([[round(x, 2), round(y, 2)] for x, y in r])
        if rings:
            out.append({"iso": c["iso"], "rings": rings})
    return out


def _key(name: str) -> str:
    return " ".join(str(name).lower().replace(".", " ").replace(",", " ").split())


def country(name: str) -> dict | None:
    """A country by ISO3 code, short or long name: {"iso", "name", "lon", "lat"} (centre of its largest ring)."""
    k = _key(name)
    if not k:
        return None
    for c in _countries():
        if k in (_key(c["iso"]), _key(c["name"]), _key(c.get("long_name", ""))):
            big = max(_rings(c["polys"]), key=len)
            xs, ys = [p[0] for p in big], [p[1] for p in big]
            return {"iso": c["iso"], "name": c["name"], "lon": round((min(xs) + max(xs)) / 2, 2),
                    "lat": round((min(ys) + max(ys)) / 2, 2)}
    return None


def city(name: str) -> dict | None:
    """A city from the Natural Earth populated places (Philippine places first): {"name", "lon", "lat"}."""
    k = _key(name)
    if not k:
        return None
    hits = [p for p in _places() if _key(p["name"]) == k]
    if not hits:
        return None
    hits.sort(key=lambda p: not p.get("ph"))
    return {"name": hits[0]["name"], "lon": hits[0]["lon"], "lat": hits[0]["lat"]}


def locate(name: str) -> dict | None:
    """A place or a country, whichever matches (cities first: "Singapore" is both)."""
    p = city(name)
    if p:
        return p
    c = country(name)
    return {"name": c["name"], "lon": c["lon"], "lat": c["lat"]} if c else None


# ---------------------------------------------------------------- timing
def place(lines: list[dict], durations: list[float], start: float = 0.4) -> tuple[list[dict], list[list[float]], float]:
    """Lines carry shots at fractions of their own audio: [{"shots": [(f0, f1, shot), ...], "pad": s, "pad_shots": [...]}].
    Returns (shots with absolute t0/t1, line start/end times, total duration). Same rule as the pilot's plan()."""
    t = start
    shots, times = [], []
    for ln, dur in zip(lines, durations):
        times.append([round(t, 3), round(t + dur, 3)])
        for f0, f1, s in ln.get("shots", []):
            shots.append(dict(s, t0=round(t + f0 * dur, 3), t1=round(t + f1 * dur + (GAP if f1 >= 1 else 0), 3)))
        t += dur + GAP
        if ln.get("pad"):
            for s in ln.get("pad_shots", []):
                shots.append(dict(s, t0=round(t, 3), t1=round(t + ln["pad"], 3)))
            t += ln["pad"]
    return shots, times, round(t + 0.4, 2)


def frac_at(word_time: float, line_start: float, line_dur: float) -> float:
    """Fraction of a line at which a word is spoken: cutaways are placed on words, not guessed fractions."""
    return max(0.0, min(1.0, round((word_time - line_start) / max(0.01, line_dur), 4)))


# ---------------------------------------------------------------- spec, project, render
def spec(comp_id: str, size: tuple[int, int], shots: list[dict], words: list[dict], duration: float) -> dict:
    w, h = size
    g = geo(round(w / h, 4))
    if any(s.get("k") == "globe" for s in shots):       # the world rings only travel with a globe shot
        g = dict(g, globe=globe_geo())
    return {"id": comp_id, "width": w, "height": h, "duration": round(duration, 3), "geo": g,
            "shots": sorted(shots, key=lambda s: s["t0"]), "words": words}


def _css() -> str:
    return ("@font-face{font-family:Anton;src:url(Anton-Regular.ttf)}"
            "@font-face{font-family:Montserrat;font-weight:800;src:url(Montserrat-ExtraBold.ttf)}"
            "html,body{margin:0;padding:0}#stage{position:relative;overflow:hidden}")


def build_project(sp: dict, out_dir: Path, assets: dict[str, Path] | None = None) -> Path:
    """Write index.html plus gsap, fonts, textures and the shot media. `assets` maps the relative src used in
    shots (for example "assets/L3-01.jpg") to a local file; each is copied next to the page."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ENGINE / "node_modules" / "gsap" / "dist" / "gsap.min.js", out_dir / "gsap.min.js")
    for f in FONTS:
        shutil.copy2(ROOT / "assets" / "fonts" / f, out_dir / f)
    shutil.copytree(TEXTURES, out_dir / "textures", dirs_exist_ok=True)
    for rel, src in (assets or {}).items():
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # video b-roll must be static in the HTML (HyperFrames pre-scans media; JS-created videos render black);
    # atlas.js moves each into its shot layer by id
    videos = []
    for n, s in enumerate(x for x in sp["shots"] if x.get("k") in ("broll", "media") and x.get("kind") == "video"):
        s["vid"] = f"bv{n}"
        videos.append(f'<video id="bv{n}" class="clip" src="{s["src"]}" muted playsinline data-start="{s["t0"]}" '
                      f'data-duration="{round(s["t1"] - s["t0"], 3)}" data-media-start="{s.get("mediaStart", 0)}" '
                      f'data-volume="0" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover"></video>')
    runtime = "\n".join((ENGINE / "runtime" / f).read_text(encoding="utf-8")
                        for f in ("atlas_lib.js", "atlas_blocks.js", "atlas.js"))
    spec_json = json.dumps(sp, ensure_ascii=False).replace("</", "<\\/")
    html = (f'<!doctype html><html><head><meta charset="utf-8"><style>{_css()}</style></head><body>'
            f'<div id="stage" data-composition-id="{sp["id"]}" data-start="0" data-duration="{sp["duration"]}" '
            f'data-width="{sp["width"]}" data-height="{sp["height"]}" style="width:{sp["width"]}px;height:{sp["height"]}px">'
            f'{"".join(videos)}<script src="gsap.min.js"></script><script>\nwindow.SPEC = {spec_json};\n{runtime}\n'
            '</script></div></body></html>')
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    return out_dir / "index.html"


def _hyperframes(args: list[str], cwd: Path, timeout: int = 7200) -> None:
    npx = shutil.which("npx") or "npx"
    res = subprocess.run([npx, "--prefix", str(ENGINE), "hyperframes", *args], cwd=cwd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=timeout,
                         env={**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1"})
    if res.returncode:
        raise RuntimeError(f"hyperframes {args[0]} failed: {(res.stderr or res.stdout)[-2000:]}")


def lint(project: Path) -> None:
    _hyperframes(["lint"], cwd=project, timeout=300)


def render(sp: dict, work: Path, out: Path, assets: dict[str, Path] | None = None) -> Path:
    """Silent MP4 at the configured fps (60)."""
    project = work / "atlas"
    build_project(sp, project, assets)
    vcfg = channel()["video"]
    workers = str(vcfg.get("render_workers", max(1, min(4, (os.cpu_count() or 2)))))
    _hyperframes(["render", "--fps", str(vcfg.get("fps_vector", 60)), "--quality", "standard", "--workers", workers,
                  "-o", str(out.resolve())], cwd=project)
    return out


def snapshot(sp: dict, work: Path, times: list[float], out_dir: Path, assets: dict[str, Path] | None = None) -> list[Path]:
    project = work / "atlas_snap"
    build_project(sp, project, assets)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.png"):
        f.unlink()
    _hyperframes(["snapshot", "--at", ",".join(f"{t:.2f}" for t in times), "--no-end", "--describe", "false",
                  "-o", str(out_dir.resolve())], cwd=project)
    frames = sorted(out_dir.glob("frame-*.png"), key=lambda f: int(f.stem.split("-")[1]))
    return frames[:len(times)]

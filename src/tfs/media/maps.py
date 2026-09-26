"""Map cards drawn from real boundary data (Natural Earth, public domain), so geography is always right.

The Visual Director names places (`card_lines`): provinces, cities, regions, island groups, seas and shoals,
or foreign countries. Each is looked up in assets/geo; anything unknown is left off rather than guessed.
A Philippine-only map zooms to the places (with a small whole-country inset); a foreign country switches
to a regional/world view with the Philippines always drawn for reference.
"""
from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from ..config import ROOT
from .design import BLUE, RED, WHITE, YELLOW, fit_text, font, glyphsafe

GEO = ROOT / "assets" / "geo"
SEA, LAND, PH_LAND, BORDER = (16, 34, 62), (52, 60, 76), (222, 212, 186), (150, 138, 112)
HILITE, INK_BOX = RED, (14, 16, 24)
PH_BBOX = (116.8, 4.5, 126.8, 21.2)          # lon_min, lat_min, lon_max, lat_max
SS = 2                                         # supersampling for smooth edges

# Island groups / islands -> provinces (and HUC cities) that make them up, as named in the data.
_LUZON_REGIONS = ["Ilocos (Region I)", "Cagayan Valley (Region II)", "Central Luzon (Region III)",
                  "CALABARZON (Region IV-A)", "MIMAROPA (Region IV-B)", "Bicol (Region V)",
                  "Cordillera Administrative Region (CAR)", "National Capital Region"]
_VISAYAS_REGIONS = ["Western Visayas (Region VI)", "Central Visayas (Region VII)", "Eastern Visayas (Region VIII)"]
_MINDANAO_REGIONS = ["Zamboanga Peninsula (Region IX)", "Northern Mindanao (Region X)", "Davao (Region XI)",
                     "SOCCSKSARGEN (Region XII)", "Dinagat Islands (Region XIII)",
                     "Autonomous Region in Muslim Mindanao (ARMM)"]
REGION_GROUPS = {
    "luzon": _LUZON_REGIONS, "visayas": _VISAYAS_REGIONS, "mindanao": _MINDANAO_REGIONS,
    "metro manila": ["National Capital Region"], "ncr": ["National Capital Region"],
    "barmm": ["Autonomous Region in Muslim Mindanao (ARMM)"], "armm": ["Autonomous Region in Muslim Mindanao (ARMM)"],
    "bangsamoro": ["Autonomous Region in Muslim Mindanao (ARMM)"], "caraga": ["Dinagat Islands (Region XIII)"],
    "cordillera": ["Cordillera Administrative Region (CAR)"], "car": ["Cordillera Administrative Region (CAR)"],
    "davao region": ["Davao (Region XI)"],
}
ISLANDS = {
    "panay": ["Aklan", "Antique", "Capiz", "Iloilo"], "negros": ["Negros Occidental", "Negros Oriental", "Bacolod"],
    "samar": ["Samar", "Eastern Samar", "Northern Samar"], "samar island": ["Samar", "Eastern Samar", "Northern Samar"],
    "leyte island": ["Leyte", "Southern Leyte", "Tacloban", "Ormoc"],
    "mindoro": ["Mindoro Occidental", "Mindoro Oriental"], "bohol": ["Bohol"],
}
PROVINCE_ALIASES = {
    "davao de oro": "Compostela Valley", "maguindanao del norte": "Maguindanao", "maguindanao del sur": "Maguindanao",
    "occidental mindoro": "Mindoro Occidental", "oriental mindoro": "Mindoro Oriental", "davao occidental": "Davao del Sur",
    "dinagat islands": "Surigao del Norte", "north cotabato": "Cotabato", "mandaluyong": "Mandaluyong City",
    "quezon province": "Quezon", "mt province": "Mountain Province", "mountain province": "Mountain Province",
}
# Cities the data draws as their own units, inside these provinces (highlighting the province includes them).
CITY_PARENT = {
    "Puerto Princesa": "Palawan", "Lapu-Lapu": "Cebu", "Mandaue": "Cebu", "Bacolod": "Negros Occidental",
    "Tacloban": "Leyte", "Ormoc": "Leyte", "Davao": "Davao del Sur", "Cagayan de Oro": "Misamis Oriental",
    "Iligan": "Lanao del Norte", "Zamboanga": "Zamboanga del Sur", "General Santos": "South Cotabato",
    "Butuan": "Agusan del Norte", "Angeles": "Pampanga", "Olongapo": "Zambales", "Baguio": "Benguet",
    "Dagupan": "Pangasinan", "Lucena": "Quezon", "Naga": "Camarines Sur", "Santiago": "Isabela",
}
# Named features that aren't provinces or cities (approximate centre points).
FEATURES = {
    "west philippine sea": (117.3, 13.0, "sea"), "south china sea": (116.0, 13.0, "sea"),
    "philippine sea": (128.2, 14.0, "sea"), "sulu sea": (120.0, 8.6, "sea"), "celebes sea": (122.8, 4.8, "sea"),
    "sibuyan sea": (122.6, 12.8, "sea"), "bohol sea": (124.4, 9.2, "sea"), "mindanao sea": (124.4, 9.2, "sea"),
    "scarborough shoal": (117.76, 15.15, "point"), "bajo de masinloc": (117.76, 15.15, "point"),
    "spratly islands": (114.4, 10.0, "point"), "kalayaan island group": (115.0, 10.5, "point"),
    "ayungin shoal": (115.87, 9.72, "point"), "second thomas shoal": (115.87, 9.72, "point"),
    "pag-asa island": (114.28, 11.05, "point"), "thitu island": (114.28, 11.05, "point"),
    "mischief reef": (115.53, 9.9, "point"), "panganiban reef": (115.53, 9.9, "point"),
    "philippine rise": (124.7, 16.5, "point"), "benham rise": (124.7, 16.5, "point"),
    "manila bay": (120.77, 14.52, "point"), "leyte gulf": (125.4, 10.8, "point"), "subic bay": (120.28, 14.8, "point"),
    "mount pinatubo": (120.35, 15.13, "point"), "mayon volcano": (123.69, 13.26, "point"),
    "taal volcano": (120.99, 14.0, "point"), "corregidor": (120.57, 14.38, "point"),
    "mactan": (123.98, 10.3, "point"), "boracay": (121.92, 11.97, "point"), "tubbataha reef": (119.9, 8.95, "point"),
    "marawi": (124.29, 8.0, "point"), "mamasapano": (124.52, 6.93, "point"), "balangiga": (125.39, 11.11, "point"),
    "intramuros": (120.975, 14.59, "point"), "malacanang": (120.994, 14.594, "point"),
    "edsa": (121.057, 14.588, "point"), "kawit": (120.9, 14.44, "point"), "clark": (120.55, 15.19, "point"),
    "acapulco": (-99.89, 16.85, "point"),
}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
    s = s.replace(".", "").replace("’", "'")
    for prefix in ("the ", "province of ", "city of ", "lalawigan ng ", "lungsod ng "):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return " ".join(s.split())


@lru_cache
def _load(name: str):
    return json.loads((GEO / f"{name}.json").read_text(encoding="utf-8"))


def _region_keys() -> dict[str, list[str]]:
    keys = dict(REGION_GROUPS)
    for region in {p["region"] for p in _load("ph_provinces")}:
        base, _, paren = region.partition(" (")
        keys.setdefault(norm(base), [region])
        if paren.lower().startswith("region "):
            keys.setdefault(norm(paren.rstrip(")")), [region])
    return keys


@dataclass
class Highlight:
    label: str
    kind: str                                        # area | point | sea | country
    polys: list = field(default_factory=list)
    point: tuple[float, float] | None = None
    foreign: bool = False


def resolve(name: str) -> Highlight | None:
    key = norm(name)
    provinces = _load("ph_provinces")

    def area(names: list[str] | None = None, regions: list[str] | None = None) -> Highlight | None:
        if names:
            names = names + [city for city, parent in CITY_PARENT.items() if parent in names]
        polys = [r for p in provinces
                 if (names and p["name"] in names) or (regions and p["region"] in regions) for r in p["polys"]]
        return Highlight(name, "area", polys) if polys else None

    if key in ISLANDS:                    # "Samar" means the island (3 provinces), not just Samar province
        return area(ISLANDS[key])
    stripped = key.removesuffix(" province").removesuffix(" city").strip()
    for candidate in (key, stripped):
        exact = [p["name"] for p in provinces if norm(p["name"]) == candidate]
        if exact:
            return area(exact)
    if key in PROVINCE_ALIASES:
        return area([PROVINCE_ALIASES[key]])
    regions = _region_keys()
    for candidate in (key, stripped, key.removesuffix(" region").strip()):
        if candidate in regions:
            return area(regions=regions[candidate])
    for candidate in (key, stripped, f"{stripped} island"):
        if candidate in ISLANDS:
            return area(ISLANDS[candidate])
    if key in FEATURES:
        lon, lat, kind = FEATURES[key]
        return Highlight(name, kind, point=(lon, lat), foreign=not _in_ph(lon, lat))
    places = _load("places")
    for want_ph in (True, False):
        for p in places:
            if p["ph"] == want_ph and norm(p["name"]) in (key, stripped):
                return Highlight(name, "point", point=(p["lon"], p["lat"]), foreign=not want_ph)
    for c in _load("countries"):
        if key in (norm(c["name"]), norm(c["long_name"]), c["iso"].lower()) or \
                (key in ("usa", "us", "america", "united states") and c["iso"] == "USA"):
            if c["iso"] == "PHL":
                return Highlight(name, "area", [r for p in provinces for r in p["polys"]])
            return Highlight(name, "country", c["polys"], foreign=True)
    return None


def _in_ph(lon: float, lat: float) -> bool:
    return PH_BBOX[0] - 4 <= lon <= PH_BBOX[2] + 4 and PH_BBOX[1] - 2 <= lat <= PH_BBOX[3] + 1


# ---------------------------------------------------------------- projection
class View:
    """Equirectangular projection with cos(latitude) scaling, fitted to a pixel rectangle."""

    def __init__(self, bbox: tuple[float, float, float, float], rect: tuple[int, int, int, int]):
        lon0, lat0, lon1, lat1 = bbox
        self.k = math.cos(math.radians((lat0 + lat1) / 2))
        x0, y0, x1, y1 = rect
        span_x, span_y = (lon1 - lon0) * self.k, lat1 - lat0
        self.scale = min((x1 - x0) / span_x, (y1 - y0) / span_y)
        cx, cy = (lon0 + lon1) / 2 * self.k, (lat0 + lat1) / 2
        self.ox, self.oy = (x0 + x1) / 2 - cx * self.scale, (y0 + y1) / 2 + cy * self.scale

    def xy(self, lon: float, lat: float) -> tuple[float, float]:
        return self.ox + lon * self.k * self.scale, self.oy - lat * self.scale

    def ring(self, ring, shift: float = 0.0):
        return [self.xy(lon + shift, lat) for lon, lat in ring]


def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _grow(bbox, min_span: float, pad: float, aspect: float):
    """Pad the box, enforce a minimum span, then widen/heighten it to the frame's aspect (w/h, projected)."""
    lon0, lat0, lon1, lat1 = bbox
    cx, cy = (lon0 + lon1) / 2, (lat0 + lat1) / 2
    k = math.cos(math.radians(cy))
    half_w = max((lon1 - lon0) * (1 + pad), min_span) / 2 * k
    half_h = max((lat1 - lat0) * (1 + pad), min_span) / 2
    if half_w / half_h < aspect:
        half_w = half_h * aspect
    else:
        half_h = half_w / aspect
    return cx - half_w / k, cy - half_h, cx + half_w / k, cy + half_h


def _shift_for(bbox_lons: list[float]) -> bool:
    """True if the view crosses the antimeridian (e.g. Manila–Acapulco) and west longitudes need +360."""
    return bool(bbox_lons) and max(bbox_lons) - min(bbox_lons) > 180


# ---------------------------------------------------------------- drawing
def _pin(d: ImageDraw.ImageDraw, x: float, y: float, r: float, sea: bool) -> None:
    if sea:
        return
    d.ellipse([x - r * 1.9, y - r * 1.9, x + r * 1.9, y + r * 1.9], outline=YELLOW, width=max(2, int(r * 0.35)))
    d.ellipse([x - r, y - r, x + r, y + r], fill=HILITE, outline=WHITE, width=max(2, int(r * 0.3)))


def _label(d: ImageDraw.ImageDraw, text: str, x: float, y: float, size: int, taken: list, bounds, sea: bool):
    fnt = font("display", size)
    text = glyphsafe(text.upper(), fnt)
    tw = d.textlength(text, font=fnt)
    pad = size * 0.35
    bw, bh = tw + 2 * pad, size * 1.35
    gap = size * 0.9
    options = ([(x - bw / 2, y - bh / 2)] if sea else
               [(x + gap, y - bh / 2), (x - gap - bw, y - bh / 2), (x - bw / 2, y - gap - bh), (x - bw / 2, y + gap)])
    for bx, by in options + [options[0]]:
        box = (bx, by, bx + bw, by + bh)
        inside = bounds[0] <= box[0] and box[2] <= bounds[2] and bounds[1] <= box[1] and box[3] <= bounds[3]
        if inside and not any(box[0] < t[2] and t[0] < box[2] and box[1] < t[3] and t[1] < box[3] for t in taken):
            break
    bx = min(max(bx, bounds[0]), bounds[2] - bw)
    by = min(max(by, bounds[1]), bounds[3] - bh)
    box = (bx, by, bx + bw, by + bh)
    taken.append(box)
    if sea:
        d.text((bx + pad, by + bh * 0.12), text, font=fnt, fill=(170, 200, 235))
    else:
        d.rounded_rectangle(box, radius=size * 0.2, fill=INK_BOX, outline=YELLOW, width=max(2, size // 12))
        d.text((bx + pad, by + bh * 0.12), text, font=fnt, fill=WHITE)


def _pixel_extent(v: View, polys, fix) -> float:
    pts = [v.xy(fix(lon), lat) for r in polys for lon, lat in r]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _centroid(polys) -> tuple[float, float]:
    big = max(polys, key=lambda r: len(r))
    return sum(p[0] for p in big) / len(big), sum(p[1] for p in big) / len(big)


def render_map(title: str, places: list[str], size: tuple[int, int], out: Path) -> Path:
    w, h = size
    W, H = w * SS, h * SS
    img = Image.new("RGB", (W, H), SEA)
    d = ImageDraw.Draw(img)
    pad = int(min(W, H) * 0.06)

    tf, tl, tlh = fit_text(d, title.upper(), "display", W - 2 * pad, int(H * 0.16), start=int(min(W, H) * 0.085))
    band = pad + tlh * len(tl) + pad // 2
    rect = (pad, band + pad // 2, W - pad, H - pad)

    hl = [x for x in (resolve(p) for p in places[:5]) if x]
    foreign = any(x.foreign for x in hl)
    pts = [pt for x in hl for pt in ([x.point] if x.point else [c for r in x.polys for c in r])]
    shift = foreign and _shift_for([p[0] for p in pts + [(PH_BBOX[0], 0), (PH_BBOX[2], 0)]])
    fix = (lambda lon: lon + 360 if lon < 0 else lon) if shift else (lambda lon: lon)
    aspect = (rect[2] - rect[0]) / (rect[3] - rect[1])
    if foreign:
        allpts = [(fix(x), y) for x, y in pts] + [(PH_BBOX[0], PH_BBOX[1]), (PH_BBOX[2], PH_BBOX[3])]
        view_box = _grow(_bbox(allpts), min_span=20, pad=0.25, aspect=aspect)
    elif pts:
        view_box = _grow(_bbox(pts), min_span=3.0, pad=0.6, aspect=aspect)
    else:
        view_box = _grow(PH_BBOX, min_span=0, pad=0.05, aspect=aspect)
    v = View(view_box, rect)

    def draw_rings(rings, fill, outline=None, width=1):
        for ring in rings:
            for s in ((0.0, 360.0) if shift else (0.0,)):
                d.polygon(v.ring(ring, s), fill=fill, outline=outline, width=width)

    for c in _load("countries"):
        if c["iso"] != "PHL":
            draw_rings(c["polys"], LAND, outline=(72, 82, 100), width=SS)
    zoomed = view_box[2] - view_box[0] < 9 and not foreign
    for p in _load("ph_provinces"):
        draw_rings(p["polys"], PH_LAND, outline=BORDER if zoomed else None, width=SS)
    for x in hl:
        if x.kind in ("area", "country"):
            draw_rings(x.polys, HILITE, outline=YELLOW, width=3 * SS)

    # labels and pins on top
    bounds = (rect[0], rect[1], rect[2], rect[3])
    taken: list = []
    lsize = int(min(W, H) * 0.038)
    r = min(W, H) * 0.012
    for x in hl:
        lon, lat = x.point if x.point else _centroid(x.polys)
        px, py = v.xy(fix(lon), lat)
        if x.point:
            _pin(d, px, py, r, x.kind == "sea")
        elif _pixel_extent(v, x.polys, fix) < min(W, H) * 0.03:     # too small to see: pin it too
            _pin(d, px, py, r, False)
        _label(d, x.label, px, py, lsize, taken, bounds, x.kind == "sea")

    if zoomed:
        _inset(img, v, view_box, rect)

    # title band + flag stripes + credit
    d.rectangle([0, 0, W, band], fill=(10, 14, 24))
    y = pad
    for row in tl:
        d.text((W / 2, y), row, font=tf, fill=YELLOW, anchor="mt")
        y += tlh
    d.rectangle([0, 0, W, int(H * 0.012)], fill=BLUE)
    d.rectangle([0, H - int(H * 0.012), W, H], fill=RED)
    cf = font("body", int(min(W, H) * 0.018))
    d.text((pad, H - pad * 0.45), "Map data: Natural Earth", font=cf, fill=(150, 160, 180), anchor="ls")

    img.resize((w, h), Image.LANCZOS).save(out)
    return out


def _inset(img: Image.Image, v: View, view_box, rect) -> None:
    """Whole-Philippines locator in a corner, with the zoomed area outlined."""
    W, H = img.size
    iw = int(min(W, H) * 0.2)
    ih = int(iw * 1.55)
    x1, y1 = rect[2], rect[3]
    box = (x1 - iw, y1 - ih, x1, y1)
    inset = Image.new("RGB", (iw, ih), (10, 22, 42))
    di = ImageDraw.Draw(inset)
    iv = View(PH_BBOX, (int(iw * 0.08), int(ih * 0.05), int(iw * 0.92), int(ih * 0.95)))
    for p in _load("ph_provinces"):
        for ring in p["polys"]:
            di.polygon(iv.ring(ring), fill=(190, 182, 160))
    a, b = iv.xy(view_box[0], view_box[3]), iv.xy(view_box[2], view_box[1])
    di.rectangle([a[0], a[1], b[0], b[1]], outline=YELLOW, width=max(2, SS * 2))
    di.rectangle([0, 0, iw - 1, ih - 1], outline=(90, 100, 120), width=SS)
    img.paste(inset, box[:2])

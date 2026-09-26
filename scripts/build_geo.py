"""Build assets/geo/*.json for map cards from Natural Earth (public domain, naturalearthdata.com).

One-off, run by hand when the data needs refreshing:
    python scripts/build_geo.py <dir with the three Natural Earth GeoJSON files>
Sources (github.com/nvkelso/natural-earth-vector, geojson/):
    ne_10m_admin_1_states_provinces.geojson, ne_50m_admin_0_countries.geojson, ne_10m_populated_places_simple.geojson
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "geo"


def _dp(points: list[list[float]], tol: float) -> list[list[float]]:
    """Douglas-Peucker line simplification."""
    if len(points) < 3:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
    far, idx = 0.0, 0
    for i, (x, y) in enumerate(points[1:-1], 1):
        d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
        if d > far:
            far, idx = d, i
    if far <= tol:
        return [points[0], points[-1]]
    return _dp(points[:idx + 1], tol)[:-1] + _dp(points[idx:], tol)


def _area(ring: list[list[float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))) / 2


def _polys(geom: dict, tol: float, min_area: float) -> list[list[list[float]]]:
    """Outer rings only (holes don't matter at card scale), simplified, tiny islets dropped."""
    parts = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    rings = []
    for poly in parts:
        pts, half = poly[0], len(poly[0]) // 2          # a closed ring's ends coincide: simplify two halves
        ring = _dp(pts[:half + 1], tol)[:-1] + _dp(pts[half:], tol)
        if len(ring) >= 4 and _area(ring) >= min_area:
            rings.append([[round(x, 3), round(y, 3)] for x, y in ring])
    return rings


def main(src: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    adm1 = json.loads((src / "ne_10m_admin_1_states_provinces.geojson").read_text(encoding="utf-8"))
    provinces = []
    for f in adm1["features"]:
        p = f["properties"]
        if p.get("adm0_a3") != "PHL":
            continue
        polys = _polys(f["geometry"], tol=0.004, min_area=0.0004)
        if polys:
            provinces.append({"name": p["name"], "type": p.get("type_en") or "", "region": p["region"],
                              "polys": polys})

    adm0 = json.loads((src / "ne_50m_admin_0_countries.geojson").read_text(encoding="utf-8"))
    countries = []
    for f in adm0["features"]:
        p = f["properties"]
        polys = _polys(f["geometry"], tol=0.03, min_area=0.01)
        if polys:
            countries.append({"name": p["NAME"], "long_name": p.get("NAME_LONG") or p["NAME"],
                              "iso": p.get("ADM0_A3") or "", "polys": polys})

    pp = json.loads((src / "ne_10m_populated_places_simple.geojson").read_text(encoding="utf-8"))
    places = []
    for f in pp["features"]:
        p = f["properties"]
        if p.get("adm0_a3") == "PHL" or p.get("scalerank", 10) <= 2 or p.get("adm0cap"):
            lon, lat = f["geometry"]["coordinates"]
            places.append({"name": p["name"], "country": p.get("adm0name") or "", "lon": round(lon, 3),
                           "lat": round(lat, 3), "ph": p.get("adm0_a3") == "PHL"})

    for name, data in (("ph_provinces", provinces), ("countries", countries), ("places", places)):
        (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                                          encoding="utf-8")
        print(name, len(data), f"{(OUT / f'{name}.json').stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

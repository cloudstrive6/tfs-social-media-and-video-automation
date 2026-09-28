"""Free vector engine (replaces AI images): the Motion Designer's plan -> a HyperFrames project -> MP4 / PNG.

The browser runtime (engine/runtime/*.js) draws the cast as SVG puppets, Fluent Emoji props (MIT) and
illustrated backgrounds, and animates everything on one GSAP timeline. HyperFrames (Apache-2.0) seeks that
timeline frame by frame in headless Chrome and encodes with FFmpeg. Picture only: captions + audio are added
by render.finish().
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from ..config import ROOT, channel
from ..models import (Actor, Background, Expression, MotionPlan, Pose, ScenePlan, Shot, ShotList, Who)
from . import maps

log = logging.getLogger(__name__)
ENGINE = ROOT / "engine"
RUNTIME = ["puppets.js", "backgrounds.js", "engine.js"]


@lru_cache
def emoji_index() -> dict:
    return json.loads((ENGINE / "assets" / "emoji" / "index.json").read_text(encoding="utf-8"))


def emoji_svg(key: str) -> str | None:
    f = ENGINE / "assets" / "emoji" / f"{key}.svg"
    if not f.exists():
        return None
    svg = f.read_text(encoding="utf-8")
    return svg.replace("<svg ", '<svg width="100%" height="100%" ', 1)


def vocabulary() -> str:
    """Everything the engine can draw, for the Motion Designer and the Visual Critic."""
    from typing import get_args

    groups: dict[str, list[str]] = {}
    for key, meta in emoji_index().items():
        groups.setdefault(meta["group"], []).append(key)
    emoji = "\n".join(f"- {g}: {', '.join(sorted(keys))}" for g, keys in groups.items())
    return (f"Sets (`background`): {', '.join(get_args(Background))}\n"
            f"Cast (`who`): {', '.join(get_args(Who))}\n"
            f"Poses: {', '.join(get_args(Pose))}\nExpressions: {', '.join(get_args(Expression))}\n"
            f"Emoji keys (props and `holds`), by group:\n{emoji}")


def fallback_scene(scene_id: int, background: str = "spotlight") -> ScenePlan:
    """The host explaining on a plain set: used for a scene the designer left out or that kept failing review."""
    host = Actor(who="kuya_standard", label="", x=0.5, scale=0.55, row="front", pose="point", expression="neutral",
                 speaking=True, facing="right", enter="none", holds="")
    return ScenePlan(scene_id=scene_id, kind="scene", background=background, camera="push_in", actors=[host],
                     props=[], bubbles=[], card_type="none", card_title="", card_lines=[])


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def sanitize(plan: MotionPlan, scene_ids: list[int]) -> MotionPlan:
    """One scene per script scene, in script order, with every number inside what the engine can draw."""
    by_id = {s.scene_id: s for s in plan.scenes}
    out = []
    for sid in scene_ids:
        sp = by_id.get(sid)
        if sp is None:
            log.warning("motion plan has no scene %s; host fallback", sid)
            out.append(fallback_scene(sid))
            continue
        if sp.kind == "card" and (sp.card_type == "none" or not (sp.card_title or sp.card_lines)):
            out.append(fallback_scene(sid, sp.background))
            continue
        actors = [a.model_copy(update={"x": _clamp(a.x, 0.1, 0.9), "scale": _clamp(a.scale, 0.2, 0.7),
                                       "holds": a.holds if a.holds and emoji_svg(a.holds) else ""})
                  for a in sp.actors[:3]]
        props = [p.model_copy(update={"x": _clamp(p.x, 0.05, 0.95), "y": _clamp(p.y, 0.05, 0.9),
                                      "size": _clamp(p.size, 0.05, 0.4), "count": int(_clamp(p.count, 1, 16)),
                                      "at": _clamp(p.at, 0, 0.8)})
                 for p in sp.props[:5] if emoji_svg(p.emoji)]
        bubbles = [b.model_copy(update={"at": _clamp(b.at, 0, 0.6)}) for b in sp.bubbles
                   if 0 <= b.actor < len(actors) and b.text.strip()][:1]
        out.append(sp.model_copy(update={"actors": actors, "props": props, "bubbles": bubbles}))
    return MotionPlan(look=plan.look, scenes=out)


def as_shots(plan: MotionPlan) -> ShotList:
    """The plan in the shot-list shape the Sound Designer and the review team read."""
    shots = []
    for sp in plan.scenes:
        if sp.kind == "card":
            desc = ""
        else:
            cast = ", ".join(f"{a.label or a.who} ({a.pose}, {a.expression}"
                             + (f", holding {a.holds}" if a.holds else "") + ")" for a in sp.actors)
            desc = (f"vector cartoon: {sp.background} set; {cast or 'no characters'}"
                    + (f"; props: {', '.join(p.emoji for p in sp.props)}" if sp.props else "")
                    + (f"; bubble: \"{sp.bubbles[0].text}\"" if sp.bubbles else ""))
        shots.append(Shot(scene_id=sp.scene_id, kind="card" if sp.kind == "card" else "illustration",
                          style="story", image_prompt=desc, card_type=sp.card_type if sp.kind == "card" else "none",
                          card_title=sp.card_title, card_lines=sp.card_lines, reuse_of_scene=0, motion=sp.camera))
    return ShotList(shots=shots)


def still_times(spec: dict) -> list[float]:
    """One moment per scene for the Visual Critic: late enough that entrances, props and bubbles are in."""
    return [round(sc["start"] + max(0.05, min(sc["dur"] * 0.72, sc["dur"] - 0.1)), 2) for sc in spec["scenes"]]


# ---------------------------------------------------------------- map cards (pre-projected for the browser)
def map_data(title: str, places: list[str], size: tuple[int, int]) -> dict | None:
    scene = maps.MapScene(title, places or [title], size, ss=1, caption_safe=size[1] > size[0] * 1.3)
    k = math.cos(math.radians((scene.view[1] + scene.view[3]) / 2))

    def box(b):
        lon0, lat0, lon1, lat1 = b
        return [round(lon0 * k, 3), round(-lat1, 3), round((lon1 - lon0) * k, 3), round(lat1 - lat0, 3)]

    def path(ring, shift=0.0):
        return "M" + " L".join(f"{(lon + shift) * k:.2f} {-lat:.2f}" for lon, lat in ring) + "Z"

    shifts = (0.0, 360.0) if scene.shift else (0.0,)
    union = (min(scene.start[0], scene.view[0]) - 20, min(scene.start[1], scene.view[1]) - 15,
             max(scene.start[2], scene.view[2]) + 20, max(scene.start[3], scene.view[3]) + 15)

    def visible(ring, shift):
        xs = [p[0] + shift for p in ring]
        ys = [p[1] for p in ring]
        return not (max(xs) < union[0] or min(xs) > union[2] or max(ys) < union[1] or min(ys) > union[3])

    land = [path(r, s) for c in maps._load("countries") if c["iso"] != "PHL"
            for r in c["polys"] for s in shifts if visible(r, s)]
    ph = [path(r) for p in maps._load("ph_provinces") for r in p["polys"]]
    hl = [path(r, s) for x in scene.hl if x.kind in ("area", "country") for r in x.polys for s in shifts
          if visible(r, s)]
    pins = []
    for x in scene.hl:
        lon, lat = scene._anchor(x)
        if x.kind != "sea":
            pins.append({"x": round(lon * k, 3), "y": round(-lat, 3), "label": x.label})
    route, route_len = None, 0.0
    home = next((x for x in scene.hl if not x.foreign), None)
    away = next((x for x in scene.hl if x.foreign), None)
    if home and away:
        (a0, b0), (a1, b1) = scene._anchor(home), scene._anchor(away)
        x0, y0, x1, y1 = a0 * k, -b0, a1 * k, -b1
        mx, my = (x0 + x1) / 2, min(y0, y1) - abs(x1 - x0) * 0.18
        route = f"M{x0:.2f} {y0:.2f} Q{mx:.2f} {my:.2f} {x1:.2f} {y1:.2f}"
        route_len = 1.2 * math.hypot(x1 - x0, y1 - y0)
    end = box(scene.view)
    return {"start": box(scene.start), "end": end, "land": land, "ph": ph, "hl": hl, "pins": pins,
            "route": route, "routeLength": round(route_len, 2), "stroke": round(end[2] / 900, 4)}


# ---------------------------------------------------------------- plan -> spec
def spec_from_plan(plan, starts: list[float], total: float, clips: list, size: tuple[int, int],
                   comp_id: str = "main", hook_until: float = 0.0) -> dict:
    """`hook_until`: seconds the on-screen hook text owns the top of a vertical (speech bubbles wait for it)."""
    w, h = size
    bounds = list(starts) + [total]
    scenes, used = [], set()
    by_id = {s.scene_id: s for s in plan.scenes}
    order = [s.scene_id for s in plan.scenes]
    for i, clip in enumerate(clips):
        sp = by_id.get(order[i]) if i < len(order) else None
        words = getattr(clip, "words", None) or []
        t0, dur = bounds[i], max(0.2, bounds[i + 1] - bounds[i])
        if sp is None:
            scenes.append({"start": t0, "dur": dur, "kind": "scene", "background": "plain", "camera": "static",
                           "actors": [], "props": [], "bubbles": []})
            continue
        sc = {"start": round(t0, 3), "dur": round(dur, 3), "kind": sp.kind, "background": sp.background,
              "camera": sp.camera,
              "actors": [a.model_dump() | {"seed": 11 * (i + 1) + k} for k, a in enumerate(sp.actors)],
              "props": [p.model_dump() for p in sp.props if emoji_svg(p.emoji)],
              "bubbles": [b.model_dump() for b in sp.bubbles],
              "mouth": [[round(ws, 3), round(we, 3)] for _, ws, we in words]}
        for a in sc["actors"]:
            if a.get("holds") and not emoji_svg(a["holds"]):
                a["holds"] = ""
        used |= {p["emoji"] for p in sc["props"]} | {a["holds"] for a in sc["actors"] if a.get("holds")}
        if sp.kind == "card":
            card = {"type": sp.card_type, "title": sp.card_title, "lines": sp.card_lines}
            if sp.card_type == "map":
                try:
                    card["map"] = map_data(sp.card_title, sp.card_lines, size)
                except Exception:
                    log.exception("map data failed; plain card")
                    card["type"] = "stat"
            sc["card"] = card
        scenes.append(sc)
    return {"id": comp_id, "width": w, "height": h, "duration": round(total, 3), "look": plan.look,
            "hookUntil": hook_until,
            "emoji": {k: emoji_svg(k) for k in sorted(used) if emoji_svg(k)}, "scenes": scenes}


# ---------------------------------------------------------------- project + render
FONT_CSS = """@font-face{font-family:Anton;src:url(Anton-Regular.ttf)}
@font-face{font-family:Montserrat;font-weight:800;src:url(Montserrat-ExtraBold.ttf)}
html,body{margin:0;padding:0;background:#0e1018}
#stage{position:relative;overflow:hidden;background:#0e1018}
.bubble,.card{font-kerning:normal}"""


def build_project(spec: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ENGINE / "node_modules" / "gsap" / "dist" / "gsap.min.js", out_dir / "gsap.min.js")
    for font in ("Anton-Regular.ttf", "Montserrat-ExtraBold.ttf"):
        src = ROOT / "assets" / "fonts" / font
        if src.exists():
            shutil.copy2(src, out_dir / font)
    w, h = spec["width"], spec["height"]
    # one inline script, in order: HyperFrames checks for an inline window.__timelines registration and may
    # load external scripts in a different order than written
    runtime = "\n".join((ENGINE / "runtime" / n).read_text(encoding="utf-8") for n in RUNTIME)
    spec_json = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/")
    comp = spec["id"]
    html = (f'<!doctype html><html><head><meta charset="utf-8"><style>{FONT_CSS}</style></head><body>'
            f'<div id="stage" data-composition-id="{comp}" data-start="0" data-duration="{spec["duration"]}" '
            f'data-width="{w}" data-height="{h}" style="width:{w}px;height:{h}px">'
            '<script src="gsap.min.js"></script>'
            f'<script>\nwindow.SPEC = {spec_json};\n{runtime}\n'
            f'window.__timelines = window.__timelines || {{}};\n'
            f'window.__timelines["{comp}"] = window.__timelines["{comp}"];\n'
            '</script></div></body></html>')
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    return out_dir / "index.html"


def _hyperframes(args: list[str], cwd: Path, timeout: int = 7200) -> None:
    npx = shutil.which("npx") or "npx"
    cmd = [npx, "--prefix", str(ENGINE), "hyperframes", *args]
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=timeout,
                         env={**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1"})
    if res.returncode:
        raise RuntimeError(f"hyperframes {args[0]} failed: {(res.stderr or res.stdout)[-2000:]}")


def render(spec: dict, work: Path, out: Path) -> Path:
    """Silent MP4 of the whole plan at the configured fps."""
    project = work / "vector"
    build_project(spec, project)
    vcfg = channel()["video"]
    fps = vcfg.get("fps_vector", 60)
    workers = str(vcfg.get("render_workers", max(1, min(4, (os.cpu_count() or 2)))))
    _hyperframes(["render", "--fps", str(fps), "--quality", "standard", "--workers", workers, "-o",
                  str(out.resolve())], cwd=project)
    return out


def snapshot(spec: dict, work: Path, times: list[float], out_dir: Path) -> list[Path]:
    """PNG stills at the given times (Visual Critic, thumbnails, carousel art) without a full render."""
    project = work / "vector_snap"
    build_project(spec, project)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.png"):
        f.unlink()
    _hyperframes(["snapshot", "--at", ",".join(f"{t:.2f}" for t in times), "-o", str(out_dir.resolve())], cwd=project)
    # frame-00-at-1.5s.png, ..., frame-100-at-...: numeric order, not string order
    frames = sorted(out_dir.glob("frame-*.png"), key=lambda f: int(f.stem.split("-")[1]))
    return frames[:len(times)]                       # HyperFrames may add a closing frame of its own


def stills(plan: MotionPlan, size: tuple[int, int], work: Path, out_dir: Path, hold: float = 3.0) -> list[Path]:
    """One finished still per planned scene (thumbnail and carousel art): each scene played for `hold` seconds
    and caught after its entrances, with nobody mid-word."""
    n = len(plan.scenes)
    spec = spec_from_plan(plan, [k * hold for k in range(n)], n * hold, [None] * n, size, comp_id="stills")
    return snapshot(spec, work, [k * hold + hold * 0.8 for k in range(n)], out_dir)


def cast_sheets(out_dir: Path = ROOT / "assets" / "characters_vector") -> list[Path]:
    """Model sheets of the recurring cast as the engine draws them (the Visual QA compares frames to these)."""
    cast = {"kuya_standard": "point", "juan": "stand", "tito_trapo": "hands_on_hips"}
    scenes = [ScenePlan(scene_id=i, kind="scene", background="plain", camera="static", props=[], bubbles=[],
                        actors=[Actor(who=who, label="", x=0.5, scale=0.8, row="front", pose=pose,
                                      expression="neutral", speaking=False, facing="right", enter="none", holds="")],
                        card_type="none", card_title="", card_lines=[]) for i, (who, pose) in enumerate(cast.items())]
    work = Path(os.environ.get("TEMP", "/tmp")) / "tfs_cast"
    shots = stills(MotionPlan(look="flat", scenes=scenes), (900, 1200), work, work / "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for who, png in zip(cast, shots):
        shutil.copy(png, out_dir / f"{who}.png")
        out.append(out_dir / f"{who}.png")
    return out

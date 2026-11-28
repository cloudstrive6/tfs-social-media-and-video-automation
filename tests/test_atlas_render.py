"""Render checks for the atlas runtime (HyperFrames + headless Chrome). Slow, so they only run with
TFS_RENDER_TESTS=1:

    TFS_RENDER_TESTS=1 .venv/Scripts/python.exe -m pytest -q tests/test_atlas_render.py

test_v5_frames_unchanged is the regression guard for the approved dry-run Short v5 (owner, 2026-11-25): the v5 shot
list and its captions (tests/fixtures/atlas_v5_*.json) are rendered with the runtime that made v5
(tests/fixtures/atlas_v5_runtime.js, frozen from commit 01082f3) and with today's runtime, and every frame must
match pixel for pixel. New blocks must stay inert for shots and words that do not use them.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from tfs.media import atlas

pytestmark = pytest.mark.skipif(os.environ.get("TFS_RENDER_TESTS") != "1", reason="render test: set TFS_RENDER_TESTS=1")
FIX = Path(__file__).parent / "fixtures"
V5_TIMES = [0.0, 0.9, 2.6, 4.4, 6.2, 8.4, 10.6, 13.3, 15.8, 18.6, 21.4, 24.4, 27.0, 29.9, 32.6, 35.1, 37.7, 40.2, 41.2]


def _photo(path: Path, n: int) -> None:
    """A stand-in photo (the v5 photos are not in the repo): a colour gradient, the same for both renders."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"gradients=s=1080x1920:seed={n}:n=3",
                    "-frames:v", "1", str(path)], check=True)


def _snap(html_runtime: str | None, sp: dict, work: Path, assets: dict, times: list[float]) -> list[np.ndarray]:
    project = work / "proj"
    if project.exists():
        shutil.rmtree(project)
    atlas.build_project(sp, project, assets)
    if html_runtime is not None:                       # swap today's runtime for the frozen one
        page = project / "index.html"
        html = page.read_text(encoding="utf-8")
        today = "\n".join((atlas.ENGINE / "runtime" / f).read_text(encoding="utf-8")
                          for f in ("atlas_lib.js", "atlas_blocks.js", "atlas.js"))
        assert today in html
        page.write_text(html.replace(today, html_runtime), encoding="utf-8")
    out = work / "snaps"
    if out.exists():
        shutil.rmtree(out)
    atlas._hyperframes(["snapshot", "--at", ",".join(f"{t:.2f}" for t in times), "--no-end", "--describe", "false",
                        "-o", str(out.resolve())], cwd=project)
    frames = sorted(out.glob("frame-*.png"), key=lambda f: int(f.stem.split("-")[1]))[:len(times)]
    from PIL import Image
    return [np.asarray(Image.open(f).convert("RGB"), dtype=np.int16) for f in frames]


def test_v5_frames_unchanged(tmp_path):
    shots = json.loads((FIX / "atlas_v5_shots.json").read_text(encoding="utf-8"))
    words = json.loads((FIX / "atlas_v5_words.json").read_text(encoding="utf-8"))
    assets = {}
    for i, src in enumerate(sorted({s["src"] for s in shots if s.get("src")})):
        f = tmp_path / f"photo{i}.jpg"
        _photo(f, i + 1)
        assets[src] = f
    sp = atlas.spec("v5-regress", (1080, 1920), shots, words, 41.655, safe=False)   # v5 predates the safe area
    assert "globe" not in sp["geo"]
    old = _snap((FIX / "atlas_v5_runtime.js").read_text(encoding="utf-8"), sp, tmp_path / "old", assets, V5_TIMES)
    new = _snap(None, sp, tmp_path / "new", assets, V5_TIMES)
    assert len(old) == len(new) == len(V5_TIMES)
    diffs = [int(np.abs(a - b).max()) for a, b in zip(old, new)]
    assert diffs == [0] * len(V5_TIMES), f"frames differ from the approved v5 runtime: {dict(zip(V5_TIMES, diffs))}"


def test_v3_blocks_render(tmp_path):
    """Every v3 block builds without a runtime error and puts pixels on screen at its build moments."""
    ph, mnl = atlas.locate("Philippines"), atlas.locate("Manila")
    shots = [
        {"k": "map", "view": "ph", "fill": "ph", "draw": 0.001, "instant": True, "t0": 0.0, "t1": 0.0},
        {"k": "globe", "t0": 0.0, "t1": 5.0, "focus": {"lon": ph["lon"], "lat": ph["lat"]}, "zoom": 2.5,
         "highlight": [{"iso": "PHL", "name": "Philippines", "at": 2.4}],
         "places": [{"name": "Manila", "lon": mnl["lon"], "lat": mnl["lat"], "at": 2.8}],
         "arcs": [{"from": [55.3, 25.2], "to": [mnl["lon"], mnl["lat"]], "at": 3.0}],
         "stamp": {"text": "VOLUNTARY", "at": 3.5}},
        {"k": "checklist", "t0": 5.0, "t1": 9.0, "head": "CHECK", "items": [{"text": "A bill", "mark": "x", "at": 5.5},
                                                                           {"text": "An average", "mark": "tick", "at": 6.5}]},
        {"k": "linechart", "t0": 9.0, "t1": 13.0, "big": "₱19.66 TRILLION", "callout": "+12.6%",
         "items": [{"label": "2025", "num": 17.4}, {"num": 18.5}, {"label": "2026", "num": 19.66}]},
        {"k": "barchart", "t0": 13.0, "t1": 17.0, "callout": "ALMOST 2X",
         "items": [{"label": "A", "value": "₱0.88T", "num": 0.88, "at": 13.5}, {"label": "B", "value": "₱1.37T", "num": 1.37, "at": 14.3}]},
        {"k": "waffle", "t0": 17.0, "t1": 21.0, "big": "≈ 28%", "small": "to debt", "frac": 0.28},
        {"k": "balance", "t0": 21.0, "t1": 25.0, "big": "₱170,598", "small": "AN AVERAGE", "frac": 0.05, "label": "TOTAL"},
        {"k": "dates", "t0": 25.0, "t1": 29.0, "items": [{"big": "23", "label": "NOV", "small": "Debate", "at": 25.3}]},
        {"k": "media", "t0": 29.0, "t1": 33.0, "icon": "building", "name": "SENATE", "rows": [{"text": "One", "at": 29.5}],
         "chips": [{"text": "ILLUSTRATIVE", "at": 30.0}]},
    ]
    words = [{"w": "₱170,598", "t0": 1.0, "t1": 1.6, "brk": True, "key": True}]
    sp = atlas.spec("v3-blocks", (1080, 1920), shots, words, 33.5)
    assert sp["geo"]["globe"]
    times = [4.6, 8.6, 12.6, 16.6, 20.6, 24.6, 28.6, 32.6]
    frames = _snap(None, sp, tmp_path, {}, times)
    assert len(frames) == len(times)
    for t, f in zip(times, frames):
        assert f.std() > 8, f"frame at {t} s looks empty"

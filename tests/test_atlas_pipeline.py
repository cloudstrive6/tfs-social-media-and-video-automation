"""Style v2 wiring, end to end offline: fake narrator, designer, Commons and renderer; real planner, mix, master,
mux and captions. Needs ffmpeg (skipped without it)."""
import json
import shutil
import subprocess

import numpy as np
import pytest

from tfs.models import AtlasItem, AtlasPlan, AtlasScene, AtlasShot, HookReview, Scene, Script

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def test_atlas_long_form_end_to_end(tmp_path, monkeypatch):
    from tfs import pipeline
    from tfs.media import atlas, sfx_v2, tts
    from tfs.media import broll

    d = tmp_path / "item"
    d.mkdir()
    script = Script(scenes=[Scene(id=1, chapter="Cold open", speaker="NARRATOR", text="Anim na taon. House.", visual=""),
                            Scene(id=2, chapter="Chapter 1: Built to fail", speaker="NARRATOR",
                                  text="Wala pang presidente na natanggal: zero.", visual="")],
                    sources=[])

    def fake_tts(scenes, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        clips = []
        for sc in scenes:
            t = np.arange(int(48000 * 5.0)) / 48000
            y = (0.2 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 3 * t) > 0)).astype(np.float32)
            p = sfx_v2.write_wav(out_dir / f"{sc.id:03d}.wav", y)
            words = [(w, 0.6 * i, 0.6 * i + 0.5) for i, w in enumerate(sc.text.split())]
            clips.append(tts.Clip(p, 5.0, words))
        return clips

    plan = AtlasPlan(scenes=[
        AtlasScene(scene_id=1, shots=[AtlasShot(k="map", view="ph", fill="ph"),
                                      AtlasShot(k="broll", at_word="House", broll_query="Batasang Pambansa",
                                                word="THE HOUSE")]),
        AtlasScene(scene_id=2, shots=[AtlasShot(k="broll", hero=True, word="METRO MANILA"),
                                      AtlasShot(k="cards", at_word="zero", items=[AtlasItem(big="0", small="removed")])])])
    rendered = {}

    def fake_render(sp, work, out, assets=None):
        rendered.update(spec=sp, assets=assets)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"color=c=black:s=320x180:d={sp['duration']}:r=10", "-pix_fmt", "yuv420p", str(out)], check=True)
        return out

    monkeypatch.setattr(pipeline.tts, "synthesize", fake_tts)
    monkeypatch.setattr(pipeline.packaging, "atlas_plan", lambda *a, **k: plan)
    monkeypatch.setattr(broll, "search", lambda q, limit=20: [])           # nothing licensed: type card fallback
    monkeypatch.setattr(atlas, "render", fake_render)
    monkeypatch.setattr(pipeline, "_dossier", lambda d: "")
    starts, shots = pipeline._atlas_video({"id": "2026-12-01-long0", "kind": "long_form"}, d, script, (1920, 1080))

    kinds = [s["k"] for s in shots]
    assert kinds[:2] == ["map", "bigtext"]                                  # no licensed photo -> type, never unlicensed
    assert "title" in kinds                                                 # chapter card in the pause
    for a, b in zip(shots, shots[1:]):
        assert a["t1"] <= b["t0"] + 1e-6, (a, b)                      # nothing overlaps
    hero = next(s for s in shots if s.get("src") == "assets/hero.mp4")
    assert rendered["assets"]["assets/hero.mp4"].exists()
    zero = next(s for s in shots if s["k"] == "cards")
    assert zero["t0"] == round(starts[1] + 5 * 0.6, 3)                      # anchored on the word "zero."
    assert hero["t0"] == starts[1]
    assert rendered["spec"]["words"][0]["w"] == "Anim"
    rep = json.loads((d / "sound_report.json").read_text(encoding="utf-8"))
    assert abs(rep["lufs"] + 14) <= 1.0 and rep["peak"] < -1.0
    assert rep["reveals"] and rep["voice_over_sfx_db_p10"] >= 15
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                            str(d / "video.mp4")], capture_output=True, text=True).stdout.split()
    assert sorted(probe) == ["audio", "video"] and (d / "captions.srt").exists()

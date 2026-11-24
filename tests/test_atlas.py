"""Atlas engine (style v2): geometry, timing and project building, offline (no render)."""
from tfs.config import ROOT
from tfs.media import atlas


def test_geo_views_match_aspect():
    for w, h in ((1920, 1080), (1080, 1920)):
        g = atlas.geo(round(w / h, 4))
        for name, (x, y, vw, vh) in g["views"].items():
            assert abs(vw / vh - w / h) < 0.01, name
        assert g["ph"].startswith("M") and g["nz"].startswith("M") and g["phProv"]


def test_place_matches_pilot_rule():
    lines = [{"shots": [(0.0, 0.5, {"k": "map"}), (0.5, 1.0, {"k": "cards", "items": []})]},
             {"shots": [(0.0, 1.0, {"k": "doc"})], "pad": 2.6, "pad_shots": [{"k": "title", "mat": True}]}]
    shots, times, total = atlas.place(lines, [4.0, 2.0])
    assert times == [[0.4, 4.4], [4.75, 6.75]]
    assert shots[0]["t0"] == 0.4 and shots[0]["t1"] == 2.4
    assert shots[1]["t1"] == round(4.4 + atlas.GAP, 3)           # last shot of a line holds through the gap
    pad = [s for s in shots if s["k"] == "title"][0]
    assert pad["t0"] == round(6.75 + atlas.GAP, 3) and pad["t1"] == round(6.75 + atlas.GAP + 2.6, 3)
    assert total == round(6.75 + atlas.GAP + 2.6 + 0.4, 2)


def test_frac_at_clamps():
    assert atlas.frac_at(33.3, 26.693, 18.037) == 0.3663
    assert atlas.frac_at(10, 20, 5) == 0.0 and atlas.frac_at(30, 20, 5) == 1.0


def test_build_project_static_video_and_assets(tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"\x00")
    shots = [{"k": "broll", "kind": "photo", "src": "assets/a.jpg", "t0": 0.4, "t1": 3.0, "word": "THE HOUSE"},
             {"k": "broll", "kind": "video", "src": "assets/b.mp4", "t0": 3.0, "t1": 6.0, "mediaStart": 1.5},
             {"k": "cards", "items": [{"big": "0", "small": "x"}], "src": "1987 Constitution", "t0": 6.0, "t1": 9.0}]
    sp = atlas.spec("t", (1080, 1920), shots, [{"w": "Hi", "t0": 0.5, "t1": 0.8, "brk": False}], 9.4)
    html = atlas.build_project(sp, tmp_path / "proj", {"assets/a.jpg": img, "assets/b.mp4": vid}).read_text(encoding="utf-8")
    assert '<video id="bv0" class="clip" src="assets/b.mp4"' in html and 'data-media-start="1.5"' in html
    assert html.index("<video") < html.index("<script")             # static media before the runtime
    for f in ("gsap.min.js", "Anton-Regular.ttf", "textures/paper_v.jpg", "textures/tfs_logo.png", "assets/a.jpg"):
        assert (tmp_path / "proj" / f).exists(), f
    assert "@thefilipinostandard" in html                             # vertical watermark lives in the runtime


def test_runtime_has_every_shot_kind():
    js = (ROOT / "engine" / "runtime" / "atlas.js").read_text(encoding="utf-8")
    for k in ("map(s)", "bigtext(s)", "title(s)", "broll(s)", "doc(s)", "cards(s)", "bars(s)", "timeline(s)",
              "compare(s)", "seats(s)", "split(s)"):
        assert k in js, k
    assert "—" not in js                                        # no em-dashes anywhere

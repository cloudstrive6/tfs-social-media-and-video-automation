"""Atlas blocks v3 (2026-11-25), offline: the JS helpers (run under node), models, word anchors, globe and media
resolution, caption key words, the variety QC, the new sounds and their cues, and the v5 sound guard."""
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from tfs.config import ROOT
from tfs.media import atlas
from tfs.media import atlas_plan as ap
from tfs.media import sfx_v2 as sv
from tfs.models import AtlasItem, AtlasPlan, AtlasScene, AtlasShot

FIX = Path(__file__).parent / "fixtures"
LIB = ROOT / "engine" / "runtime" / "atlas_lib.js"
BLOCKS = ROOT / "engine" / "runtime" / "atlas_blocks.js"
SR = sv.SR


def node(expr: str):
    """Evaluate `expr` with window.TFSLIB loaded (as L) under node; returns the JSON result."""
    if not shutil.which("node"):
        pytest.skip("node not installed")
    code = (f"require('vm').runInThisContext(require('fs').readFileSync({json.dumps(str(LIB))},'utf8'));"
            f"const L=globalThis.TFSLIB;process.stdout.write(JSON.stringify({expr}));")
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


@dataclass
class Clip:
    path: Path
    duration: float
    words: list


@dataclass
class Sc:
    id: int
    chapter: str = ""
    text: str = ""


# ---------------------------------------------------------------- JS helpers
def test_count_up_figures_keep_prefix_suffix_commas_and_end_exactly():
    got = node("[L.figAt('₱19.66 TRILLION',0.5), L.figAt('₱170,598',0.5), L.figAt('-30%',0.25),"
               " L.figAt('₱170,598',1), L.figAt('NO NUMBER',0.3), L.figAt('≈ 28%',0)]")
    assert got == ["₱9.83 TRILLION", "₱85,299", "-8%", "₱170,598", "NO NUMBER", "≈ 0%"]


def test_globe_projection_centre_horizon_and_far_side():
    centre, far, clipped = node("[L.rot(121,14,121,14), L.rot(301,14,121,14)[0] < 0,"
                                " L.clipRing([[100,-10],[140,-10],[140,30],[100,30]].map(p => L.rot(p[0],p[1],20,0)))]")
    assert [round(x, 6) for x in centre] == [1, 0, 0]          # the focus point faces the viewer
    assert far is True                                           # the antipode is hidden
    assert all(p[0] >= -1e-9 for p in clipped)                  # nothing behind the globe survives
    assert sum(abs(np.hypot(p[1], p[2]) - 1) < 1e-6 for p in clipped) >= 3   # the cut follows the horizon circle


def test_route_arc_slerp_and_partial_draw():
    mid, start, d0, d1 = node("[L.slerp([0,0],[90,0],0.5), L.slerp([120.98,14.6],[55.29,25.2],0),"
                              " L.arcPath([120.98,14.6],[55.29,25.2],0.3,100,15,300,500,500),"
                              " L.arcPath([120.98,14.6],[55.29,25.2],1,100,15,300,500,500)]")
    assert [round(x, 6) for x in mid] == [45, 0]
    assert [round(x, 3) for x in start] == [120.98, 14.6]
    assert d0.startswith("M") and len(d1) > len(d0)             # drawing further makes a longer path


def test_step_times_same_in_js_and_python():
    items = [{"at": 3.0}, {}, {"at": 99}]
    js = node(f"L.stepTimes({json.dumps(items)}, 2, 10, 0.45, 0.8)")
    py = ap.step_times([3.0, None, 99], 2, 10, 0.45, 0.8)
    assert [round(x, 3) for x in js] == py == [3.0, round(2 + 0.45 + (10 - 2 - 0.45 - 1) / 3, 3), round(2 + 0.45 + 2 * (6.55 / 3), 3)]


def test_runtime_files_have_every_v3_kind_and_no_dashes():
    js = BLOCKS.read_text(encoding="utf-8")
    for k in ("build.globe", "build.checklist", "build.linechart", "build.barchart", "build.waffle", "build.balance",
              "build.dates", "build.media", "function stamp"):
        assert k in js, k
    for f in (LIB, BLOCKS, ROOT / "engine" / "runtime" / "atlas.js", ROOT / "prompts" / "atlas_designer.md"):
        txt = f.read_text(encoding="utf-8")
        assert "—" not in txt and "–" not in txt, f.name
    assert "requestAnimationFrame" not in js and "Date.now" not in js and "Math.random" not in js


def test_project_inlines_helpers_and_globe_rings_only_with_a_globe(tmp_path):
    plain = atlas.spec("a", (1080, 1920), [{"k": "cards", "items": [], "t0": 0, "t1": 2}], [], 2.4)
    assert "globe" not in plain["geo"]
    sp = atlas.spec("b", (1080, 1920), [{"k": "globe", "t0": 0, "t1": 3}], [], 3.4)
    assert len(sp["geo"]["globe"]) > 150 and sp["geo"]["globe"][0]["rings"]
    html = atlas.build_project(sp, tmp_path / "p").read_text(encoding="utf-8")
    assert html.index("window.TFSLIB") < html.index("window.TFS_BLOCKS") < html.index("window.__timelines[S.id]")


def test_gazetteer_finds_cities_and_countries():
    assert atlas.locate("Manila")["lat"] == pytest.approx(14.6, abs=0.1)
    assert atlas.country("Philippines")["iso"] == "PHL" and atlas.country("PHL")["name"] == "Philippines"
    assert atlas.locate("Dubai") and atlas.locate("Japan") and atlas.locate("Atlantis") is None


# ---------------------------------------------------------------- plan -> shots
WORDS = [("Hindi", 0.0, 0.3), ("ito", 0.3, 0.5), ("bill.", 0.6, 1.0), ("Voluntary", 1.6, 2.2), ("lang,", 2.2, 2.5),
         ("average", 3.0, 3.5), ("lang", 3.5, 3.7), ("ng", 3.7, 3.8), ("170,598", 4.0, 4.8), ("pesos.", 4.8, 5.2),
         ("Taxes", 6.0, 6.4), ("ang", 6.4, 6.5), ("ambag.", 6.6, 7.0)]


def _plan_one(*shots, key_words=()):
    return AtlasPlan(scenes=[AtlasScene(scene_id=1, shots=list(shots), key_words=list(key_words))])


def test_checklist_rows_stamp_and_number_land_on_their_words():
    plan = _plan_one(AtlasShot(k="checklist", head="THE SHARE", stamp="VOLUNTARY", stamp_word="Voluntary", items=[
        AtlasItem(text="A bill", mark="x", at_word="bill"), AtlasItem(text="An average", mark="tick", at_word="average"),
        AtlasItem(text="Paid by taxes", at_word="nowhere")]))
    shots = ap.to_shots(plan, [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", lambda *a: None)
    ck = [s for s in shots if s["k"] == "checklist"][0]
    assert [i["at"] for i in ck["items"][:2]] == [1.0, 3.4]                # 0.4 s scene start + word start
    assert ck["items"][0]["mark"] == "x" and ck["items"][2]["mark"] == "tick"
    assert ck["items"][2]["at"] > ck["items"][1]["at"] - 5                  # unanchored row still gets a time
    assert ck["stamp"] == {"text": "VOLUNTARY", "color": "red", "at": 2.0}


def test_linechart_counts_on_the_spoken_number_and_marks_it_key():
    plan = _plan_one(AtlasShot(k="linechart", big="₱170,598", big_word="170,598",
                               items=[AtlasItem(label="2025", num=1), AtlasItem(label="2026", num=2)]))
    shots = ap.to_shots(plan, [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", lambda *a: None)
    lc = [s for s in shots if s["k"] == "linechart"][0]
    assert lc["bigAt"] == 4.4 and lc["keyAt"] == [4.4]


def test_globe_resolves_focus_countries_cities_and_routes():
    plan = _plan_one(AtlasShot(k="globe", focus="Philippines", highlight=["Philippines", "Narnia"],
                               places=["Manila", "Dubai"], arcs=["Dubai > Manila", "Nowhere > Manila"], zoom=9))
    shots = ap.to_shots(plan, [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", lambda *a: None)
    g = [s for s in shots if s["k"] == "globe"][0]
    assert g["focus"]["lon"] == pytest.approx(122, abs=1) and g["zoom"] == 6.0
    assert [h["iso"] for h in g["highlight"]] == ["PHL"]
    assert [p["name"] for p in g["places"]] == ["Manila", "Dubai"] and len(g["arcs"]) == 1
    rot_at, rot_dur = ap.globe_timing(g["t0"], g["t1"])
    assert g["highlight"][0]["at"] >= rot_at + rot_dur and all(p["at"] for p in g["places"])


def test_media_card_uses_a_licensed_photo_or_a_drawn_icon():
    shot = AtlasShot(k="media", broll_query="Senate session hall", name="SENATE", role="23 NOV 2026", icon="building",
                     rows=[AtlasItem(text="No mechanism", at_word="Taxes"), AtlasItem(text="Pay taxes", color="red")],
                     chips=[AtlasItem(text="file photo", at_word="average")])
    found = lambda q, w, a, b: {"kind": "photo", "src": "assets/b01.jpg", "credit": "Photo: X, CC BY 4.0"}
    shots = ap.to_shots(_plan_one(shot), [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", found)
    m = [s for s in shots if s["k"] == "media"][0]
    assert m["src"] == "assets/b01.jpg" and "icon" not in m and m["name"] == "SENATE"
    assert m["rows"][0]["at"] == 6.4 and m["chips"] == [{"text": "FILE PHOTO", "at": 3.4}]
    none = ap.to_shots(_plan_one(shot), [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", lambda *a: None)
    m2 = [s for s in none if s["k"] == "media"][0]
    assert "src" not in m2 and m2["icon"] == "building"


def test_old_kinds_get_no_new_fields():
    plan = _plan_one(AtlasShot(k="cards", items=[AtlasItem(big="0", small="x")]), AtlasShot(k="map", view="ph", at_word="average"))
    shots = ap.to_shots(plan, [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", lambda *a: None)
    for s in shots:
        assert not {"stamp", "keyAt", "bigAt", "calloutAt"} & set(s), s


# ---------------------------------------------------------------- caption key words
def _words():
    return ap.caption_words([Clip(Path("a"), 7.2, WORDS)], [0.4])


def test_key_words_one_per_sentence_numbers_first():
    plan = _plan_one(AtlasShot(k="cards"), key_words=["Voluntary", "average", "Taxes"])
    shots = [{"k": "linechart", "t0": 0.4, "t1": 7.0, "keyAt": [4.4]}]
    out = ap.mark_keys(_words(), plan, [Sc(1)], [0.4], 8.0, shots)
    keys = [w["w"] for w in out if w.get("key")]
    assert keys == ["170,598", "Taxes"]       # "Voluntary" and "average" share the number's sentence; the number wins


def test_no_key_words_leaves_captions_untouched():
    words = _words()
    assert ap.mark_keys(words, _plan_one(AtlasShot(k="cards")), [Sc(1)], [0.4], 8.0, []) == words


# ---------------------------------------------------------------- variety
def test_variety_flags_a_family_over_15_seconds_and_counts_builds():
    shots = [{"k": "map", "t0": 0.0, "t1": 0.0}, {"k": "bigtext", "t0": 0.0, "t1": 3.0},
             {"k": "cards", "t0": 3.0, "t1": 9.0}, {"k": "linechart", "t0": 9.0, "t1": 14.0, "bigAt": 9.5},
             {"k": "waffle", "t0": 14.0, "t1": 19.5}, {"k": "globe", "t0": 19.5, "t1": 24.0},
             {"k": "media", "t0": 24.0, "t1": 29.0, "icon": "person", "rows": [{"at": 25}, {"at": 26}]}]
    runs = ap.family_runs(shots)
    assert [r[0] for r in runs] == ["title", "chart", "map", "icon"]
    probs = ap.variety_problems(shots)
    assert len(probs) == 1 and probs[0].startswith("chart runs 16.5 s")
    assert ap.builds(shots[3]) == 1 and ap.builds(shots[6]) == 2
    assert ap.variety_problems(shots[:4]) == []


def test_v5_short_passes_the_variety_rule():
    shots = json.loads((FIX / "atlas_v5_shots.json").read_text(encoding="utf-8"))
    assert ap.variety_problems(shots) == []


# ---------------------------------------------------------------- sound
def _centroid(x):
    X = np.abs(np.fft.rfft(x))
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return float((X * f).sum() / X.sum())


def test_new_sounds_match_the_measured_reel():
    hit, tick, thump = sv.stamp_hit(), sv.ui_tick(), sv.sub_thump()
    assert 800 <= _centroid(hit) <= 1100 and 0.2 <= len(hit) / SR <= 0.4
    assert _centroid(tick) > 4000 and len(tick) / SR < 0.12
    P = np.abs(np.fft.rfft(thump)) ** 2
    f = np.fft.rfftfreq(len(thump), 1 / SR)
    assert _centroid(thump) < 600 and P[f < 150].sum() / P.sum() > 0.9


def test_v5_cues_are_exactly_as_approved():
    shots = json.loads((FIX / "atlas_v5_shots.json").read_text(encoding="utf-8"))
    cues, track, reveals = sv.build_cues(shots, 41.655)
    assert [(t, n) for t, n, _ in cues] == [
        (0.0, "card slap"), (2.12, "soft air"), (5.51, "paper swish"), (5.86, "pen circle"), (10.04, "card slap"),
        (12.76, "card slap"), (13.98, "card slap"), (15.2, "card slap"), (17.27, "soft air"), (20.26, "paper swish"),
        (20.61, "pen circle"), (24.09, "marker swipe"), (28.18, "card slap"), (29.52, "card slap"), (31.7, "soft air"),
        (34.11, "card slap"), (36.45, "card slap"), (39.58, "card slap"), (39.58, "low hit")]
    assert reveals == [39.53]
    assert float(np.sqrt((track.astype(np.float64) ** 2).mean())) == pytest.approx(0.004245083, rel=1e-4)


def v3_shots():
    return [
        {"k": "globe", "t0": 0.4, "t1": 5.0, "highlight": [{"iso": "PHL", "at": 2.9}],
         "places": [{"name": "Manila", "at": 3.4}], "arcs": [{"from": [55, 25], "to": [121, 14.6], "at": 3.8}]},
        {"k": "checklist", "t0": 5.0, "t1": 10.0, "items": [{"text": "a", "mark": "x", "at": 5.6}, {"text": "b", "at": 7.0}],
         "stamp": {"text": "VOLUNTARY", "at": 8.2}},
        {"k": "linechart", "t0": 10.0, "t1": 15.0, "big": "₱19.66T", "callout": "+12%", "bigAt": 10.6},
        {"k": "barchart", "t0": 15.0, "t1": 20.0, "callout": "2X", "items": [{"value": "1", "at": 15.5}, {"value": "2", "at": 16.6}]},
        {"k": "media", "t0": 20.0, "t1": 25.0, "rows": [{"text": "x", "at": 21.0}], "chips": [{"text": "ALLEGED", "at": 22.5}]},
        {"k": "dates", "t0": 25.0, "t1": 29.0, "items": [{"big": "17", "at": 25.3}, {"big": "26", "at": 27.3}]},
    ]


def test_v3_cues_land_on_their_build_steps():
    cues, _, _ = sv.build_cues(v3_shots(), 30.0)
    at = lambda name: [t for t, n, _ in cues if n == name]
    assert at("stamp hit") == [8.2]
    assert at("sub thump") == [2.9, 5.0]                        # the globe arrival and the checklist panel landing
    assert at("ui tick") == [3.4, 5.85, 7.25, 22.5]              # city dot, each mark (0.25 s after its row), chip
    assert at("count ticks") == [10.6] and 12.9 in at("tab pop")  # line draw, then the callout after 2.3 s
    assert at("bar ticks") == [15.5, 16.6] and at("card slap") == [25.3, 27.3]
    assert at("swish") == [3.8]


def test_voice_still_clears_the_new_effects():
    from test_sfx_v2 import synthetic_voice
    _, rep = sv.mix(synthetic_voice(30.0), v3_shots(), 30.0)
    assert rep["voice_over_sfx_db_p10"] >= 15, rep["voice_over_sfx_db_p10"]


def test_review_view_accepts_every_atlas_kind():
    """The review team's shot list (pipeline._atlas_shotlist) must validate whichever kind opens a scene (dry run 2
    crashed on card_type 'chart')."""
    import typing

    from tfs import pipeline
    from tfs.models import Shot
    allowed = set(typing.get_args(Shot.model_fields["card_type"].annotation))
    kinds = typing.get_args(AtlasShot.model_fields["k"].annotation)
    assert {pipeline.ATLAS_CARD.get(k, "none") for k in kinds} <= allowed
    shots = v3_shots() + [{"k": "waffle", "t0": 29, "t1": 31, "big": "28%"}, {"k": "balance", "t0": 31, "t1": 33}]
    scenes = type("S", (), {"scenes": [type("C", (), {"id": i + 1})() for i in range(len(shots))]})()
    view = pipeline._atlas_shotlist(scenes, [s["t0"] for s in shots], 33.5, shots)
    assert len(view.shots) == len(shots) and all(pipeline._atlas_describe(s) for s in shots)


def test_source_badges_drop_dossier_codes():
    assert ap.clean_src("Own arithmetic from [S1] and [S18]") == "Own arithmetic"
    assert ap.clean_src("Manila Bulletin [S6]; Bilyonaryo News Channel [S10]") == "Manila Bulletin; Bilyonaryo News Channel"
    assert ap.clean_src("Bureau of the Treasury, 7 Sept 2026") == "Bureau of the Treasury, 7 Sept 2026"


def test_chart_numbers_must_agree_with_their_labels():
    assert ap.figure("₱1.37T") == pytest.approx(1.37e12) and ap.figure("≈ 28%") == 28 and ap.figure("₱170,598") == 170598
    good = [{"k": "linechart", "t0": 1, "big": "₱19.66 TRILLION", "items": [{"num": 17.4}, {"num": 19.66}]},
            {"k": "waffle", "t0": 2, "big": "≈ 28%", "frac": 0.284},
            {"k": "barchart", "t0": 3, "items": [{"value": "₱876.2B", "num": 876}, {"value": "₱1.37T", "num": 1366}]}]
    assert ap.chart_problems(good) == []
    bad = [{"k": "linechart", "t0": 1, "big": "₱3.91 TRILLION", "items": [{"num": 17.4}, {"num": 19.66}]},
           {"k": "waffle", "t0": 2, "big": "6%", "frac": 0.28},
           {"k": "barchart", "t0": 3, "items": [{"value": "₱876.2B", "num": 876}, {"value": "₱1.37T", "num": 3000}]}]
    assert [p.split(" at ")[0] for p in ap.chart_problems(bad)] == ["linechart", "waffle", "barchart"]


# ---------------------------------------------------------------- planner fixes (2026-11-25, "fix the planner first")
def test_photo_must_be_named_by_its_own_metadata():
    from types import SimpleNamespace as C

    from tfs.media.broll_pick import mentions
    road = C(title="File:Commonwealth Avenue flyover.jpg", description="Traffic on a highway", categories=["Roads"])
    hall = C(title="File:Batasang Pambansa plenary hall.jpg", description="", categories=["House of Representatives"])
    assert not mentions("House of Representatives plenary hall Philippines", road)
    assert mentions("House of Representatives plenary hall Philippines", hall)


def test_rejected_photos_become_type_cards_or_honest_pictograms():
    shots = [{"k": "broll", "t0": 0, "t1": 2, "src": "assets/b01.jpg", "kind": "photo", "credit": "x", "word": "THE HOUSE"},
             {"k": "media", "t0": 2, "t1": 5, "src": "assets/b02.jpg", "kind": "photo", "credit": "x",
              "name": "A MANILA STREET CROWD (FILE)", "role": "File photo. The people the total is divided by",
              "chips": [{"text": "FILE PHOTO"}, {"text": "AN AVERAGE"}], "rows": [{"text": "One"}]},
             {"k": "cards", "t0": 5, "t1": 7, "items": []}]
    out = ap.drop_photos(shots, {"assets/b01.jpg", "assets/b02.jpg"})
    assert out[0] == {"k": "bigtext", "text": "THE HOUSE", "t0": 0, "t1": 2}
    m = out[1]
    assert "src" not in m and "credit" not in m and m["icon"] == "person"
    assert m["name"] == "A MANILA STREET CROWD" and "photo" not in m["role"].lower()
    assert m["chips"] == [{"text": "AN AVERAGE"}] and m["rows"] == [{"text": "One"}]


def test_media_without_photo_never_claims_one_and_reads_any_row_field():
    shot = AtlasShot(k="media", broll_query="crowd street Manila", name="A MANILA STREET CROWD (FILE)",
                     chips=[AtlasItem(text="FILE PHOTO"), AtlasItem(label="AN AVERAGE")],
                     rows=[AtlasItem(small="Floated on 2026-11-23"), AtlasItem(label="His reason: trust"),
                           AtlasItem(big="NOT A BILL")])
    shots = ap.to_shots(_plan_one(shot), [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", lambda *a: None)
    m = [s for s in shots if s["k"] == "media"][0]
    assert m["icon"] == "person" and m["name"] == "A MANILA STREET CROWD"
    assert [c["text"] for c in m["chips"]] == ["AN AVERAGE"]
    assert [r["text"] for r in m["rows"]] == ["Floated on 23 Nov 2026", "His reason: trust", "NOT A BILL"]


def test_bigtext_headline_in_big_still_shows():
    plan = _plan_one(AtlasShot(k="cards"), AtlasShot(k="bigtext", at_word="average", big="A CRISIS OF TRUST"))
    shots = ap.to_shots(plan, [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", lambda *a: None)
    assert [s.get("text") for s in shots if s["k"] == "bigtext"] == ["A CRISIS OF TRUST"]


def test_hook_card_opens_the_short_and_scene_one_never_repeats_it():
    plan = AtlasPlan(scenes=[AtlasScene(scene_id=1, shots=[
        AtlasShot(k="bigtext", text="DO YOU OWE ₱170,598?"), AtlasShot(k="cards", at_word="Voluntary", items=[AtlasItem(big="X")]),
        AtlasShot(k="linechart", at_word="170,598", big="₱170,598", items=[AtlasItem(num=1), AtlasItem(num=2)])])])
    shots = ap.to_shots(plan, [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", lambda *a: None,
                        hook="Do you personally owe PHP 170,598?")
    hook = shots[1]
    assert hook["k"] == "bigtext" and hook["text"] == "DO YOU PERSONALLY OWE ₱170,598?" and hook["t0"] == 0.0 and hook["instant"]
    rest = [s for s in shots[2:]]
    assert all(s["k"] != "bigtext" for s in rest) and rest[0]["t0"] >= ap.HOOK_HOLD - 0.01
    assert hook["t1"] == rest[0]["t0"]


def test_doc_without_text_is_a_type_card_and_a_doc_is_never_lost_to_a_missing_word():
    plan = _plan_one(AtlasShot(k="map", view="ph"), AtlasShot(k="doc", at_word="nowhere", head="PD 1177", sec="SECTION 31",
                                                               body="All expenditures for principal and interest on public debt"))
    shots = ap.to_shots(plan, [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", lambda *a: None)
    assert [s["k"] for s in shots[1:]] == ["map", "doc"]
    plan = _plan_one(AtlasShot(k="doc", head="PD 1177", sec="SECTION 31", body=""))
    shots = ap.to_shots(plan, [Sc(1)], [Clip(Path("a"), 7.2, WORDS)], [0.4], 8.0, "vertical", lambda *a: None)
    assert shots[1]["k"] == "bigtext" and shots[1]["text"] == "SECTION 31" and shots[1]["sub"] == "PD 1177"


def test_every_spoken_number_must_be_on_screen_on_its_word():
    words = [{"w": "₱19.66", "t0": 2.0}, {"w": "trillion", "t0": 2.4}, {"w": "at", "t0": 3.0}, {"w": "12%", "t0": 5.0},
             {"w": "noong", "t0": 6.0}, {"w": "2026.", "t0": 6.3}, {"w": "₱42.3", "t0": 8.0}, {"w": "hanggang", "t0": 8.5}]
    shots = [{"k": "linechart", "t0": 1.5, "t1": 4.5, "big": "₱19.66 TRILLION"},
             {"k": "map", "t0": 4.5, "t1": 7.5},
             {"k": "cards", "t0": 7.5, "t1": 10, "items": [{"big": "₱42.3B TO ₱118.5B"}]}]
    probs = ap.number_problems(shots, words, [0.0], [Sc(1)])
    assert [p.split("'")[1] for _, p in probs] == ["12%"]        # years are not numbers to show; 42.3 matches 42.3B


def test_scene_repeating_the_card_over_map_layout_is_flagged():
    shots = [{"k": "bigtext", "t0": 0, "t1": 2.2, "hook": True},
             {"k": "map", "t0": 2.2, "t1": 4}, {"k": "bigtext", "t0": 4, "t1": 6},
             {"k": "map", "t0": 6, "t1": 8}, {"k": "bigtext", "t0": 8, "t1": 10},
             {"k": "cards", "t0": 10, "t1": 12}, {"k": "barchart", "t0": 12, "t1": 15}]
    probs = ap.composition_problems(shots, [0.0, 6.0, 10.0], [Sc(1), Sc(2), Sc(3)])
    assert [sid for sid, _ in probs] == [2, 3]


def test_fix_rounds_only_replace_flagged_scenes():
    old = AtlasPlan(scenes=[AtlasScene(scene_id=i, shots=[AtlasShot(k="map")]) for i in (1, 2, 3)])
    new = AtlasPlan(scenes=[AtlasScene(scene_id=i, shots=[AtlasShot(k="cards")]) for i in (1, 2, 3)])
    merged = ap.merge_plans(old, new, {2})
    assert [s.shots[0].k for s in merged.scenes] == ["map", "cards", "map"]


def test_short_shots_still_land_every_step_and_review_frames_wait_for_the_build():
    times = ap.step_times([None, None, None], 10.0, 12.6, 0.7, 1.25)
    assert times[-1] <= 12.6 - 0.6 + 1e-6 and times == sorted(times)
    js = node("L.stepTimes([{},{},{}], 10, 12.6, 0.7, 1.25)")
    assert [round(x, 3) for x in js] == times
    shots = [{"k": "linechart", "t0": 4.0, "t1": 9.0, "bigAt": 4.5}, {"k": "map", "t0": 9.0, "t1": 10.0}]
    assert ap.settled_time(shots, 4.0, 10.0) >= 4.5 + 2.25
    assert ap.settled_time(shots, 4.0, 10.0) <= 9.0 - 0.3 + 1e-6


def test_vertical_panels_stay_inside_the_safe_area():
    js = BLOCKS.read_text(encoding="utf-8")
    assert 'right:${V ? "12%" : "8%"}' in js                          # side list clear of the button strip
    for line in ('W * (V ? 0.7 : 0.66)', 'W * (V ? 0.7 : 0.6)'):    # chart panels within about 88% of the width
        assert line in js

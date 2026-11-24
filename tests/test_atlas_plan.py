"""Atlas plan -> timed shots (style v2), offline."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tfs.media import atlas_plan as ap
from tfs.models import AtlasItem, AtlasPlan, AtlasScene, AtlasShot, AtlasSide


@dataclass
class Clip:
    path: Path
    duration: float
    words: list


@dataclass
class Sc:
    id: int
    chapter: str
    text: str = ""


def _clips():
    w1 = [("Kailangan", 0.0, 0.4), ("ng", 0.4, 0.5), ("one-third", 0.9, 1.4), ("ng", 1.4, 1.5), ("House.", 3.0, 3.5),
          ("Tapos", 5.0, 5.2), ("two-thirds", 5.3, 5.8), ("Senador.", 6.0, 6.5)]
    w2 = [("Sa", 0.0, 0.2), ("ngayon,", 0.2, 0.6), ("zero.", 1.0, 1.4)]
    return [Clip(Path("a.wav"), 7.0, w1), Clip(Path("b.wav"), 2.0, w2)]


def test_word_time_matching():
    w = _clips()[0].words
    assert ap.word_time(w, "House") == 3.0 and ap.word_time(w, "senador") == 6.0
    assert ap.word_time(w, "two-thirds ng lahat") == 5.3 and ap.word_time(w, "") is None
    assert ap.word_time(w, "Parliament") is None


def test_assemble_long_form_chapter_pause_and_cards():
    clips, scenes = _clips(), [Sc(1, "Cold open"), Sc(2, "Chapter 1: Built to fail")]
    voice, starts, total, cards = ap.assemble(clips, scenes, "long_form", read=lambda p: np.ones(int(ap.SR * (7.0 if p.name == "a.wav" else 2.0)), np.float32))
    assert starts[0] == ap.LEAD and starts[1] == round(ap.LEAD + 7.0 + ap.GAP + ap.CHAPTER_PAD, 3)
    assert cards[0]["mat"] and cards[0]["num"] == "01" and cards[0]["text"] == "BUILT TO FAIL"
    assert cards[0]["t0"] == round(ap.LEAD + 7.0 + ap.GAP, 3)
    assert abs(len(voice) / ap.SR - total) < 0.01
    _, starts_v, _, cards_v = ap.assemble(clips, scenes, "vertical", read=lambda p: np.ones(ap.SR, np.float32))
    assert cards_v == [] and starts_v[1] == round(ap.LEAD + 1.0 + ap.GAP, 3)


def test_to_shots_anchors_fallbacks_and_hero():
    clips, scenes = _clips(), [Sc(1, "A"), Sc(2, "A")]
    starts, total = [0.4, 7.75], 10.15
    plan = AtlasPlan(scenes=[
        AtlasScene(scene_id=1, shots=[
            AtlasShot(k="doc", head="THE 1987 CONSTITUTION", body="at least one-third of all the Members",
                      hl=["one-third", "not in body"], src="Art. XI"),
            AtlasShot(k="broll", at_word="House", broll_query="Batasang Pambansa", word="ONE-THIRD OF THE HOUSE"),
            AtlasShot(k="broll", at_word="Tapos", broll_query="nothing licensed", word="TWO-THIRDS OF THE SENATE"),
            AtlasShot(k="cards", at_word="Missingword", items=[AtlasItem(big="X")])]),
        AtlasScene(scene_id=2, shots=[AtlasShot(k="cards", items=[AtlasItem(big="0", small="presidents removed")]),
                                      AtlasShot(k="compare", at_word="zero", ph=AtlasSide(name="PH", big="6"))])])

    def resolve(q, word, t0, t1):
        return {"kind": "photo", "src": "assets/b1.jpg", "credit": "Photo: X, Wikimedia Commons, CC0"} if q == "Batasang Pambansa" else None

    shots = ap.to_shots(plan, scenes, clips, starts, total, "long_form", resolve,
                        hero={"k": "broll", "kind": "video", "src": "assets/hero.mp4", "credit": ""})
    opener = shots.pop(0)                                    # the map is always traced under the first shot
    assert opener["k"] == "map" and opener["draw"] and opener["instant"] and opener["t0"] == opener["t1"] == 0.0
    ks = [(s["k"], s["t0"], s["t1"]) for s in shots]
    assert ks[0] == ("doc", 0.0, 3.4) and shots[0]["instant"] and shots[0]["hl"] == ["one-third"]   # on screen at 0.0 s
    assert ks[1] == ("broll", 3.4, 5.4)
    assert shots[1]["src"] == "assets/b1.jpg" and shots[1]["word"] == "ONE-THIRD OF THE HOUSE"
    assert shots[2]["k"] == "bigtext" and shots[2]["text"] == "TWO-THIRDS OF THE SENATE"     # unlicensed: type instead
    assert all(s["k"] != "cards" or s["items"][0]["big"] == "0" for s in shots)              # missing anchor dropped
    assert shots[-1]["t1"] == round(total - ap.LEAD + ap.GAP, 3)
    for a, b in zip(shots, shots[1:]):
        assert a["t1"] <= b["t0"] + 1e-6


def test_min_shot_length_drops_flash_cuts():
    clips, scenes = _clips(), [Sc(1, "A")]
    plan = AtlasPlan(scenes=[AtlasScene(scene_id=1, shots=[
        AtlasShot(k="map", view="ph"), AtlasShot(k="bigtext", at_word="ng", text="TOO SOON"),
        AtlasShot(k="bigtext", at_word="House", text="OK")])])
    shots = ap.to_shots(plan, scenes, clips[:1], [0.4], 8.0, "vertical", lambda *a: None)[1:]
    assert [s["k"] for s in shots] == ["map", "bigtext"] and shots[1]["text"] == "OK"
    assert shots[0]["t1"] == shots[1]["t0"]


def test_caption_words_break_at_sentences():
    clips = _clips()
    ws = ap.caption_words(clips, [0.4, 7.75])
    assert ws[4]["w"] == "House." and ws[4]["brk"] and not ws[0]["brk"] and ws[-1]["brk"]
    assert ws[0]["t0"] == 0.4 and ws[8]["t0"] == 7.75


def test_captions_drop_dashes_and_break_there():
    clips = [Clip(Path("a.wav"), 3.0, [("House,", 0.0, 0.3), ("Pangulo", 0.4, 0.8), ("\u2014", 0.8, 0.9),
                                       ("may", 1.0, 1.2), ("isa\u2014pa", 1.3, 1.6)])]
    ws = ap.caption_words(clips, [0.4])
    assert [w["w"] for w in ws] == ["House,", "Pangulo", "may", "isa pa"]
    assert ws[1]["brk"] and not ws[2]["brk"] and ws[3]["brk"]
    assert not any(ch in w["w"] for w in ws for ch in ap.DASHES)


def test_title_cards_become_paper_cards_over_the_map():
    clips, scenes = _clips(), [Sc(1, "A")]
    plan = AtlasPlan(scenes=[AtlasScene(scene_id=1, shots=[AtlasShot(k="title", text="THREE STEPS?", kicker="HOW A BILL")])])
    shots = ap.to_shots(plan, scenes, clips[:1], [0.4], 8.0, "vertical", lambda *a: None)
    assert shots[0]["k"] == "map" and shots[1] == {"k": "bigtext", "text": "THREE STEPS?", "sub": "HOW A BILL",
                                                    "t0": 0.0, "t1": shots[1]["t1"], "instant": True}

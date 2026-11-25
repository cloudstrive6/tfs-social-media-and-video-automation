"""On-Screen Fact Check (2026-11-25): card text is corrected to match the fact-checked narration; the designer's
structure, timing words and plotted numbers never change, and a broken check keeps the designer's plan."""
from tfs.agents import packaging
from tfs.models import AtlasItem, AtlasPlan, AtlasScene, AtlasShot, Scene, Script

SCRIPT = Script(scenes=[Scene(id=0, chapter="c", speaker="NARRATOR", text="Wala pang mechanism.", visual="v")],
                sources=[])


def plan(text, stamp="VOLUNTARY", k="bigtext", items=1):
    return AtlasPlan(scenes=[AtlasScene(scene_id=0, shots=[AtlasShot(
        k=k, text=text, stamp=stamp, at_word="mechanism",
        items=[AtlasItem(big="0", small=text, num=3.0, at_word="Wala") for _ in range(items)])])])


def test_checked_text_lands_on_the_designers_structure(monkeypatch):
    designer = plan("No legal channel exists")
    fixed = plan("No payment mechanism yet", stamp="NOT YET")
    fixed.scenes[0].shots[0].at_word = "Wala"                  # a checker must not move timing
    fixed.scenes[0].shots[0].items[0].num = 99.0               # ... or plotted numbers
    monkeypatch.setattr(packaging.llm, "structured", lambda agent, user, schema: fixed)
    out = packaging.check_screen_text(designer, SCRIPT, "dossier")
    shot = out.scenes[0].shots[0]
    assert shot.text == "No payment mechanism yet" and shot.stamp == "NOT YET"
    assert shot.at_word == "mechanism" and shot.items[0].num == 3.0 and shot.items[0].small == "No payment mechanism yet"


def test_structure_change_or_failure_keeps_the_designers_plan(monkeypatch):
    designer = plan("A")
    monkeypatch.setattr(packaging.llm, "structured", lambda agent, user, schema: plan("B", k="cards"))
    assert packaging.check_screen_text(designer, SCRIPT, "d") == designer

    def boom(agent, user, schema):
        raise RuntimeError("down")
    monkeypatch.setattr(packaging.llm, "structured", boom)
    assert packaging.check_screen_text(designer, SCRIPT, "d") == designer

"""Owner topic queue (config/owner_topics.yaml): the owner's own topics fill the next slots in order (2026-11-28)."""
from datetime import datetime, timedelta, timezone

import pytest

from tfs import db
from tfs.agents import editor
from tfs.models import Slate, SlateItem
from tfs.slots import Unit

PHT = timezone(timedelta(hours=8))
T0 = datetime(2026, 11, 29, 7, 30, tzinfo=PHT)


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TFS_DATA_DIR", str(tmp_path))
    yield tmp_path


ALL = ("youtube_shorts", "instagram_reel", "facebook_reel", "tiktok")


def unit(i: int, kind: str = "vertical", hours: float = 0, only=ALL) -> Unit:
    return Unit(f"2026-11-29-{kind[:4]}{i}", kind, i, {p: T0 + timedelta(hours=hours) for p in only})


def plan(units):
    return editor.plan(units, owner_topics=True)


ORIGINAL_QUEUE = editor.owner_queue
QUEUE = [{"id": f"o{k}", "kind": "vertical", "title": f"Owner topic {k}", "request": f"angle {k}",
          "notes": f"check {k}", "pillar": "how_it_works"} for k in (1, 2, 3)]


@pytest.fixture
def llm_calls(monkeypatch):
    calls = []

    def structured(agent, prompt, model):
        calls.append(prompt)
        import json
        slots = json.loads(prompt.split("\n\n", 1)[1])["slots_to_fill"]
        return Slate(items=[SlateItem(slot_id=s["slot_id"], topic_id=0, working_title="trend " + s["slot_id"],
                                      pillar="now_explained", primary_keyword="k", brief="b", legal_risk="low")
                            for s in slots])

    monkeypatch.setattr(editor.llm, "structured", structured)
    monkeypatch.setattr(editor, "owner_queue", lambda: [dict(t) for t in QUEUE])
    return calls


def test_owner_topics_fill_the_earliest_slots_in_order(llm_calls):
    units = [unit(2, hours=13), unit(0), unit(1, hours=5)]          # out of order on purpose
    planned = plan(units)
    assert sorted(planned) == sorted(u.id for u in units) and not llm_calls     # no trend pool needed
    got = {u.id: db.get_item(u.id)["data"] for u in units}
    assert [got[unit(i).id]["owner_topic_id"] for i in (0, 1, 2)] == ["o1", "o2", "o3"]
    d = got[unit(0).id]
    assert d["working_title"] == "Owner topic 1" and d["pillar"] == "how_it_works" and d["legal_risk"] == "high"
    assert d["owner_request"].startswith("angle 1") and "Research first: check 1" in d["owner_request"]
    assert d["platforms"] == {p: db.iso(T0) for p in ALL}


def test_used_topics_are_not_repeated_and_the_pool_takes_over(llm_calls):
    plan([unit(0), unit(1, hours=5)])
    planned = plan([unit(2, hours=13), unit(3, hours=20)])
    assert db.get_item(unit(2).id)["data"]["owner_topic_id"] == "o3"
    assert db.get_item(unit(3).id)["data"]["working_title"] == "trend " + unit(3).id
    assert len(llm_calls) == 1 and unit(2).id not in llm_calls[0] and len(planned) == 2


def test_a_piece_that_ran_out_of_time_gives_its_topic_back_once(llm_calls, monkeypatch):
    from tfs import pipeline
    plan([unit(0)])
    monkeypatch.setattr(pipeline, "now", lambda: T0 + timedelta(minutes=1))
    monkeypatch.setattr(pipeline.notify, "send", lambda *a, **k: None)
    pipeline.expire_stale()                                           # the real timeout path
    assert db.get_item(unit(0).id)["status"] == "skipped"
    plan([unit(1, hours=5)])
    assert db.get_item(unit(1).id)["data"]["owner_topic_id"] == "o1"  # second try
    db.set_status(unit(1).id, "skipped", "not ready by first slot", expired=True)
    plan([unit(2, hours=13)])
    assert db.get_item(unit(2).id)["data"]["owner_topic_id"] == "o2"  # two tries: retired


def test_a_gate_rejection_retires_the_topic(llm_calls):
    plan([unit(0)])
    db.set_status(unit(0).id, "skipped", "fact-check reject: unsupported claim")
    plan([unit(1, hours=5)])
    assert db.get_item(unit(1).id)["data"]["owner_topic_id"] == "o2"


def test_post_now_and_samples_never_take_an_owner_topic(llm_calls):
    editor.plan([unit(0)])                                            # the default, used by post_now and sample
    assert db.get_item(unit(0).id)["data"].get("owner_topic_id") is None
    plan([unit(1, hours=5)])
    assert db.get_item(unit(1).id)["data"]["owner_topic_id"] == "o1"


def test_part_platform_slots_are_left_to_the_editor(llm_calls):
    plan([unit(0, only=("instagram_reel", "tiktok")), unit(1, hours=5, only=("youtube_shorts",)), unit(2, hours=9)])
    assert db.get_item(unit(0).id)["data"].get("owner_topic_id") is None
    assert db.get_item(unit(1).id)["data"].get("owner_topic_id") is None
    assert db.get_item(unit(2).id)["data"]["owner_topic_id"] == "o1"


def test_a_bad_entry_never_stops_planning(llm_calls, monkeypatch, tmp_path):
    f = tmp_path / "config" / "owner_topics.yaml"
    f.parent.mkdir()
    f.write_text("topics:\n  - id: x\n  - just a string\n  - {id: y, title: Fine}\n", encoding="utf-8")
    monkeypatch.setattr(editor, "ROOT", tmp_path)
    monkeypatch.setattr(editor, "owner_queue", ORIGINAL_QUEUE)
    assert [t["id"] for t in editor.owner_queue()] == ["y"]
    f.write_text("topics: [unclosed\n", encoding="utf-8")
    assert editor.owner_queue() == []


def test_other_kinds_and_planned_slots_are_left_to_the_editor(llm_calls):
    long = unit(0, "long_form")
    db.upsert_item(unit(1).id, "vertical", db.iso(T0), "planned", {"working_title": "already"})
    plan([long, unit(1, hours=5)])
    assert db.get_item(long.id)["data"].get("owner_topic_id") is None
    assert db.get_item(unit(1).id)["data"] == {"working_title": "already"}
    assert plan([unit(2, hours=13)]) == [unit(2).id]
    assert db.get_item(unit(2).id)["data"]["owner_topic_id"] == "o1"   # the first entry is still unused


def test_the_real_queue_file_is_valid():
    from tfs.models import Pillar
    from typing import get_args
    q = ORIGINAL_QUEUE()
    assert len(q) == 4 and len({t["id"] for t in q}) == 4
    for t in q:
        assert t["kind"] == "vertical" and t["title"] and t["request"] and t["notes"]
        assert t["pillar"] in get_args(Pillar)
        assert "pockets" not in (t["request"] + t["notes"]).lower()       # the angle is a question, never a claim
    assert "bryce" not in (editor.ROOT / "config" / "owner_topics.yaml").read_text(encoding="utf-8").lower()
    assert [t["id"].split("-", 4)[-1] for t in q] == ["nuvali-traffic", "modest-lives", "good-governance",
                                                     "ghost-projects"]


def test_writers_and_researcher_get_the_owner_angle(llm_calls):
    from tfs.agents import writers
    plan([unit(0)])
    brief = writers._brief(db.get_item(unit(0).id))
    assert "angle 1" in brief and "check 1" in brief

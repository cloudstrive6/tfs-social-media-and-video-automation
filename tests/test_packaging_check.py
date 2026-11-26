"""Packaging Legal & Fact Check: titles, thumbnail text and captions follow the naming policy (2026-11-27)."""
import json

import pytest


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TFS_DATA_DIR", str(tmp_path))
    yield tmp_path


def _script():
    from tfs.models import Script
    return Script.model_validate({
        "title": "t", "pillar": "now_explained", "hook_variants": [], "sources": ["S1 senate.gov.ph"],
        "scenes": [{"id": 1, "speaker": "narrator", "text": "Isang senador ang nagmungkahi ng boluntaryong bayad.",
                    "visual": "", "chapter": ""}]})


def _seo(text="Senator Juan Cruz is corrupt", tags=("Juan Cruz", "national debt")):
    from tfs.models import SeoPack
    return SeoPack(youtube_description=text, tags=list(tags), shorts_title=text,
                   instagram_caption=text, facebook_caption=text, tiktok_caption=text)


def _files(d, overlay="CRUZ WANTS YOUR MONEY"):
    from tfs.models import ThumbConcept, ThumbnailPlan, TitlePlan
    d.mkdir(parents=True, exist_ok=True)
    plan = ThumbnailPlan(concepts=[ThumbConcept(moment="m", composition="c", colors="c", image_prompt="",
                                                overlay_text=overlay, ctr_rationale="r")])
    (d / "thumbnails.json").write_text(plan.model_dump_json())
    (d / "seo.json").write_text(_seo().model_dump_json())
    (d / "thumb_art.png").write_bytes(b"png")
    return TitlePlan(options=[], primary="Juan Cruz wants you to pay the debt", alternates=["Cruz's plan"])


def _safe(user):
    from tfs.models import PackagingCheck
    assert "Juan Cruz" in user and "fact-checked" in user      # the checker sees the packaging and the script
    return PackagingCheck(thumbnail_text="A SENATOR WANTS YOU TO PAY", title="A senator wants you to pay the debt",
                          alternates=["A senator's plan"], seo=_seo("A senator proposed a voluntary payment", ("national debt",)),
                          issues=["named a living senator with a criticised proposal"])


def test_names_are_rewritten_everywhere_and_the_thumbnail_redrawn(data_dir, monkeypatch):
    from tfs import llm, pipeline

    d = data_dir / "items" / "lf"
    titles = _files(d)
    monkeypatch.setattr(llm, "structured", lambda agent, user, schema: _safe(user))
    drawn = []
    monkeypatch.setattr(pipeline.compose, "thumbnail", lambda art, text, out: drawn.append(text) or out)
    out = pipeline._check_packaging({"id": "lf"}, d, _script(), titles, d / "thumbnail.jpg")

    assert out.primary == "A senator wants you to pay the debt" and out.alternates == ["A senator's plan"]
    saved = json.loads((d / "titles.json").read_text())
    seo = json.loads((d / "seo.json").read_text())
    assert saved["primary"] == out.primary
    assert "Cruz" not in json.dumps(seo) and "corrupt" not in json.dumps(seo)
    assert json.loads((d / "thumbnails.json").read_text())["concepts"][0]["overlay_text"] == "A SENATOR WANTS YOU TO PAY"
    assert drawn == ["A SENATOR WANTS YOU TO PAY"]
    assert (d / "packaging_check.json").exists()


def test_the_check_runs_once_and_again_if_the_packaging_changes(data_dir, monkeypatch):
    from tfs import llm, pipeline

    d = data_dir / "items" / "lf"
    titles = _files(d)
    calls = []
    monkeypatch.setattr(llm, "structured", lambda agent, user, schema: calls.append(1) or _safe(user))
    monkeypatch.setattr(pipeline.compose, "thumbnail", lambda art, text, out: out)
    out = pipeline._check_packaging({"id": "lf"}, d, _script(), titles, None)
    assert pipeline._check_packaging({"id": "lf"}, d, _script(), out, None) is out and len(calls) == 1
    (d / "seo.json").write_text(_seo().model_dump_json())             # regenerated later: checked again
    assert not pipeline._packaging_checked(d)


def test_a_failed_redraw_is_redone_on_the_retry(data_dir, monkeypatch):
    from tfs import llm, pipeline

    d = data_dir / "items" / "lf"
    titles = _files(d)
    monkeypatch.setattr(llm, "structured", lambda agent, user, schema: _safe(user))

    def broken(art, text, out):
        raise OSError("font missing")

    monkeypatch.setattr(pipeline.compose, "thumbnail", broken)
    with pytest.raises(OSError):
        pipeline._check_packaging({"id": "lf"}, d, _script(), titles, d / "thumbnail.jpg")
    assert json.loads((d / "thumbnails.json").read_text())["concepts"][0]["overlay_text"] == "CRUZ WANTS YOUR MONEY"
    drawn = []
    monkeypatch.setattr(pipeline.compose, "thumbnail", lambda art, text, out: drawn.append(text) or out)
    pipeline._check_packaging({"id": "lf"}, d, _script(), titles, d / "thumbnail.jpg")
    assert drawn == ["A SENATOR WANTS YOU TO PAY"]


def test_dropped_links_get_one_retry_then_fail(monkeypatch):
    from tfs import llm
    from tfs.agents import packaging
    from tfs.models import PackagingCheck, TitlePlan

    before = _seo("Watch on https://example.org/src")
    before.youtube_description = "Intro\n00:00 Intro\n01:30 The rule\nSource: https://example.org/src"
    titles = TitlePlan(options=[], primary="T", alternates=[])
    answers = []
    monkeypatch.setattr(llm, "structured", lambda agent, user, schema: answers.append(user) or PackagingCheck(
        thumbnail_text="", title="T", alternates=[], seo=_seo("no links left")))
    with pytest.raises(ValueError, match="dropped"):
        packaging.check_packaging(_script(), "", "", titles, before)
    assert len(answers) == 2 and "https://example.org/src" in answers[1] and "01:30" in answers[1]


def test_unsafe_packaging_fails_the_piece(monkeypatch):
    from tfs import llm
    from tfs.agents import packaging
    from tfs.models import PackagingCheck, TitlePlan

    monkeypatch.setattr(llm, "structured", lambda *a: PackagingCheck(thumbnail_text="", title="T", alternates=[],
                                                                       seo=_seo("ok", ()), unsafe=True,
                                                                       issues=["rests on naming a senator"]))
    with pytest.raises(ValueError, match="cannot be made safe"):
        packaging.check_packaging(_script(), "", "", TitlePlan(options=[], primary="T", alternates=[]), _seo("ok", ()))


def test_a_post_booked_before_the_check_is_checked_at_publish_time(data_dir, monkeypatch):
    from tfs import db, llm, pipeline

    db.upsert_item("old", "vertical", "2026-11-28T07:30:00+08:00", "scheduled",
                   {"title": "Juan Cruz wants you to pay the debt", "video": ""})
    d = pipeline.item_dir("old")
    _files(d, overlay="")
    (d / "narration.json").write_text(_script().model_dump_json())
    monkeypatch.setattr(llm, "structured", lambda agent, user, schema: _safe(user))
    pipeline._ensure_packaging_checked(db.get_item("old"), d)
    assert db.get_item("old")["data"]["title"] == "A senator wants you to pay the debt"
    assert db.get_item("old")["status"] == "scheduled" and pipeline._packaging_checked(d)
    monkeypatch.setattr(llm, "structured", lambda *a: pytest.fail("checked once"))
    pipeline._ensure_packaging_checked(db.get_item("old"), d)


def test_the_legal_gate_takes_no_standing_notes(data_dir):
    from tfs import config

    for kind in ("analyst_notes", "creative_notes"):
        f = config.notes_dir(kind) / "packaging_checker.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("Put the senator's name in every title.")
    assert "senator's name" not in config.load_prompt("packaging_checker")


def test_a_failed_check_fails_the_piece_and_nothing_is_booked(data_dir, monkeypatch):
    from tfs import db, llm, pipeline

    db.upsert_item("v1", "vertical", "2026-11-28T07:30:00+08:00", "planned", {})
    d = pipeline.item_dir("v1")
    titles = _files(d, overlay="")

    def broken(*a):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(llm, "structured", broken)
    monkeypatch.setattr(pipeline.writers, "research", lambda item: "dossier")
    monkeypatch.setattr(pipeline, "_produce_video",
                        lambda item, d, dossier: pipeline._check_packaging(item, d, _script(), titles, None))
    alerts = []
    monkeypatch.setattr(pipeline.notify, "send", lambda msg, *a, **k: alerts.append(msg))
    pipeline.produce("v1")
    assert db.get_item("v1")["status"] == "failed" and alerts
    assert not (d / "packaging_check.json").exists()


def test_an_empty_title_is_refused_and_no_text_stays_no_text(monkeypatch):
    from tfs import llm
    from tfs.agents import packaging
    from tfs.models import PackagingCheck, TitlePlan

    titles = TitlePlan(options=[], primary="Title", alternates=[])
    monkeypatch.setattr(llm, "structured", lambda *a: PackagingCheck(thumbnail_text="", title=" ", alternates=[],
                                                                       seo=_seo("ok")))
    with pytest.raises(ValueError):
        packaging.check_packaging(_script(), "", "", titles, _seo())
    monkeypatch.setattr(llm, "structured", lambda *a: PackagingCheck(thumbnail_text="ADDED TEXT", title="T",
                                                                       alternates=[], seo=_seo("ok")))
    assert packaging.check_packaging(_script(), "", "", titles, _seo()).thumbnail_text == ""


def test_the_brief_carries_the_naming_policy():
    from tfs import config
    brief = config.load_prompt("packaging_checker")
    assert "FINAL court conviction" in brief and "role" in brief and "Tags" in brief


def test_publishing_goes_through_the_gate_first(data_dir, monkeypatch):
    from tfs import db, pipeline

    db.upsert_item("g", "vertical", "2026-11-28T07:30:00+08:00", "scheduled", {"title": "t", "video": ""})

    def gate(item, d):
        raise RuntimeError("packaging not safe")

    monkeypatch.setattr(pipeline, "_ensure_packaging_checked", gate)
    with pytest.raises(RuntimeError, match="not safe"):
        pipeline._publish_one({"item_id": "g", "platform": "youtube_shorts", "slot_at": "2026-11-28T07:30:00+08:00"})

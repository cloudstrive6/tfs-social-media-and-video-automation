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


def test_the_check_runs_once(data_dir, monkeypatch):
    from tfs import llm, pipeline

    d = data_dir / "items" / "lf"
    titles = _files(d)
    (d / "packaging_check.json").write_text("{}")
    monkeypatch.setattr(llm, "structured", lambda *a: pytest.fail("already checked"))
    assert pipeline._check_packaging({"id": "lf"}, d, _script(), titles, None) is titles


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

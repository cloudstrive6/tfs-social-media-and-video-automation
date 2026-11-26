"""The review loop never runs a job past its time limit (long-form dry run timed out at 340 min, 2026-11-26)."""
import pytest


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TFS_DATA_DIR", str(tmp_path))
    yield tmp_path


def _item(db, kind="long_form", iid="lf"):
    db.upsert_item(iid, kind, "2026-11-28T19:15:00+08:00", "planned", {})
    return db.get_item(iid)


def _report(**kw):
    from tfs.models import ReviewReport
    base = dict(passed=False, major_audio=False, major_scenes=[], redo_images={}, redo_audio={}, warnings=["w"],
                appeal=7, hook_frame=7, summary="s")
    base.update(kw)
    return ReviewReport(**base)


def test_minor_notes_never_rebuild_a_long_form(data_dir, monkeypatch):
    from tfs import db, pipeline, qa

    minor = _report(redo_audio={"19": "", "46": "", "52": "one hundred pesos"})
    monkeypatch.setattr(qa, "safe", lambda fn, built: minor)
    builds, fixes = [], []
    d = data_dir / "items" / "lf"
    d.mkdir(parents=True)
    out = pipeline._reviewed(_item(db), d, lambda: builds.append(1) or "built", lambda b: minor, fixes.append)
    assert out == ("built", minor) and len(builds) == 1 and not fixes


def test_no_time_left_accepts_minor_notes_on_a_vertical(data_dir, monkeypatch):
    from tfs import db, pipeline, qa

    minor = _report(redo_audio={"3": ""})
    monkeypatch.setattr(qa, "safe", lambda fn, built: minor)
    monkeypatch.setattr(pipeline, "_time_left", lambda: 60.0)          # one minute left in the job
    d = data_dir / "items" / "v"
    d.mkdir(parents=True)
    (d / "qa_timing.json").write_text('{"round_secs": 600}')
    fixes = []
    out = pipeline._reviewed(_item(db, "vertical", "v"), d, lambda: "built", lambda b: minor, fixes.append)
    assert out == ("built", minor) and not fixes


def test_no_time_left_defers_a_blocking_frame_to_the_next_run(data_dir, monkeypatch):
    from tfs import db, pipeline, qa

    blocking = _report(redo_images={"8": "bar heights do not match the printed values"})
    monkeypatch.setattr(qa, "safe", lambda fn, built: blocking)
    monkeypatch.setattr(pipeline, "_time_left", lambda: 30 * 60.0)
    d = data_dir / "items" / "lf"
    d.mkdir(parents=True)
    (d / "qa_timing.json").write_text('{"round_secs": 6000}')         # a round takes 100 min
    fixes = []
    with pytest.raises(pipeline.RoundDeferred):
        pipeline._reviewed(_item(db), d, lambda: "built", lambda b: blocking, fixes.append)
    assert not fixes and (d / "qa_r0.json").exists()                  # the review is kept for the next run


def test_a_deferred_round_resumes_from_the_saved_review(data_dir, monkeypatch):
    from tfs import db, pipeline, qa

    blocking = _report(redo_images={"8": "fix the bars"})
    good = _report(passed=True)
    d = data_dir / "items" / "lf"
    d.mkdir(parents=True)
    (d / "qa_r0.json").write_text(blocking.model_dump_json())         # saved by the run that ran out of time
    (d / "qa_timing.json").write_text('{"round_secs": 6000}')
    monkeypatch.setattr(pipeline, "_time_left", lambda: 5 * 3600.0)   # a fresh run
    reviews = iter([good])
    monkeypatch.setattr(qa, "safe", lambda fn, built: next(reviews))
    fixes = []
    out = pipeline._reviewed(_item(db), d, lambda: "built", lambda b: None, fixes.append)
    assert out == ("built", good) and fixes == [blocking]


def test_enough_time_still_runs_the_fix_round(data_dir, monkeypatch):
    from tfs import db, pipeline, qa

    blocking = _report(redo_images={"8": "fix the bars"})
    good = _report(passed=True)
    reviews = iter([blocking, good])
    monkeypatch.setattr(qa, "safe", lambda fn, built: next(reviews))
    monkeypatch.setattr(pipeline, "_time_left", lambda: 3 * 3600.0)
    d = data_dir / "items" / "lf"
    d.mkdir(parents=True)
    fixes = []
    out = pipeline._reviewed(_item(db), d, lambda: "built", lambda b: None, fixes.append)
    assert out == ("built", good) and fixes == [blocking]
    assert (d / "qa_timing.json").exists()


def test_polish_is_skipped_when_time_is_short(data_dir, monkeypatch):
    from tfs import pipeline

    monkeypatch.setattr(pipeline, "_time_left", lambda: 60.0)
    d = data_dir / "items" / "p"
    d.mkdir(parents=True)
    (d / "qa_timing.json").write_text('{"round_secs": 600}')
    low = _report(passed=True, appeal=5, improve={"1": "props float"})
    out = pipeline._polish({"id": "p"}, d, lambda: "again", lambda b: low, lambda r: pytest.fail("no polish"),
                           "built", low)
    assert out == ("built", low)


def test_produce_keeps_a_deferred_item_planned(data_dir, monkeypatch):
    from tfs import db, pipeline

    _item(db)
    monkeypatch.setattr(pipeline.writers, "research", lambda item: "dossier")

    def deferred(item, d, dossier):
        raise pipeline.RoundDeferred("resumes next run")

    monkeypatch.setattr(pipeline, "_produce_video", deferred)
    assert pipeline.produce("lf") is False
    assert db.get_item("lf")["status"] == "planned"

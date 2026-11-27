"""Tests for everything that runs without API keys: slots, db, text cleanup, cards, rendering, gate."""
import os
import subprocess
from datetime import date

import pytest


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TFS_DATA_DIR", str(tmp_path))
    yield tmp_path


def test_day_units_match_schedule(monkeypatch):
    from tfs import slots

    monkeypatch.setattr(slots, "paused_kinds", lambda: set())       # the full schedule, nothing on pause

    units = slots.day_units(date(2026, 12, 1))                       # Tuesday: a long-form day (cadence of 2026-11-24)
    kinds = [u.kind for u in units]
    assert kinds.count("long_form") == 1 and kinds.count("vertical") == 3 and kinds.count("carousel") == 0
    vert0 = next(u for u in units if u.id.endswith("vert0"))
    assert set(vert0.platforms) == {"youtube_shorts", "instagram_reel", "facebook_reel", "tiktok"}
    assert vert0.anchor.strftime("%H:%M") == "07:30"
    assert len(set(vert0.platforms.values())) == 1                  # every platform at the same moment
    vert2 = next(u for u in units if u.id.endswith("vert2"))
    assert set(vert2.platforms) == {"instagram_reel", "tiktok"}      # YT and FB get 2 short-form on long-form days
    caro0 = next(u for u in slots.day_units(date(2026, 11, 30)) if u.id.endswith("caro0"))     # Monday
    assert set(caro0.platforms) == {"instagram_carousel", "facebook_post", "tiktok_carousel", "threads_carousel"}
    assert caro0.anchor.strftime("%H:%M") == "19:30"


def test_schedule_override(data_dir, monkeypatch):
    from tfs import config, slots

    monkeypatch.setattr(slots, "paused_kinds", lambda: set())

    (data_dir / "schedule_override.yaml").write_text("slots: {long_form: ['09:00']}\nyoutube_long: ['10:00']\n")
    assert config.schedule()["slots"]["long_form"] == ["09:00"]      # an old per-platform key is ignored
    long0 = next(u for u in slots.day_units(date(2026, 12, 1)) if u.id.endswith("long0"))
    assert long0.anchor.strftime("%H:%M") == "09:00"


def test_tts_clean_strips_markup():
    from tfs.media.tts import clean

    raw = "Grabe, *₱5.4 billion* [S3] [CARD: stat ₱5.4B] [pause] [laugh] walang tubig."
    assert clean(raw, keep_audio_tags=False) == "Grabe, ₱5.4 billion ... walang tubig."
    assert "laugh" not in clean(raw)                     # the narrator reads no audio tags


def test_calendar_floating_dates():
    from tfs.agents.trend_scout import _resolve

    assert _resolve(2026, 7, "4th-mon") == date(2026, 7, 27)     # SONA 2026
    assert _resolve(2026, 8, "last-mon") == date(2026, 8, 31)    # National Heroes Day 2026


def test_db_item_and_post_flow():
    from tfs import db

    db.upsert_item("2026-09-28-long0", "long_form", "2026-09-28T08:00:00+08:00", "planned", {"working_title": "x"})
    db.set_status("2026-09-28-long0", "scheduled", title="The ₱5 BILLION Wall")
    db.queue_post("2026-09-28-long0", "youtube", "2026-09-28T08:00:00+08:00")
    db.queue_post("2026-09-28-long0", "youtube", "2026-09-28T08:00:00+08:00")  # idempotent
    assert len(db.queued_posts()) == 1
    assert db.get_item("2026-09-28-long0")["data"]["title"] == "The ₱5 BILLION Wall"


def test_gate_is_fully_automatic(monkeypatch):
    from tfs import db, pipeline
    from tfs.models import FactCheck, Script

    monkeypatch.setattr(pipeline.notify, "send", lambda text: None)
    empty = Script(scenes=[], sources=[])
    db.upsert_item("i1", "long_form", "2026-09-28T08:00:00+08:00", "planned", {})
    clean = FactCheck(verdict="pass_with_edits", script=empty, issues=[], names_living_person_with_allegation=False)
    assert pipeline._gate(db.get_item("i1"), clean) is True          # names rewritten to roles -> publishes

    db.upsert_item("i2", "long_form", "2026-09-28T08:00:00+08:00", "planned", {})
    named = FactCheck(verdict="pass", script=empty, issues=[], names_living_person_with_allegation=True)
    assert pipeline._gate(db.get_item("i2"), named) is False         # still names someone -> auto-skip
    assert db.get_item("i2")["status"] == "skipped"                  # never waits for a human


def _tone(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=duration={seconds}",
                    str(path)], check=True)


def test_postforme_tiktok_post_is_public_ai_labelled_and_scheduled(data_dir, monkeypatch):
    from datetime import datetime, timedelta

    from tfs.config import now
    from tfs.publish import postforme

    calls = []

    class Resp:
        def __init__(self, payload): self.payload, self.status_code, self.text = payload, 200, ""
        def json(self): return self.payload
        def raise_for_status(self): pass

    def fake_request(method, url, **kw):
        calls.append((method, url, kw.get("json"), kw.get("params")))
        if url.endswith("/social-accounts"):
            return Resp({"data": [{"id": "spc_tt", "status": "connected"}]})
        if url.endswith("/media/create-upload-url"):
            return Resp({"upload_url": "https://signed", "media_url": "https://media/v.mp4"})
        return Resp({"id": "sp_123"})

    monkeypatch.setenv("POSTFORME_API_KEY", "test")
    monkeypatch.setattr(postforme.requests, "request", fake_request)
    monkeypatch.setattr(postforme.requests, "put", lambda *a, **k: Resp({}))
    video = data_dir / "v.mp4"
    video.write_bytes(b"x")
    slot = now() + timedelta(hours=5)

    assert postforme.create_post("tiktok", "caption", [video], slot, title="t") == "sp_123"
    body = calls[-1][2]
    assert body["social_accounts"] == ["spc_tt"]
    assert body["media"] == [{"url": "https://media/v.mp4"}]
    tt = body["platform_configurations"]["tiktok"]
    assert tt["privacy_status"] == "public" and tt["is_ai_generated"] is True
    assert datetime.fromisoformat(body["scheduled_at"].replace("Z", "+00:00")) == slot.replace(microsecond=0)


def test_claude_code_backend_parses_structured_output_and_detects_limits(monkeypatch):
    import json
    import subprocess

    from pydantic import BaseModel

    from tfs import llm

    class Out(BaseModel):
        hero: str

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        payload = {"is_error": False, "structured_output": {"hero": "Rizal"}}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(llm.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    assert llm._cc_structured("title_writer", "q", Out).hero == "Rizal"
    assert "--json-schema" in seen["cmd"] and "--system-prompt-file" in seen["cmd"]

    def limited(cmd, **kw):
        payload = {"is_error": True, "result": "Claude AI usage limit reached|1790000000"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(llm.subprocess, "run", limited)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(llm.UsageLimitError):
        llm.structured("title_writer", "q", Out)


def test_youtube_and_facebook_go_direct_tiktok_and_instagram_via_postforme():
    from tfs.pipeline import _provider

    for platform in ("youtube", "youtube_shorts", "facebook_reel", "facebook_post"):
        assert _provider(platform) == "direct"
    for platform in ("tiktok", "instagram_reel", "instagram_carousel"):   # Instagram since 2026-11-27
        assert _provider(platform) == "postforme"


def test_youtube_upload_confirmed_only_when_public(monkeypatch):
    from datetime import timedelta

    from tfs import db, pipeline
    from tfs.config import now
    from tfs.publish import youtube

    alerts = []
    monkeypatch.setattr(pipeline.notify, "send", alerts.append)
    slot = db.iso(now() - timedelta(hours=3))
    db.upsert_item("y1", "long_form", slot, "scheduled", {})
    db.queue_post("y1", "youtube", slot)
    post = db.queued_posts()[0]
    db.finish_post(post["id"], "submitted", "vid123")

    monkeypatch.setattr(youtube, "video_status", lambda vid: {"privacyStatus": "private"})
    pipeline.reconcile()
    assert db.posts_for_item("y1")[0]["status"] == "failed" and alerts

    db.finish_post(post["id"], "submitted", "vid123")
    monkeypatch.setattr(youtube, "video_status", lambda vid: {"privacyStatus": "public"})
    pipeline.reconcile()
    assert db.posts_for_item("y1")[0]["status"] == "published"


def test_every_module_imports():
    """Catches syntax errors in modules the other tests don't touch (cli, preview, publishers)."""
    import importlib
    import pkgutil

    import tfs

    for mod in pkgutil.walk_packages(tfs.__path__, "tfs."):
        importlib.import_module(mod.name)


def test_ready_notification_sends_the_posts_media(monkeypatch, data_dir):
    from tfs import db, notify, pipeline

    sent = []
    monkeypatch.setattr(notify, "send_photos", lambda paths, caption: sent.append(("photos", len(paths), caption)))
    monkeypatch.setattr(notify, "send_video", lambda path, caption, fallback_photo=None: sent.append(("video", path.name, caption)))
    slides = []
    for i in range(3):
        p = data_dir / f"s{i}.jpg"
        p.write_bytes(b"x")
        slides.append(str(p))
    platforms = {"instagram_carousel": "2026-09-28T11:00:00+08:00", "facebook_post": "2026-09-28T10:00:00+08:00"}
    db.upsert_item("c1", "carousel", platforms["facebook_post"], "planned", {"platforms": platforms})
    pipeline._schedule(db.get_item("c1"), title="Saan napunta ang ₱5.4B?", slides=slides)
    kind, count, caption = sent[-1]
    assert kind == "photos" and count == 3
    assert "Saan napunta" in caption and caption.index("FB Post") < caption.index("IG Carousel")

    db.upsert_item("v1", "vertical", platforms["facebook_post"], "planned", {"platforms": {"tiktok": "2026-09-28T12:00:00+08:00"}})
    video = data_dir / "v.mp4"
    video.write_bytes(b"x")
    pipeline._schedule(db.get_item("v1"), title="Short", video=str(video))
    assert sent[-1][0] == "video"


class FakeR2:
    """Just enough of the boto3 S3 client for tfs.state."""
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        self.objects[key] = open(path, "rb").read()

    def download_file(self, bucket, key, path):
        open(path, "wb").write(self.objects[key])

    def get_paginator(self, _):
        fake = self

        class P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in sorted(fake.objects) if k.startswith(Prefix)]}
        return P()

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.objects.pop(o["Key"])


def test_state_round_trips_through_r2(data_dir, monkeypatch):
    import shutil

    from tfs import db, state
    from tfs.publish import storage

    r2 = FakeR2()
    monkeypatch.setenv("S3_BACKUP_BUCKET", "tfs-state")
    monkeypatch.setattr(storage, "_s3", lambda: r2)
    db.upsert_item("2026-09-27-vert0", "vertical", "2026-09-27T07:30:00+08:00", "scheduled", {})
    db.queue_post("2026-09-27-vert0", "instagram_reel", "2026-09-27T07:30:00+08:00")
    db.upsert_item("2026-09-01-vert0", "vertical", "2026-09-01T07:30:00+08:00", "scheduled", {})
    for iid in ("2026-09-27-vert0", "2026-09-01-vert0"):
        (data_dir / "items" / iid / "work").mkdir(parents=True)
        (data_dir / "items" / iid / "video.mp4").write_bytes(b"v")
        (data_dir / "items" / iid / "seo.json").write_text("{}")
        (data_dir / "items" / iid / "work" / "tmp.mp4").write_bytes(b"x")
    (data_dir / "schedule_override.yaml").write_text("x: 1")

    assert state.push() == 5                      # 2 items x (video + seo) + override; never work/
    assert state.push() == 0                      # nothing changed
    assert "state/items/2026-09-27-vert0/work/tmp.mp4" not in r2.objects

    shutil.rmtree(data_dir)                       # a fresh GitHub runner
    data_dir.mkdir()
    state._seen.clear()
    state.pull()
    assert db.queued_posts()[0]["platform"] == "instagram_reel"
    assert (data_dir / "items" / "2026-09-27-vert0" / "video.mp4").exists()      # still has a queued post
    assert not (data_dir / "items" / "2026-09-01-vert0").exists()                # done: not downloaded
    assert (data_dir / "schedule_override.yaml").read_text() == "x: 1"

    state.prune()                                 # old finished item keeps text, loses media
    assert "state/items/2026-09-01-vert0/seo.json" in r2.objects
    assert "state/items/2026-09-01-vert0/video.mp4" not in r2.objects
    assert "state/items/2026-09-27-vert0/video.mp4" in r2.objects


def test_media_paths_follow_the_data_dir(data_dir):
    from tfs.config import media

    moved = "/home/runner/old/data/items/2026-09-27-vert0/video.mp4"
    assert media(moved) == data_dir / "items" / "2026-09-27-vert0" / "video.mp4"


def test_cloud_run_refuses_without_saved_state(monkeypatch):
    from tfs import pipeline

    monkeypatch.delenv("S3_BACKUP_BUCKET", raising=False)
    with pytest.raises(SystemExit):
        pipeline.cloud_run()


def test_archive_uploads_finished_item_once(data_dir, monkeypatch):
    from tfs import archive, config

    r2 = FakeR2()
    r2.put_object = lambda Bucket, Key, Body, **kw: r2.objects.__setitem__(Key, Body)
    for k, v in {"B2_ENDPOINT": "https://b2", "B2_BUCKET": "arch", "B2_KEY_ID": "k", "B2_APP_KEY": "s"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(archive, "_client", lambda: r2)
    d = config.item_dir("2026-09-27-vert0")
    (d / "work").mkdir()
    (d / "work" / "tmp.mp4").write_bytes(b"x")
    (d / "video.mp4").write_bytes(b"v")
    (d / "seo.json").write_text("{}")
    item = {"id": "2026-09-27-vert0", "kind": "vertical", "anchor_at": "2026-09-27T07:30:00+08:00",
            "status": "scheduled", "data": {"title": "t"}}
    assert archive.archive_item(item) == 2
    assert "2026/09/2026-09-27-vert0/video.mp4" in r2.objects
    assert "2026/09/2026-09-27-vert0/item.json" in r2.objects
    assert not any("work/" in k or "_archived" in k for k in r2.objects)
    assert archive.archive_item(item) == 0              # nothing new


def test_proofreader_matches_words_by_scene():
    from tfs import qa

    heard = [("Alam", 0.1, 0.3), ("mo", 0.3, 0.4), ("ba", 0.4, 0.5), ("limang", 2.1, 2.4), ("bilyon", 2.4, 2.8)]
    assert qa.split_by_scene(heard, [0.0, 2.0, 4.0]) == ["Alam mo ba", "limang bilyon"]
    assert qa.scene_match("Alam mo ba *talaga*?", "alam mo ba talaga") == 1.0
    assert qa.scene_match("Limang bilyon ang nawala", "limang ang") < 0.8        # skipped words get flagged


def test_vertical_word_budget():
    from tfs.agents import writers

    assert 100 <= writers.max_words("vertical") <= 115


@pytest.mark.parametrize("platform", ["youtube_shorts", "tiktok", "instagram_reel", "facebook_post"])
def test_publish_one_reaches_each_provider(data_dir, monkeypatch, platform):
    from datetime import timedelta

    from tfs import db, pipeline
    from tfs.config import item_dir, now
    from tfs.models import SeoPack
    from tfs.publish import meta, postforme, youtube

    monkeypatch.setattr(pipeline, "_ensure_packaging_checked", lambda item, d: None)   # covered in its own tests

    d = item_dir("2026-09-27-vert0")
    (d / "video.mp4").write_bytes(b"v")
    (d / "s0.jpg").write_bytes(b"j")
    fields = {k: "x" for k in SeoPack.model_fields}
    fields["tags"] = ["a"]
    (d / "seo.json").write_text(SeoPack(**fields).model_dump_json())
    slot = db.iso(now() + timedelta(hours=1))
    db.upsert_item("2026-09-27-vert0", "vertical", slot, "scheduled",
                   {"title": "t", "video": str(d / "video.mp4"), "slides": [str(d / "s0.jpg")]})
    db.queue_post("2026-09-27-vert0", platform, slot)
    calls = []
    monkeypatch.setattr(youtube, "upload", lambda *a, **k: calls.append("yt") or "vid")
    monkeypatch.setattr(postforme, "create_post", lambda *a, **k: calls.append("pfm") or "sp_1")
    monkeypatch.setattr(meta, "ig_reel", lambda *a, **k: calls.append("ig") or "ig1")
    monkeypatch.setattr(meta, "fb_photos", lambda *a, **k: calls.append("fb") or "fb1")
    status, remote = pipeline._publish_one(db.queued_posts()[0])
    assert remote in ("vid", "sp_1", "ig1", "fb1") and len(calls) == 1


def test_no_tofu_boxes(data_dir):
    from tfs.media.design import font, glyphsafe

    assert glyphsafe("Proclamation ① 1081 ★", font("display", 40)).split() == ["Proclamation", "1", "1081"]


def test_review_fix_clears_the_render_and_a_flagged_thumbnail(data_dir):
    from tfs import pipeline
    from tfs.models import ReviewReport

    d = data_dir / "items" / "x"
    (d / "work").mkdir(parents=True)
    for f in ("video.mp4", "starts.json", "thumb_art.png", "thumbnail.jpg"):
        (d / f).write_bytes(b"x")
    report = ReviewReport(passed=False, redo_images={"1": "wrong year on the card", "thumbnail": "text cut"},
                          redo_audio={}, warnings=[], appeal=6, hook_frame=6, summary="")
    pipeline._apply_video_fixes(d, report)
    assert not any((d / f).exists() for f in ("video.mp4", "starts.json", "thumb_art.png", "thumbnail.jpg"))
    assert not (d / "work").exists()


def test_minor_narration_notes_never_reject_a_piece(data_dir, monkeypatch):
    from tfs import db, pipeline, qa
    from tfs.models import ReviewReport

    db.upsert_item("x", "vertical", "2026-09-27T07:30:00+08:00", "planned", {})
    report = ReviewReport(passed=False, major_audio=False, redo_images={}, redo_audio={"3": ""}, warnings=["minor"],
                          appeal=6, hook_frame=7, summary="s")
    monkeypatch.setattr(qa, "safe", lambda fn, built: report)
    d = data_dir / "items" / "x"
    d.mkdir(parents=True)
    result = pipeline._reviewed(db.get_item("x"), d, lambda: "built", lambda b: report, lambda r: None)
    assert result == ("built", report)
    major = report.model_copy(update={"major_audio": True, "major_scenes": ["3"]})   # same scene every round
    for f in d.glob("qa_r*.json"):
        f.unlink()
    monkeypatch.setattr(qa, "safe", lambda fn, built: major)
    monkeypatch.setattr(pipeline.notify, "send", lambda *a, **k: None)
    assert pipeline._reviewed(db.get_item("x"), d, lambda: "built", lambda b: major, lambda r: None) is None


def test_voice_only_problems_get_extra_rounds(data_dir, monkeypatch):
    from tfs import db, pipeline, qa
    from tfs.models import ReviewReport

    db.upsert_item("z", "vertical", "2026-09-27T07:30:00+08:00", "planned", {})
    d = data_dir / "items" / "z"
    d.mkdir(parents=True)
    bad = ReviewReport(passed=False, major_audio=True, major_scenes=["11"], redo_images={}, redo_audio={"11": "Ilang"},
                       warnings=["x"], appeal=7, hook_frame=6, summary="s")
    good = bad.model_copy(update={"passed": True, "major_audio": False, "redo_audio": {}})
    reports = iter([bad, bad, bad, good])
    monkeypatch.setattr(qa, "safe", lambda fn, built: next(reports))
    assert pipeline._reviewed(db.get_item("z"), d, lambda: "built", lambda b: None, lambda r: None) == ("built", good)


def test_one_off_narration_flag_is_a_note_not_a_rejection(data_dir, monkeypatch):
    from tfs import db, pipeline, qa
    from tfs.models import ReviewReport

    db.upsert_item("w", "vertical", "2026-09-27T07:30:00+08:00", "planned", {})
    d = data_dir / "items" / "w"
    d.mkdir(parents=True)
    rounds = iter([ReviewReport(passed=False, major_audio=True, major_scenes=[k], redo_images={}, redo_audio={k: ""},
                                warnings=[f"voice, scene {k} (major): x"], appeal=7, hook_frame=7, summary="s")
                   for k in ("2", "5", "9")])                        # a different scene each round (judge noise)
    monkeypatch.setattr(qa, "safe", lambda fn, built: next(rounds))
    built, report = pipeline._reviewed(db.get_item("w"), d, lambda: "built", lambda b: None, lambda r: None)
    assert built == "built" and report.major_scenes == ["9"]           # accepted; the flag becomes a note


def test_youtube_tags_always_fit_the_rules():
    from tfs.publish.youtube import clean_tags

    tags = clean_tags(["#Philippines", "flood control <scam>", "DPWH, COA"] + [f"mahabang tag bilang {i}" for i in range(60)])
    assert tags[0] == "Philippines" and "flood control scam" in tags
    assert sum(len(t) + (2 if " " in t else 0) for t in tags) + len(tags) - 1 <= 500
    assert all("<" not in t and "," not in t and len(t) <= 30 for t in tags)


def test_metadata_follows_every_platform_rule():
    from tfs.models import SeoPack
    from tfs.publish import limits

    # YouTube's documented examples: "Foo-Baz" costs 7, "Foo Baz" costs 9 (implicit quotes); commas count
    assert limits.tags_length(["Foo-Baz"]) == 7 and limits.tags_length(["Foo Baz"]) == 9
    assert limits.tags_length(["Foo-Baz", "Foo Baz"]) == 17
    tags = limits.youtube_tags(["#Philippines", "flood control <scam>", "DPWH, COA", "philippines"]
                               + [f"mahabang tag bilang {i}" for i in range(80)])
    assert tags[:2] == ["Philippines", "flood control scam"] and limits.tags_length(tags) <= 500
    assert all(c not in t for t in tags for c in "<>#,")
    title = limits.youtube_title("Ang <Pinaka> " + "mahabang pamagat " * 12)
    assert len(title) <= 100 and "<" not in title
    desc = limits.youtube_description("₱" * 3000 + "\n" + "😀" * 500)
    assert len(desc.encode("utf-8")) <= 5000 and "<" not in desc
    pack = SeoPack(youtube_description="d", tags=["a b"] * 3, shorts_title="t",
                   instagram_caption="Hook " + " ".join(f"#tag{i}" for i in range(45)), facebook_caption="f",
                   tiktok_caption="x" * 3000)
    fixed = limits.enforce_seo(pack)
    assert len(limits.HASHTAG.findall(fixed.instagram_caption)) == 30
    assert len(fixed.tiktok_caption) <= 2200 and fixed.tags == ["a b"]


def test_instagram_copy_meets_reels_spec(data_dir):
    import json
    import subprocess

    from tfs.publish.meta import ig_ready

    src = data_dir / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=540x960:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-c:a", "aac",
                    "-b:a", "192k", "-ar", "44100", "-shortest", str(src)], check=True)
    out = ig_ready(src)
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
                                     capture_output=True, text=True).stdout)["streams"]
    audio = next(s for s in info if s["codec_type"] == "audio")
    video = next(s for s in info if s["codec_type"] == "video")
    assert audio["codec_name"] == "aac" and audio["sample_rate"] == "48000" and int(audio["bit_rate"]) <= 136000
    assert video["codec_name"] == "h264" and video["pix_fmt"] == "yuv420p"
    assert b"elst" not in out.read_bytes()[:200000]            # no edit list


def test_ig_reel_uses_a_signed_url_and_cleans_up(data_dir, monkeypatch):
    from tfs.publish import meta

    video = data_dir / "v.mp4"
    video.write_bytes(b"v")
    calls, deleted = [], []
    monkeypatch.setenv("META_IG_USER_ID", "ig1")
    monkeypatch.setattr(meta, "ig_ready", lambda v: v)
    monkeypatch.setattr(meta, "_signed_url", lambda p: ("https://r2.example/signed", "tmp/ig/v.mp4"))
    monkeypatch.setattr(meta, "_wait_ready", lambda c: None)

    def fake_call(method, path, **kw):
        calls.append((path, kw))
        return {"id": "c1" if path.endswith("/media") else "post1"}
    monkeypatch.setattr(meta, "_call", fake_call)

    class S3:
        def delete_object(self, Bucket, Key):
            deleted.append(Key)
    from tfs import state
    monkeypatch.setattr(state, "_s3", lambda: S3())
    monkeypatch.setattr(state, "_bucket", lambda: "b")
    assert meta.ig_reel(video, "cap") == "post1"
    assert calls[0][1]["video_url"] == "https://r2.example/signed" and deleted == ["tmp/ig/v.mp4"]


def test_long_form_is_eight_to_fifteen_minutes():
    from tfs.agents import writers

    assert writers.min_words("long_form") == int(8 * 60 * writers.WORDS_PER_SECOND)
    assert writers.max_words("long_form") == int(15 * 60 * writers.WORDS_PER_SECOND)
    assert "8-15 minutes" in writers._length("long_form")


def test_threads_text_fits_and_keeps_one_topic_tag():
    from tfs.publish import limits

    caption = "The Court killed PDAF in 2013. " * 30 + "\n\nSource: COA.\n\n#PorkBarrel #PDAF #Philippines"
    text = limits.threads_text(caption)
    assert len(text) <= 500 and text.endswith("#PorkBarrel") and "#PDAF" not in text
    assert limits.threads_text("Short one. #A #B") == "Short one.\n\n#A"


def test_carousels_go_to_tiktok_photos_and_threads(data_dir, monkeypatch):
    from tfs import pipeline
    from tfs.publish import postforme

    sent = {}

    def fake_call(method, path, platform=None, **kw):
        if path == "/media/create-upload-url":
            return {"upload_url": "https://u", "media_url": "https://m"}
        sent.update(kw.get("json") or {})
        return {"id": "pfm1"}

    monkeypatch.setattr(postforme, "_call", fake_call)
    monkeypatch.setattr(postforme, "account_id", lambda p: "acct")
    monkeypatch.setattr(postforme.requests, "put", lambda *a, **k: type("R", (), {"raise_for_status": lambda s: None})())
    slides = []
    for i in range(3):
        f = data_dir / f"slide{i}.jpg"
        f.write_bytes(b"jpg")
        slides.append(f)
    from datetime import timedelta
    from tfs.config import now
    postforme.create_post("tiktok_carousel", "caption", slides, now() + timedelta(hours=2), title="A title")
    cfg = sent["platform_configurations"]["tiktok"]
    assert len(sent["media"]) == 3 and cfg["auto_add_music"] and "allow_duet" not in cfg
    assert pipeline._provider("tiktok_carousel") == "postforme" and pipeline._provider("threads_carousel") == "direct"
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    assert not pipeline._connected("threads_carousel")               # not connected yet: skipped, not failed
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "t")
    assert pipeline._connected("threads_carousel")


def test_scheduling_uses_the_current_schedule(data_dir, monkeypatch):
    from tfs import db, pipeline

    db.upsert_item("2026-11-30-caro0", "carousel", "2026-11-30T11:00:00+08:00", "producing",
                   {"platforms": {"instagram_carousel": "2026-11-30T11:00:00+08:00",
                                  "facebook_post": "2026-11-30T10:00:00+08:00"}})
    monkeypatch.setattr(pipeline, "_notify_ready", lambda item: None)
    monkeypatch.setattr("tfs.archive.archive_item", lambda item: None)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(pipeline, "paused_kinds", lambda: set())     # carousels pause under style v2
    monkeypatch.setattr("tfs.slots.paused_kinds", lambda: set())
    monkeypatch.setattr("tfs.post_now.paused_kinds", lambda: set())
    pipeline._schedule(db.get_item("2026-11-30-caro0"), slides=[])
    posts = {p["platform"]: p["slot_at"] for p in db.queued_posts()}
    assert posts == {"instagram_carousel": "2026-11-30T19:30:00+08:00", "facebook_post": "2026-11-30T19:30:00+08:00",
                     "tiktok_carousel": "2026-11-30T19:30:00+08:00"}          # Threads waits until it's connected


def test_post_now_publishes_on_every_carousel_platform(data_dir, monkeypatch):
    from tfs import db, pipeline, post_now, state
    from tfs.agents import editor

    monkeypatch.setattr(state, "enabled", lambda: True)
    monkeypatch.setattr(state, "pull", lambda: None)
    monkeypatch.setattr(state, "push", lambda: 0)

    def plan(units):
        u = units[0]
        db.upsert_item(u.id, u.kind, db.iso(u.anchor), "planned",
                       {"working_title": "Permits", "platforms": {p: db.iso(t) for p, t in u.platforms.items()}})
        return [u.id]

    monkeypatch.setattr(editor, "plan", plan)
    monkeypatch.setattr(pipeline, "produce", lambda item_id: pipeline._schedule(db.get_item(item_id), slides=[]))
    monkeypatch.setattr(pipeline, "_notify_ready", lambda item: None)
    monkeypatch.setattr("tfs.archive.archive_item", lambda item: None)
    monkeypatch.setattr(pipeline, "paused_kinds", lambda: set())     # carousels pause under style v2
    monkeypatch.setattr("tfs.slots.paused_kinds", lambda: set())
    monkeypatch.setattr("tfs.post_now.paused_kinds", lambda: set())
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "t")
    published = []
    monkeypatch.setattr(pipeline, "publish_due", lambda: published.extend(p["platform"] for p in db.queued_posts()))
    out = post_now.run("carousel", "Starting a business in the Philippines", "look at Reddit")
    assert sorted(published) == ["facebook_post", "instagram_carousel", "threads_carousel", "tiktok_carousel"]
    item = db.items_with_status("scheduled")[0]
    assert "now-carousel" in item["id"] and "Reddit" in item["data"]["owner_request"] and out.startswith(item["id"])


def _report(appeal, passed=True, improve=None):
    from tfs.models import ReviewReport
    return ReviewReport(passed=passed, redo_images={}, redo_audio={}, warnings=[], appeal=appeal, hook_frame=appeal,
                        summary="", improve=improve or {})


def test_polish_keeps_a_better_version_and_reverts_a_worse_one(data_dir):
    from tfs import pipeline

    for after_appeal, expected in ((8, "polished"), (5, "original")):
        d = data_dir / f"item{after_appeal}"
        (d / "slides").mkdir(parents=True)
        art = d / "slides" / "art01.png"
        art.write_text("original")

        def fix(report, art=art):
            assert report.redo_images == {"1": "props float"}
            art.write_text("polished")

        out = pipeline._polish({"id": "x"}, d, lambda art=art: art.read_text(),
                               lambda built, a=after_appeal: _report(a), fix, "original",
                               _report(6, improve={"1": "props float"}))
        assert out[0] == expected and art.read_text() == expected
        assert not (d.parent / f"{d.name}.prepolish").exists()
    # a good piece is left alone
    assert pipeline._polish({"id": "y"}, data_dir, lambda: "b", lambda b: _report(9), lambda r: None, "a",
                            _report(8, improve={"1": "x"}))[0] == "a"


def test_creative_director_notes_reach_the_designers(data_dir, monkeypatch):
    from tfs import config, db
    from tfs.agents import creative
    from tfs.models import AgentNote, CreativeNotes

    for i in range(2):
        db.upsert_item(f"c{i}", "carousel", "2026-09-28T08:30:00+08:00", "scheduled", {"title": f"t{i}"})
        d = config.item_dir(f"c{i}")
        d.mkdir(parents=True, exist_ok=True)
        rep = _report(6)
        rep.warnings = ["slide 2: documents float beside the head"]
        (d / "qa_r0.json").write_text(rep.model_dump_json())
    seen = {}

    def fake(agent, user, schema):
        seen["user"] = user
        return CreativeNotes(summary="Floating props keep coming up.",
                             agent_notes=[AgentNote(agent="atlas_designer", notes=["Props go in hands."]),
                                          AgentNote(agent="scriptwriter", notes=["not ours to edit"])])

    monkeypatch.setattr(creative.llm, "structured", fake)
    monkeypatch.setattr(creative.notify, "send", lambda text: None)
    assert creative.due() and creative.run()
    assert "documents float" in seen["user"]
    assert "Props go in hands." in config.load_prompt("atlas_designer")
    assert not (creative.notes_dir() / "scriptwriter.md").exists() and not creative.due()


def test_post_now_requests_are_picked_up_by_the_run(monkeypatch):
    from tfs import pipeline, post_now, state

    queued = [{"type": "post-now", "kind": "carousel", "topic": "Permits", "note": "Reddit"}]
    monkeypatch.setattr(state, "take_requests", lambda: [queued.pop()] if queued else [])
    made = []
    monkeypatch.setattr(post_now, "make", lambda kind, topic, note: made.append((kind, topic, note)) or "ok")
    assert pipeline._owner_requests() and made == [("carousel", "Permits", "Reddit")]
    assert not pipeline._owner_requests()                       # nothing left: the run carries on as usual


def test_instagram_publish_waits_out_media_not_available(monkeypatch):
    from tfs.publish import meta

    calls = []

    def fake(method, path, files=None, **params):
        calls.append(path)
        if len(calls) < 3:
            raise RuntimeError("Graph API 1/media_publish: Media ID is not available")
        return {"id": "m1"}

    monkeypatch.setattr(meta, "_call", fake)
    monkeypatch.setattr(meta.time, "sleep", lambda s: None)
    assert meta._publish("1", "c1") == "m1" and len(calls) == 3


def test_youtube_upload_resumes_after_a_network_drop(monkeypatch, tmp_path):
    from tfs.publish import youtube

    class Req:
        n = 0

        def next_chunk(self):
            Req.n += 1
            if Req.n == 1:
                raise OSError("EOF occurred in violation of protocol")
            return None, {"id": "vid1"}

    class Videos:
        def insert(self, **kw):
            return Req()

    class Api:
        def videos(self):
            return Videos()

    monkeypatch.setattr(youtube, "api", lambda: Api())
    monkeypatch.setattr(youtube, "MediaFileUpload", lambda *a, **k: None)
    monkeypatch.setattr(youtube.time, "sleep", lambda s: None)
    from datetime import timedelta
    from tfs.config import now
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    assert youtube.upload(video, "t", "d", ["a"], now() + timedelta(hours=2)) == "vid1"


def test_paused_kinds_are_not_planned_or_produced(data_dir, monkeypatch):
    from tfs import db, pipeline, slots

    monkeypatch.setattr(slots, "paused_kinds", lambda: {"long_form", "vertical"})
    monkeypatch.setattr(pipeline, "paused_kinds", lambda: {"long_form", "vertical"})
    assert {u.kind for u in slots.day_units(date(2026, 9, 30))} == {"carousel"}
    db.upsert_item("2026-09-30-vert0", "vertical", "2026-09-30T04:30:00+08:00", "planned", {})
    monkeypatch.setattr(pipeline.writers, "research", lambda item: (_ for _ in ()).throw(AssertionError("made")))
    pipeline.produce("2026-09-30-vert0")                               # paused: left alone, not failed
    assert db.get_item("2026-09-30-vert0")["status"] == "planned"


def test_facebook_reel_is_not_posted_twice(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from tfs.publish import meta

    monkeypatch.setenv("META_PAGE_ID", "p1")
    posted = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
    calls = []

    def fake(method, path, files=None, **params):
        calls.append((method, params.get("upload_phase")))
        if method == "GET":
            return {"data": [{"id": "r9", "description": "Jeepney caption", "created_time": posted}]}
        raise AssertionError("must not upload again")

    monkeypatch.setattr(meta, "_call", fake)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    assert meta.fb_reel(video, "Jeepney caption") == "r9" and calls == [("GET", None)]


def test_audit_matches_slides_by_image_not_by_file(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw

    from tfs import audit

    imgs = []
    for i in range(3):
        im = Image.new("RGB", (400, 500), (240, 240, 240))
        ImageDraw.Draw(im).rectangle([40 + i * 110, 60, 120 + i * 110, 440], fill=(20, 20, 20))
        imgs.append(im)
    local = [audit._hash(im) for im in imgs]
    served = {f"u{i}": imgs[i].resize((200, 250)) for i in range(3)}       # re-encoded smaller, like a CDN
    monkeypatch.setattr(audit, "_fetch", lambda url: served.get(url))
    assert audit._match(local, ["u0", "u1", "u2"]) == ["1", "2", "3"]
    assert audit._match(local, ["u2", "u0", "u1", "missing"]) == ["3", "1", "2", "x"]


def test_postforme_puts_carousel_slides_back_in_order(monkeypatch):
    from tfs.publish import postforme

    stored = {"media": [{"url": u} for u in ("c", "a", "b")]}      # Post for Me's scrambled copy
    calls = []

    def fake(method, path, platform=None, **kw):
        calls.append(method)
        if method == "PUT":
            stored["media"] = kw["json"]["media"]
        return stored

    monkeypatch.setattr(postforme, "_call", fake)
    body = {"media": [{"url": u} for u in ("a", "b", "c")]}
    postforme._ensure_order("p1", body, "tiktok")
    assert [m["url"] for m in stored["media"]] == ["a", "b", "c"] and "PUT" in calls

    stored["media"] = [{"url": u} for u in ("b", "a", "c")]
    monkeypatch.setattr(postforme, "_call", lambda m, path, platform=None, **kw:
                        calls.append(m) or {"media": [{"url": u} for u in ("b", "a", "c")]})
    with pytest.raises(RuntimeError, match="cancelled"):              # won't stay fixed: cancel, don't post
        postforme._ensure_order("p1", body, "tiktok")
    assert calls[-1] == "DELETE"


def test_meta_container_creation_retries_temporary_errors(monkeypatch):
    from tfs.publish import meta, threads

    for mod in (meta, threads):
        tries = []

        def fake(method, path, files=None, _t=tries, **params):
            _t.append(1)
            if len(_t) < 3:
                raise RuntimeError("Graph API x/media: An unknown error has occurred.")
            return {"id": "c1"}

        monkeypatch.setattr(mod, "_call", fake)
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)
        assert mod._create("1/media", image_url="u")["id"] == "c1" and len(tries) == 3

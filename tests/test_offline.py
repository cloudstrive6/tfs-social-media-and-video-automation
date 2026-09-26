"""Tests for everything that runs without API keys: slots, db, text cleanup, cards, rendering, gate."""
import os
import subprocess
from datetime import date

import pytest


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TFS_DATA_DIR", str(tmp_path))
    yield tmp_path


def test_day_units_match_schedule():
    from tfs import slots

    units = slots.day_units(date(2026, 9, 28))
    kinds = [u.kind for u in units]
    assert kinds.count("long_form") == 1 and kinds.count("vertical") == 3 and kinds.count("carousel") == 2
    vert0 = next(u for u in units if u.id.endswith("vert0"))
    assert set(vert0.platforms) == {"youtube_shorts", "instagram_reel", "facebook_reel"}  # tiktok disabled
    assert vert0.anchor.strftime("%H:%M") == "07:30"


def test_schedule_override(data_dir):
    from tfs import config, slots

    (data_dir / "schedule_override.yaml").write_text("youtube_long: ['09:00', '14:00', '19:30']\n")
    assert config.schedule()["youtube_long"][0] == "09:00"
    long0 = next(u for u in slots.day_units(date(2026, 9, 28)) if u.id.endswith("long0"))
    assert long0.anchor.strftime("%H:%M") == "09:00"


def test_tts_clean_strips_markup():
    from tfs.media.tts import clean

    raw = "Grabe, *₱5.4 billion* [S3] [CARD: stat ₱5.4B] [pause] [laugh] walang tubig."
    assert clean(raw, keep_audio_tags=False) == "Grabe, ₱5.4 billion ... walang tubig."
    assert "[laugh]" in clean(raw, keep_audio_tags=True)


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


def test_gate_routes_allegations_to_human(monkeypatch):
    from tfs import db, pipeline
    from tfs.models import FactCheck, Script

    monkeypatch.setattr(pipeline.notify, "send", lambda text: None)
    db.upsert_item("i1", "long_form", "2026-09-28T08:00:00+08:00", "planned", {})
    fc = FactCheck(verdict="pass", script=Script(scenes=[], sources=[]), issues=[],
                   names_living_person_with_allegation=True)
    assert pipeline._gate(db.get_item("i1"), fc) is False
    assert db.get_item("i1")["status"] == "awaiting_approval"
    db.set_status("i1", "approved", approved=True)
    assert pipeline._gate(db.get_item("i1"), fc) is True


def _tone(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=duration={seconds}",
                    str(path)], check=True)


@pytest.mark.parametrize("kind,size", [("long_form", (1920, 1080)), ("vertical", (1080, 1920))])
def test_render_keeps_audio_and_video_in_sync(data_dir, kind, size):
    from tfs.media import cards, render
    from tfs.media.tts import Clip, duration

    shots, clips = [], []
    for i, secs in enumerate((1.3, 2.1)):
        img = cards.render_card("stat", "halaga ng proyekto", ["₱5.4B"], size, data_dir / f"c{i}.png")
        mp3 = data_dir / f"a{i}.mp3"
        _tone(mp3, secs)
        clips.append(Clip(mp3, duration(mp3), [("grabe", 0.0, 0.5), ("talaga", 0.5, 1.0)]))
        shots.append(render.Shot(img, "card"))
    out, starts = render.render(shots, clips, kind, data_dir / "work", data_dir / "out.mp4", "hook")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration,width,height",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
    assert f"{size[0]},{size[1]}" in probe
    durations = [float(line.split(",")[-1]) for line in probe.strip().splitlines()]
    assert abs(durations[0] - durations[1]) < 0.1
    assert starts[0] == 0.0 and starts[1] > 1.3


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


def test_youtube_goes_direct_everything_else_via_postforme():
    from tfs.pipeline import _provider

    assert _provider("youtube") == "direct" and _provider("youtube_shorts") == "direct"
    for platform in ("instagram_reel", "instagram_carousel", "facebook_reel", "facebook_post", "tiktok"):
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

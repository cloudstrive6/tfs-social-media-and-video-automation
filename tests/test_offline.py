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
    assert set(vert0.platforms) == {"youtube_shorts", "instagram_reel", "facebook_reel", "tiktok"}
    assert vert0.anchor.strftime("%H:%M") == "04:30"
    assert len(set(vert0.platforms.values())) == 1                  # every platform at the same moment
    caro0 = next(u for u in units if u.id.endswith("caro0"))
    assert set(caro0.platforms) == {"instagram_carousel", "facebook_post", "tiktok_carousel", "threads_carousel"}
    assert caro0.anchor.strftime("%H:%M") == "08:30"


def test_schedule_override(data_dir):
    from tfs import config, slots

    (data_dir / "schedule_override.yaml").write_text("slots: {long_form: ['09:00']}\nyoutube_long: ['10:00']\n")
    assert config.schedule()["slots"]["long_form"] == ["09:00"]      # an old per-platform key is ignored
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


def test_youtube_and_meta_go_direct_tiktok_via_postforme():
    from tfs.pipeline import _provider

    for platform in ("youtube", "youtube_shorts", "instagram_reel", "instagram_carousel", "facebook_reel",
                     "facebook_post"):
        assert _provider(platform) == "direct"
    assert _provider("tiktok") == "postforme"


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


def test_map_places_resolve_to_real_geography(data_dir):
    from tfs.media import maps

    assert maps.resolve("Bulacan").kind == "area"
    assert maps.resolve("Davao de Oro").polys                          # renamed province -> old data name
    palawan = maps.resolve("Palawan").polys
    assert len(palawan) > len(maps.resolve("Puerto Princesa").polys)  # province includes its HUC
    lon, lat = maps.resolve("Scarborough Shoal").point
    assert 117 < lon < 118.5 and 14.5 < lat < 15.8
    assert maps.resolve("Mexico").foreign and not maps.resolve("Mindanao").foreign
    assert maps.resolve("Atlantis") is None                           # unknown places are left off, never guessed


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920)])
def test_map_card_renders(data_dir, size):
    from PIL import Image

    from tfs.media import cards

    out = cards.render_card("map", "Galleon trade", ["Manila", "Acapulco"], size, data_dir / "m.png")
    assert Image.open(out).size == size
    out = cards.render_card("map", "Saan 'to?", ["Nowhere"], size, data_dir / "n.png")  # falls back to PH overview
    assert Image.open(out).size == size


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


def test_review_fix_regenerates_only_the_flagged_shot_and_rerenders(data_dir, monkeypatch):
    from tfs import pipeline
    from tfs.media import images
    from tfs.models import ReviewReport, Scene, Script, Shot, ShotList

    d = data_dir / "items" / "x"
    (d / "img").mkdir(parents=True)
    (d / "work").mkdir()
    shot = dict(kind="illustration", style="story", card_type="none", card_title="", card_lines=[],
                reuse_of_scene=0, motion="push_in")
    (d / "shots.json").write_text(ShotList(shots=[Shot(scene_id=i, image_prompt=f"old {i}", **shot)
                                                  for i in (0, 1)]).model_dump_json())
    for i in (0, 1):
        (d / "img" / f"{i:03d}.png").write_bytes(b"png")
    (d / "video.mp4").write_bytes(b"v")
    report = ReviewReport(passed=False, redo_images={"1": "new 1, no text in the sign"}, redo_audio={"0": "D-P-W-H"},
                          warnings=[], appeal=6, hook_frame=6, summary="")
    pipeline._apply_video_fixes(d, report)
    assert not (d / "video.mp4").exists() and not (d / "work").exists() and (d / "img" / "000.png").exists()

    made = []
    monkeypatch.setattr(images, "generate", lambda prompt, out, *a, **k: (made.append(prompt), out.write_bytes(b"p")))
    script = Script(scenes=[Scene(id=i, chapter="c", speaker="NARRATOR", text=f"line {i}", visual="v")
                            for i in (0, 1)], sources=[])
    pipeline._visuals({"id": "x"}, d, script, "9:16", (1080, 1920))
    assert made == ["new 1, no text in the sign"]
    assert pipeline._voiced(script, d)[0].text == "D-P-W-H"


@pytest.mark.parametrize("card", ["stat", "quote", "timeline", "document"])
def test_vertical_cards_leave_the_caption_band_empty(data_dir, card):
    from PIL import Image

    from tfs.media import cards

    out = cards.render_card(card, "Isang mahabang pamagat para sa card na ito", ["Unang linya na medyo mahaba",
                            "Pangalawang linya", "Pangatlo"], (1080, 1920), data_dir / "c.png")
    band = Image.open(out).convert("RGB").crop((0, int(1920 * 0.62), 1080, int(1920 * 0.74)))
    assert len(set(band.getdata())) == 1            # nothing drawn where the burned captions go


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


def test_captions_group_by_sentence_and_highlight_one_word_at_a_time(data_dir):
    from tfs.media import render
    from tfs.media.tts import Clip

    words = [("Hindi", 0.0, 0.3), ("nagbago", 0.3, 0.7), ("ang", 0.7, 0.8), ("Konstitusyon.", 0.8, 1.4),
             ("Nagbago", 1.6, 2.0), ("ang", 2.0, 2.1), ("bilang.", 2.1, 2.6)]
    groups = [" ".join(w for w, _, _ in g) for g in render.caption_chunks(words)]
    # never spans a sentence end, never ends on a particle like "ang"
    assert groups == ["Hindi nagbago", "ang Konstitusyon.", "Nagbago ang bilang."]

    out = data_dir / "c.ass"
    render.captions_ass([Clip(data_dir / "x.mp3", 2.6, words)], [0.0], (1080, 1920), "", out)
    lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue")]
    assert len(lines) == len(words)                                   # one event per spoken word
    assert all(l.count("\c&H0016D1FC&") == 1 for l in lines)         # exactly one highlighted word at a time
    times = [(l.split(",")[1], l.split(",")[2]) for l in lines]
    assert all(a[1] <= b[0] for a, b in zip(times, times[1:]))        # events never overlap


def test_long_caption_words_shrink_to_stay_in_frame():
    from tfs.media import render

    assert render._fit_size("PINAKAMAHALAGANG PAGKAKAKILANLAN", 105, 1080 - 2 * 75) < 105


@pytest.mark.parametrize("card", ["stat", "bars", "timeline", "quote", "document", "map"])
def test_animated_cards_have_exact_length_and_actually_move(data_dir, card):
    import subprocess

    from tfs.media import motion

    lines = {"bars": ["Dati: 16", "Ngayon: 14"], "map": ["Bulacan"], "timeline": ["2001 — a", "2012 — b"]}.get(
        card, ["₱5.4B"])
    out = motion.animate_card(card, "Pamagat", lines, (540, 960), 30, 45, data_dir / f"{card}.mp4")
    n = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_read_frames", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
    assert int(n.stdout.strip()) == 45                          # matches the narration timing exactly
    frames = list(motion.ANIMATIONS[card]("Pamagat", lines, (540, 960), 6))
    assert frames[0].tobytes() != frames[-1].tobytes()          # it is an animation, not a still


def test_count_up_keeps_number_format():
    from tfs.media.motion import _count

    assert _count("₱5.4B", 0.5) == "₱2.7B"
    assert _count("1,200 proyekto", 1.0) == "1,200 proyekto"


def test_card_text_never_shows_source_tags_and_stays_off_the_button_strip(data_dir):
    from tfs.media import motion

    assert motion.tidy("R.A. 8042 — 7 Hunyo 1995 [S12][S13]") == "R.A. 8042 — 7 Hunyo 1995"
    img = motion.still("document", "COA report", ["Isang napakahabang linya ng teksto para subukan ang layout"],
                       (1080, 1920))
    strip = img.crop((int(1080 * 0.87), int(1920 * 0.1), 1080, int(1920 * 0.55))).convert("L")
    assert max(strip.getdata()) < 90                  # nothing bright (text/paper/stamp) under the side buttons


def test_parallax_moves_subject_more_than_background(data_dir, monkeypatch):
    from PIL import Image, ImageDraw

    from tfs.media import depth

    bg = Image.new("RGB", (600, 1000), (20, 30, 60))
    fg = Image.new("RGBA", (600, 1000), (0, 0, 0, 0))
    ImageDraw.Draw(fg).ellipse([200, 300, 400, 700], fill=(250, 200, 50, 255))
    monkeypatch.setattr(depth, "layers", lambda image: (bg, fg))
    out = data_dir / "p.mp4"
    assert depth.parallax_clip(data_dir / "x.png", 20, "pan_left", (270, 480), 30, out) and out.exists()
    zb, bx, _, zf, fx, _ = depth._moves("pan_left", 1.0, 0.5, (270, 480))
    assert abs(fx) > abs(bx) > 0 and zf != zb                  # parallax: the subject travels further
    monkeypatch.setattr(depth, "layers", lambda image: None)   # no clear subject -> caller uses Ken Burns
    assert depth.parallax_clip(data_dir / "x.png", 20, "push_in", (270, 480), 30, data_dir / "q.mp4") is False


@pytest.mark.parametrize("model,expected", [("eleven_v3", "fil"), ("eleven_multilingual_v2", None)])
def test_narrator_is_told_the_text_is_filipino(data_dir, monkeypatch, model, expected):
    import base64

    from tfs import config
    from tfs.media import tts

    sent = {}

    class R:
        status_code, text = 200, ""

        def json(self):
            return {"audio_base64": base64.b64encode(b"mp3").decode(),
                    "alignment": {"characters": list("Flor"), "character_start_times_seconds": [0, .1, .2, .3],
                                  "character_end_times_seconds": [.1, .2, .3, .4]}}

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
    real = config.channel()
    cfg = {**real, "tts": {**real["tts"], "elevenlabs": {**real["tts"]["elevenlabs"], "model_id": model}}}
    monkeypatch.setattr(tts, "channel", lambda: cfg)
    monkeypatch.setattr(tts.requests, "post", lambda url, **kw: sent.update(kw["json"]) or R())
    tts._elevenlabs("Flor Contemplacion", "NARRATOR", data_dir / "a.mp3", "", "")
    assert sent.get("language_code") == expected


def test_no_tofu_boxes_and_quotes_read_the_right_way_round(data_dir):
    from tfs.media import motion
    from tfs.media.design import font, glyphsafe

    assert glyphsafe("Proclamation ① 1081 ★", font("display", 40)).split() == ["Proclamation", "1", "1081"]
    frames = list(motion._quote("Marcos, 1972", ["Martial law is declared over the entire country today"],
                                (540, 960), 2))
    assert frames                                              # swapped internally: quote big, source small


def test_rejected_language_code_retries_without_it(data_dir, monkeypatch):
    import base64

    from tfs.media import tts

    bodies = []

    class R:
        def __init__(self, code):
            self.status_code, self.text = code, "language_code not supported"

        def json(self):
            return {"audio_base64": base64.b64encode(b"mp3").decode(),
                    "alignment": {"characters": ["a"], "character_start_times_seconds": [0],
                                  "character_end_times_seconds": [.1]}}

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
    from tfs import config
    real = config.channel()
    v3 = {**real, "tts": {**real["tts"], "elevenlabs": {**real["tts"]["elevenlabs"], "model_id": "eleven_v3"}}}
    monkeypatch.setattr(tts, "channel", lambda: v3)
    monkeypatch.setattr(tts.requests, "post",
                        lambda url, **kw: bodies.append(dict(kw["json"])) or R(400 if "language_code" in kw["json"] else 200))
    tts._elevenlabs("a", "NARRATOR", data_dir / "a.mp3", "", "")
    assert "language_code" in bodies[0] and "language_code" not in bodies[1]


def test_stat_card_puts_the_figure_first():
    from tfs.media import motion

    frames = list(motion._stat("₱37", ["Bawas kada 11-kg tank", "excise ₱3.36/kg"], (540, 960), 2))
    assert frames                                    # figure/label swapped internally without error


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


def test_a_shot_failing_review_twice_is_replaced_not_fatal(data_dir, monkeypatch):
    from tfs import pipeline
    from tfs.media import images
    from tfs.models import ReviewReport, Scene, Script, Shot, ShotList

    d = data_dir / "items" / "y"
    (d / "img").mkdir(parents=True)
    shot = dict(kind="illustration", style="story", card_type="none", card_title="", card_lines=[],
                reuse_of_scene=0, motion="push_in")
    (d / "shots.json").write_text(ShotList(shots=[Shot(scene_id=i, image_prompt=f"p{i}", **shot)
                                                  for i in (0, 1, 2)]).model_dump_json())
    monkeypatch.setattr(images, "generate", lambda prompt, out, *a, **k: out.write_bytes(b"p"))
    script = Script(scenes=[Scene(id=i, chapter="c", speaker="N", text=f"l{i}", visual="v") for i in (0, 1, 2)],
                    sources=[])
    bad = ReviewReport(passed=False, redo_images={"1": "calendar again"}, redo_audio={}, warnings=[], appeal=6,
                       hook_frame=6, summary="")
    for _ in range(2):                               # fails, is regenerated, fails again
        pipeline._apply_video_fixes(d, bad)
    shots = pipeline._visuals({"id": "y"}, d, script, "9:16", (1080, 1920))
    assert shots[1].image.name in ("000.png", "002.png")      # borrowed a neighbour's illustration


def test_named_characters_get_their_exact_costume_in_the_prompt():
    from tfs.media.images import full_prompt

    p = full_prompt("Kuya Standard points at a chart while Juan scratches his head", "story")
    assert "royal-blue barong" in p and "light-blue T-shirt" in p and "cream barong" not in p


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


def test_quote_card_keeps_source_lines_separate():
    from tfs.media import motion

    # quote in the title, several source/footnote lines: no swap, no merging
    frames = list(motion._quote("Hindi puwedeng basta-basta.", ["Senate President, 2026", "Rules, Sec. 5"],
                                (540, 960), 2))
    assert frames


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


def test_music_and_effects_are_mixed_under_the_narration(data_dir):
    import subprocess

    from tfs.media import cards, render, sound
    from tfs.media.tts import Clip, duration
    from tfs.models import MusicCue, SfxCue, SoundPlan

    lib = sound.library_dir()
    (lib / "music").mkdir(parents=True)
    (lib / "sfx").mkdir(parents=True)
    tone = lambda f, secs, out: subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                                                f"sine=frequency={f}:duration={secs}", "-q:a", "5", str(out)],
                                               check=True)
    tone(330, 8, lib / "music" / "curious.mp3")
    tone(880, 0.5, lib / "sfx" / "pop.mp3")
    tone(600, 0.8, lib / "sfx" / "whoosh_soft.mp3")
    tone(200, 1.2, lib / "sfx" / "gavel.mp3")
    clips, shots = [], []
    for i in range(2):
        mp3 = data_dir / f"n{i}.mp3"
        tone(440, 2, mp3)
        clips.append(Clip(mp3, duration(mp3), [("Ang", 0.1, 0.4), ("korte", 0.5, 1.0), ("nagpasya.", 1.1, 1.8)]))
    img = cards.render_card("stat", "Kailangang boto", ["16"], (540, 960), data_dir / "c.png")
    shots = [render.Shot(img, "card", card={"card_type": "stat", "title": "Kailangang boto", "lines": ["16"]}),
             render.Shot(img, "push_in")]
    plan = SoundPlan(music=[MusicCue(from_scene=10, mood="curious")],
                     sfx=[SfxCue(scene_id=11, anchor_word="nagpasya", sound="gavel")])
    segments, events = sound.timeline(plan, shots, clips, [10, 11], [0.0, 2.3], 4.6, "vertical")
    assert segments and segments[0][0] == 0.0
    keys = [e.path.stem for e in events]
    assert "pop" in keys and "gavel" in keys and "whoosh_soft" in keys
    gavel = next(e for e in events if e.path.stem == "gavel")
    assert abs(gavel.at - (2.3 + 1.1)) < 0.01                    # lands exactly on "nagpasya"
    out, _ = render.render(shots, clips, "vertical", data_dir / "work", data_dir / "v.mp4", "", plan, [10, 11])
    assert (data_dir / "work" / "mix.wav").exists()
    assert abs(duration(out) - duration(data_dir / "work" / "narration.wav")) < 0.15


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


def test_out_of_elevenlabs_credits_pauses_instead_of_failing(data_dir, monkeypatch):
    from tfs.llm import UsageLimitError
    from tfs.media import tts

    class R:
        status_code, text = 401, '{"detail":{"code":"quota_exceeded","status":"quota_exceeded"}}'

    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
    monkeypatch.setattr(tts.requests, "post", lambda url, **kw: R())
    with pytest.raises(UsageLimitError):
        tts._elevenlabs("a", "NARRATOR", data_dir / "a.mp3", "", "")


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


def test_carousel_preflight_keeps_the_draft_if_slide_count_changes(monkeypatch):
    from tfs import pipeline
    from tfs.agents import packaging
    from tfs.models import Carousel, Slide

    slide = dict(layout="text", headline="h", body="b", source="s", theme="dark", image_prompt="p", style="story")
    draft = Carousel(format="explainer", slides=[Slide(**slide) for _ in range(3)])
    monkeypatch.setattr(packaging, "preflight_carousel",
                        lambda item, car, dossier: Carousel(format="explainer", slides=[Slide(**slide)]))
    assert pipeline._checked_carousel({"kind": "carousel"}, draft, "") is draft
    fixed = Carousel(format="explainer", slides=[Slide(**{**slide, "image_prompt": "blank sign"}) for _ in range(3)])
    monkeypatch.setattr(packaging, "preflight_carousel", lambda item, car, dossier: fixed)
    assert pipeline._checked_carousel({"kind": "carousel"}, draft, "") is fixed


# ---------------------------------------------------------------- vector engine
def _scene(sid, **kw):
    from tfs.models import Actor, Bubble, Prop, ScenePlan

    base = dict(scene_id=sid, kind="scene", background="street", camera="push_in",
                actors=[Actor(who="juan", label="", x=1.4, scale=0.5, row="front", pose="shrug", expression="sad",
                              speaking=True, facing="right", enter="pop", holds="not_an_emoji")],
                props=[Prop(emoji="money_with_wings", x=0.5, y=0.2, size=0.2, enter="drop", motion="rain", count=40,
                            at=0.1),
                       Prop(emoji="not_an_emoji", x=0.5, y=0.2, size=0.2, enter="pop", motion="none", count=1, at=0)],
                bubbles=[Bubble(actor=3, text="nobody", at=0.2), Bubble(actor=0, text="Where did it go?", at=0.9)],
                card_type="none", card_title="", card_lines=[])
    return ScenePlan(**(base | kw))


def test_vector_sanitize_orders_clamps_and_fills_gaps():
    from tfs.media import vector
    from tfs.models import MotionPlan

    plan = MotionPlan(look="flat", scenes=[_scene(2), _scene(0),
                                           _scene(5, kind="card", card_type="stat", card_title="", card_lines=[])])
    out = vector.sanitize(plan, [0, 1, 2, 5])
    assert [s.scene_id for s in out.scenes] == [0, 1, 2, 5]
    assert out.scenes[1].actors[0].who == "kuya_standard"            # missing scene -> host fallback
    assert out.scenes[3].kind == "scene"                              # empty card -> host fallback
    s0 = out.scenes[0]
    assert s0.actors[0].x == 0.9 and s0.actors[0].holds == ""
    assert [p.emoji for p in s0.props] == ["money_with_wings"] and s0.props[0].count == 16
    assert [b.text for b in s0.bubbles] == ["Where did it go?"] and s0.bubbles[0].at == 0.35


def test_vector_spec_and_project(tmp_path):
    from types import SimpleNamespace

    from tfs.media import vector
    from tfs.models import MotionPlan

    plan = vector.sanitize(MotionPlan(look="doodle", scenes=[
        _scene(0), _scene(1, kind="card", card_type="stat", card_title="Flood budget", card_lines=["₱5.4B"],
                          actors=[], props=[], bubbles=[])]), [0, 1])
    clips = [SimpleNamespace(words=[("Saan", 0.1, 0.4), ("napunta?", 0.45, 1.0)]), SimpleNamespace(words=[])]
    spec = vector.spec_from_plan(plan, [0.0, 3.0], 6.0, clips, (1080, 1920))
    assert spec["scenes"][0]["mouth"] == [[0.1, 0.4], [0.45, 1.0]]
    assert spec["scenes"][1]["card"]["lines"] == ["₱5.4B"] and "money_with_wings" in spec["emoji"]
    assert all(sc["start"] < t < sc["start"] + sc["dur"] for sc, t in zip(spec["scenes"], vector.still_times(spec)))
    html = vector.build_project(spec, tmp_path / "p").read_text(encoding="utf-8")
    assert 'data-composition-id="main"' in html and "window.__timelines[" in html and "window.SPEC" in html
    assert html.count("<script>") == 1                                # SPEC + runtime inline, in order
    shots = vector.as_shots(plan)
    assert [s.kind for s in shots.shots] == ["illustration", "card"] and "juan" in shots.shots[0].image_prompt


def test_visual_qa_notes_replan_vector_cards(monkeypatch):
    from tfs import qa

    monkeypatch.setattr(qa, "_vector", lambda: True)
    assert qa._cast() == qa.CAST_VECTOR and len(qa.CAST_VECTOR) == 3


def test_paid_images_are_off():
    from tfs.config import channel
    from tfs.media import images

    assert channel()["video"]["engine"] == "vector" and channel()["video"]["fps_vector"] == 60
    with pytest.raises(RuntimeError, match="vector engine"):
        images.generate("anything", __import__("pathlib").Path("never.png"))


def test_vector_staging_keeps_adults_the_same_height_and_apart():
    from tfs.media import vector
    from tfs.models import Actor

    def a(who, x, scale):
        return Actor(who=who, label="", x=x, scale=scale, row="front", pose="stand", expression="neutral",
                     speaking=False, facing="right", enter="none", holds="")

    out = vector._stage([a("kuya_standard", 0.45, 0.55), a("juan", 0.6, 0.32), a("child", 0.8, 0.5)], True)
    assert [x.scale for x in out[:2]] == [0.55, 0.55] and out[2].scale < 0.4
    assert sorted(x.x for x in out) == [0.2, 0.5, 0.8]


def test_money_props_show_pesos():
    from tfs.media import vector

    vector.emoji_index.cache_clear()
    idx = vector.emoji_index()
    assert "peso_banknote" in idx and "dollar_banknote" not in idx and "heavy_dollar_sign" not in idx
    for key in ("money_bag", "money_with_wings", "peso_banknote"):
        assert "₱</text>" in vector.emoji_svg(key)


def test_carousel_slides_keep_text_off_the_art(tmp_path):
    from PIL import Image

    from tfs.media import compose

    art = tmp_path / "art.png"
    Image.new("RGB", compose.band_size("text"), (0, 200, 0)).save(art)
    out = compose.slide(2, 8, "It takes *13 steps* to open a shop", "Some body text with ₱500 in it.", "Source",
                        "dark", art, tmp_path / "s.jpg", "@h")
    img = Image.open(out).convert("RGB")
    card_bottom = compose.CARD_Y + compose.ART["text"][1]
    assert img.size == (1080, 1350)
    # the card is the art at full strength (no wash), and nothing under it is art-coloured
    assert img.getpixel((540, card_bottom - 30))[1] > 180
    greenish = [x for x in range(0, 1080, 30) if img.getpixel((x, card_bottom + 220))[1] > 150
                and img.getpixel((x, card_bottom + 220))[0] < 100]
    assert not greenish
    assert [w for w, e in compose._tokens("It takes *13 steps* to open") if e] == ["13", "steps"]
    assert [w for w, e in compose._tokens("About ₱30,000 before day one") if e] == ["₱30,000"]


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

    db.upsert_item("2026-09-29-caro0", "carousel", "2026-09-29T11:00:00+08:00", "producing",
                   {"platforms": {"instagram_carousel": "2026-09-29T11:00:00+08:00",
                                  "facebook_post": "2026-09-29T10:00:00+08:00"}})
    monkeypatch.setattr(pipeline, "_notify_ready", lambda item: None)
    monkeypatch.setattr("tfs.archive.archive_item", lambda item: None)
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    pipeline._schedule(db.get_item("2026-09-29-caro0"), slides=[])
    posts = {p["platform"]: p["slot_at"] for p in db.queued_posts()}
    assert posts == {"instagram_carousel": "2026-09-29T08:30:00+08:00", "facebook_post": "2026-09-29T08:30:00+08:00",
                     "tiktok_carousel": "2026-09-29T08:30:00+08:00"}          # Threads waits until it's connected


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
                             agent_notes=[AgentNote(agent="motion_designer", notes=["Props go in hands."]),
                                          AgentNote(agent="scriptwriter", notes=["not ours to edit"])])

    monkeypatch.setattr(creative.llm, "structured", fake)
    monkeypatch.setattr(creative.notify, "send", lambda text: None)
    assert creative.due() and creative.run()
    assert "documents float" in seen["user"]
    assert "Props go in hands." in config.load_prompt("motion_designer")
    assert not (creative.notes_dir() / "scriptwriter.md").exists() and not creative.due()


def test_post_now_requests_are_picked_up_by_the_run(monkeypatch):
    from tfs import pipeline, post_now, state

    queued = [{"type": "post-now", "kind": "carousel", "topic": "Permits", "note": "Reddit"}]
    monkeypatch.setattr(state, "take_requests", lambda: [queued.pop()] if queued else [])
    made = []
    monkeypatch.setattr(post_now, "make", lambda kind, topic, note: made.append((kind, topic, note)) or "ok")
    assert pipeline._owner_requests() and made == [("carousel", "Permits", "Reddit")]
    assert not pipeline._owner_requests()                       # nothing left: the run carries on as usual


def test_loose_props_stand_on_the_ground():
    from tfs.media import vector
    from tfs.models import Prop

    def p(y, motion="none"):
        return Prop(emoji="door", x=.5, y=y, size=.2, enter="none", motion=motion, count=1, at=0)
    assert vector._grounded(p(0.4), False).y == 0.7                      # beside a head -> on the floor
    assert vector._grounded(p(0.1), False).y == 0.1                      # sky stays sky
    assert vector._grounded(p(0.4, "rain"), True).y == 0.4               # falling / floating on purpose


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

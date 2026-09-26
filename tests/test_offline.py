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


@pytest.mark.parametrize("model,expected", [("eleven_v3", "tl"), ("eleven_multilingual_v2", None)])
def test_narrator_is_told_the_text_is_filipino(data_dir, monkeypatch, model, expected):
    import base64

    from tfs import config
    from tfs.media import tts

    sent = {}

    class R:
        def raise_for_status(self):
            pass

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

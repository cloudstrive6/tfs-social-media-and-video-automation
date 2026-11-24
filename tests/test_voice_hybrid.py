"""Local GPU first, Modal as fallback (Bryce, 2026-11-24), offline: queue posting, deferral, local takes, deadline."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tfs.media import tts_voxcpm as vx
from tfs.media import voice_queue as vq


@dataclass
class Sc:
    id: int
    text: str


SCENES = [Sc(1, "Anim na taon ang termino."), Sc(2, "Walang re-election.")]


@pytest.fixture
def hybrid(monkeypatch, tmp_path):
    cfg = {"tts": {"voxcpm": {"mode": "hybrid", "takes": 1, "threshold": 0.85}}}
    monkeypatch.setattr(vx, "channel", lambda: cfg)
    queue = {"job": None, "posted": 0, "cleaned": 0, "done": {}}
    monkeypatch.setattr(vq, "enabled", lambda: True)
    monkeypatch.setattr(vq, "get_job", lambda item: queue["job"])

    def post(item, lines, seed, deadline, posted):
        queue["job"] = {"item": item, "lines": lines}
        queue["posted"] += 1
    monkeypatch.setattr(vq, "post", post)
    monkeypatch.setattr(vq, "fetch_done", lambda item, sids, dest: {s: p for s, p in queue["done"].items() if s in sids})
    monkeypatch.setattr(vq, "cleanup", lambda item: queue.__setitem__("cleaned", queue["cleaned"] + 1))
    calls = []
    monkeypatch.setattr(vx, "synthesize_scenes", lambda texts, out_dir, ids=None, takes=1: calls.append(
        [i for i, sid in enumerate(ids) if not (out_dir / f"{sid:03d}.json").exists()]) or [])

    def score(text, data, tmp, tag):
        p = tmp / f"{tag}.wav"
        p.write_bytes(data)
        return {"path": p, "dur": 1.0, "heard": text if data == b"good" else "mali", "words": [(w, 0.1, 0.2) for w in text.split()],
                "match": 1.0 if data == b"good" else 0.2}
    monkeypatch.setattr(vx, "score_take", score)
    monkeypatch.setattr(vx, "_encode", lambda wav, mp3: (mp3.write_bytes(wav.read_bytes()), 1.0)[1])
    return queue, calls, tmp_path


def test_no_local_audio_yet_posts_once_and_waits(hybrid):
    queue, calls, tmp = hybrid
    later = datetime.now(timezone.utc) + timedelta(hours=5)
    for _ in range(2):
        with pytest.raises(vx.VoiceDeferred):
            vx.synthesize(SCENES, tmp / "audio", item="2026-12-01-vert0", deadline=later)
    assert queue["posted"] == 1 and [l[0] for l in queue["job"]["lines"]] == [1, 2] and calls == []


def test_local_takes_are_used_and_modal_is_not(hybrid):
    queue, calls, tmp = hybrid
    for sid in (1, 2):
        w = tmp / f"local{sid}.wav"
        w.write_bytes(b"good")
        queue["done"][sid] = w
    vx.synthesize(SCENES, tmp / "audio", item="i", deadline=datetime.now(timezone.utc) + timedelta(hours=5))
    meta = json.loads((tmp / "audio" / "001.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "voxcpm-local" and queue["cleaned"] == 1 and calls == [[]]       # nothing left for Modal


def test_a_bad_local_take_goes_to_modal_without_waiting(hybrid):
    queue, calls, tmp = hybrid
    good, bad = tmp / "g.wav", tmp / "b.wav"
    good.write_bytes(b"good")
    bad.write_bytes(b"bad")
    queue["done"] = {1: good, 2: bad}
    vx.synthesize(SCENES, tmp / "audio", item="i", deadline=datetime.now(timezone.utc) + timedelta(hours=5))
    assert calls == [[1]]                                     # only scene 2 (index 1) goes to Modal


def test_deadline_passed_means_modal(hybrid):
    queue, calls, tmp = hybrid
    vx.synthesize(SCENES, tmp / "audio", item="i", deadline=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert calls == [[0, 1]] and queue["posted"] == 0


def test_a_waiting_item_does_not_block_the_queue(monkeypatch):
    from tfs import pipeline

    items = [{"id": "a", "kind": "vertical"}, {"id": "b", "kind": "vertical"}]
    monkeypatch.setattr(pipeline.db, "last_scout_at", lambda: datetime.now(timezone.utc).isoformat())
    monkeypatch.setattr(pipeline, "now", lambda: datetime.now(timezone.utc))
    monkeypatch.setattr(pipeline, "plan_upcoming", lambda: [])
    monkeypatch.setattr(pipeline, "expire_stale", lambda: None)
    monkeypatch.setattr(pipeline, "paused_kinds", lambda: set())
    monkeypatch.setattr(pipeline.db, "items_with_status", lambda *s: items)
    seen = []
    monkeypatch.setattr(pipeline, "produce", lambda i: seen.append(i) or i == "b")
    pipeline.tick(max_produce=1)
    assert seen == ["a", "b"]

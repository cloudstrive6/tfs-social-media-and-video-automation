"""Local narration worker (tools/voice_worker.py), offline: deadlines, the GPU slot handshake, batching, release."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tfs.config import ROOT

spec = importlib.util.spec_from_file_location("voice_worker", ROOT / "tools" / "voice_worker.py")
vw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vw)


def _job(item, minutes, n=2):
    return {"item": item, "seed": 19, "deadline": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(),
            "lines": [{"id": i + 1, "text": "Anim na taon ang termino ng presidente."} for i in range(n)]}


def test_pending_leaves_close_deadlines_to_modal(monkeypatch):
    monkeypatch.setattr(vw.vq, "list_jobs", lambda: [_job("late", 10), _job("b", 300), _job("a", 120)])
    assert [j["item"] for j in vw.pending(datetime.now(timezone.utc))] == ["a", "b"]


def test_slot_granted_by_render_then_released(tmp_path, monkeypatch):
    monkeypatch.setattr(vw, "REQUEST", tmp_path / "requests" / "tfs-voice.json")
    monkeypatch.setattr(vw, "GRANTED", tmp_path / "granted" / "tfs-voice")
    monkeypatch.setattr(vw, "gpu_in_use", lambda: True)
    sleeps = []

    def sleep(s):                                          # the render grants at its next batch boundary
        sleeps.append(s)
        vw.GRANTED.write_text("ok")
    monkeypatch.setattr(vw.time, "sleep", sleep)
    assert vw.wait_for_slot([_job("a", 120)]) is True and len(sleeps) == 1
    req = json.loads(vw.REQUEST.read_text(encoding="utf-8"))
    assert req["needs_commit_gb"] == 25.0 and req["need_minutes"] >= 5
    vw.release()
    assert not vw.REQUEST.exists() and not vw.GRANTED.exists()


def test_free_gpu_needs_no_grant(tmp_path, monkeypatch):
    monkeypatch.setattr(vw, "REQUEST", tmp_path / "r.json")
    monkeypatch.setattr(vw, "GRANTED", tmp_path / "g")
    monkeypatch.setattr(vw, "gpu_in_use", lambda: False)
    assert vw.wait_for_slot([_job("a", 120)]) is True


def test_low_commit_releases_and_leaves_it_to_modal(tmp_path, monkeypatch):
    monkeypatch.setattr(vw, "REQUEST", tmp_path / "r.json")
    monkeypatch.setattr(vw, "GRANTED", tmp_path / "g")
    monkeypatch.setattr(vw.vq, "list_jobs", lambda: [_job("a", 120)])
    monkeypatch.setattr(vw, "gpu_in_use", lambda: False)
    monkeypatch.setattr(vw, "free_commit_gb", lambda: 12.0)
    ran = []
    monkeypatch.setattr(vw, "narrate", lambda jobs: ran.append(jobs))
    vw.once()
    assert ran == [] and not vw.REQUEST.exists()


def test_narrate_batches_jobs_and_uploads(tmp_path, monkeypatch):
    up, finished = [], []
    monkeypatch.setattr(vw.vq, "put_done", lambda item, sid, wav: up.append((item, sid, wav.name)))
    monkeypatch.setattr(vw.vq, "finish_job", lambda item: finished.append(item))

    class Res:
        returncode, stdout, stderr = 0, '{"done": 3}', ""

    def run(cmd, **k):
        job = json.loads(Path(cmd[3]).read_text(encoding="utf-8"))
        out = Path(cmd[4])
        out.mkdir()
        for line in job["lines"]:
            (out / line["file"]).write_bytes(b"RIFF")
        return Res()
    monkeypatch.setattr(vw.subprocess, "run", run)
    vw.narrate([_job("a", 120, 2), _job("b", 200, 1)])
    assert up == [("a", 1, "00_001.wav"), ("a", 2, "00_002.wav"), ("b", 1, "01_001.wav")] and finished == ["a", "b"]

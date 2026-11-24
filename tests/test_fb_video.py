"""Facebook long-form upload (style v2 cadence), offline: resumable start, chunked transfer, finish, de-duplication."""
from tfs.publish import meta


class R:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def test_fb_video_resumable_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("META_PAGE_ID", "123")
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", "x")
    monkeypatch.setattr(meta, "CHUNK", 4)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0123456789")
    calls = []

    def post(url, data=None, files=None, timeout=None):
        calls.append((data["upload_phase"], data.get("start_offset"), len(files["video_file_chunk"][1]) if files else 0))
        assert "graph-video.facebook.com" in url and url.endswith("/123/videos")
        if data["upload_phase"] == "start":
            return R({"upload_session_id": "s1", "video_id": "v1", "start_offset": "0", "end_offset": "4"})
        if data["upload_phase"] == "transfer":
            nxt = int(data["start_offset"]) + 4
            return R({"start_offset": str(min(nxt, 10)), "end_offset": str(min(nxt + 4, 10))})
        assert data["title"] == "Built to Fail" and data["published"] == "true"
        return R({"success": True})

    monkeypatch.setattr(meta.requests, "post", post)
    monkeypatch.setattr(meta, "_call", lambda *a, **k: {"data": []})
    assert meta.fb_video(video, "Built to Fail", "desc") == "v1"
    assert calls == [("start", None, 0), ("transfer", "0", 4), ("transfer", "4", 4), ("transfer", "8", 2),
                     ("finish", None, 0)]


def test_fb_video_returns_existing_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("META_PAGE_ID", "123")
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", "x")
    import time
    from datetime import datetime, timezone
    made = datetime.fromtimestamp(time.time() - 600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
    monkeypatch.setattr(meta, "_call", lambda *a, **k: {"data": [{"id": "old", "title": "Built to Fail", "created_time": made}]})
    monkeypatch.setattr(meta.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no upload")))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    assert meta.fb_video(video, "Built to Fail", "d") == "old"

"""Final renders to the shared studio archive on B2 (Bryce, 2026-11-24), offline with a fake S3."""
import json

from tfs import render_archive as ra


class FakeS3:
    def __init__(self):
        self.objects = {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"ContentLength": len(self.objects[Key])}

    def upload_file(self, path, bucket, key):
        self.objects[key] = open(path, "rb").read()

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body


def _env(monkeypatch, on=True):
    vals = {"B2_ARCHIVE_KEY_ID": "k", "B2_ARCHIVE_APP_KEY": "s", "B2_ARCHIVE_BUCKET": "studio-render-archive",
            "B2_ENDPOINT": "https://s3.example"} if on else {}
    monkeypatch.setattr(ra, "env", lambda k, d="": vals.get(k, d))


def test_layout_sidecar_and_repeat(tmp_path, monkeypatch):
    _env(monkeypatch)
    s3 = FakeS3()
    monkeypatch.setattr(ra, "_client", lambda: s3)
    video, thumb = tmp_path / "video.mp4", tmp_path / "thumbnail.jpg"
    video.write_bytes(b"x" * 100)
    thumb.write_bytes(b"j")
    item = {"id": "2026-12-01-long0", "kind": "long_form", "anchor_at": "2026-12-01T19:15:00+08:00",
            "data": {"title": "Built to Fail", "platforms": {"youtube": "2026-12-01T19:15:00+08:00"}}}
    rec = ra.archive_render(item, video, thumb)
    assert rec["key"] == "tfs/longform/2026-12/2026-12-01-long0.mp4"
    assert set(s3.objects) == {rec["key"], rec["key"] + ".json", "tfs/longform/2026-12/2026-12-01-long0__thumbnail.jpg"}
    side = json.loads(s3.objects[rec["key"] + ".json"])
    assert side["bytes"] == 100 and len(side["sha1"]) == 40 and side["title"] == "Built to Fail" and side["channel"] == "tfs"
    assert ra.archive_render(item, video, thumb)["skipped"] == "already archived"
    short = dict(item, id="2026-12-01-vert0", kind="vertical")
    assert ra.archive_render(short, video)["key"] == "tfs/shorts/2026-12/2026-12-01-vert0.mp4"


def test_off_without_the_key_and_never_raises(tmp_path, monkeypatch):
    _env(monkeypatch, on=False)
    assert not ra.enabled() and ra.archive_render({"id": "a", "kind": "vertical"}, tmp_path / "v.mp4") is None
    _env(monkeypatch)
    monkeypatch.setattr(ra, "_client", lambda: (_ for _ in ()).throw(RuntimeError("B2 down")))
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    assert ra.archive_item({"id": "a", "kind": "vertical", "data": {"video": str(v)}}) is None

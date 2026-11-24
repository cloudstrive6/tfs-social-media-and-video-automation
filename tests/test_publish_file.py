"""One-off publish of an approved video (publish_file.py), offline: every platform tried, failures isolated."""
import json

from tfs import publish_file as pf


class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def download_file(self, bucket, key, path):
        open(path, "wb").write(self.objects[key])

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body


def test_publishes_each_platform_and_isolates_failures(monkeypatch):
    post = {"title": "T", "youtube_description": "d", "tags": ["a"], "facebook": "f", "instagram": "i", "tiktok": "t"}
    s3 = FakeS3({"publish/x/video.mp4": b"v", "publish/x/post.json": json.dumps(post).encode()})
    monkeypatch.setattr(pf.state, "_s3", lambda: s3)
    monkeypatch.setattr(pf.state, "_bucket", lambda: "b")
    sent = []
    monkeypatch.setattr(pf.notify, "send", lambda text: sent.append(text))

    def fake_post(platform, video, p):
        if platform == "instagram_reel":
            raise RuntimeError("Graph API: media not ready")
        return f"id-{platform}", f"https://example/{platform}"
    monkeypatch.setattr(pf, "_post", fake_post)
    res = pf.run("publish/x")
    assert [k for k, v in res.items() if v["ok"]] == ["youtube_shorts", "facebook_reel", "tiktok"]
    assert res["instagram_reel"]["ok"] is False and "not ready" in res["instagram_reel"]["error"]
    assert json.loads(s3.objects["publish/x/result.json"]) == res
    assert "🟢 youtube_shorts" in sent[0] and "❌ instagram_reel" in sent[0]

"""Instagram goes out through Post for Me's Quickstart project since 2026-11-27 (Bryce: "TFS IG content will be
published via PostForMe"); the Meta Graph API route stays in the code for when the Page link comes back."""
from __future__ import annotations

from pathlib import Path

from tfs.config import channel
from tfs.publish import postforme


def test_instagram_routes_to_postforme():
    over = channel()["publishing"]["overrides"]
    assert over["instagram_reel"] == "postforme" and over["instagram_carousel"] == "postforme"


def test_instagram_uses_the_quickstart_key(monkeypatch):
    monkeypatch.delenv("POSTFORME_API_KEY_INSTAGRAM", raising=False)
    monkeypatch.setenv("POSTFORME_API_KEY_TIKTOK", "quick")
    monkeypatch.setenv("POSTFORME_API_KEY", "white-label")
    assert postforme._key("instagram") == "quick"
    assert postforme._key("facebook") == "white-label"
    monkeypatch.setenv("POSTFORME_API_KEY_INSTAGRAM", "own")
    assert postforme._key("instagram") == "own"


def test_account_prefers_the_tfs_handle(monkeypatch):
    postforme.account_id.cache_clear()
    monkeypatch.delenv("POSTFORME_ACCOUNT_INSTAGRAM", raising=False)
    data = [{"id": "a", "status": "connected", "username": "someone_else"},
            {"id": "b", "status": "disconnected", "username": "thefilipinostandard"},
            {"id": "c", "status": "connected", "username": "The Filipino Standard", "external_id": ""}]
    monkeypatch.setattr(postforme, "_call", lambda *a, **k: {"data": data})
    assert postforme.account_id("instagram") == "c"
    postforme.account_id.cache_clear()


def test_publish_file_sends_instagram_to_postforme(monkeypatch, tmp_path):
    from tfs import publish_file
    sent = {}
    monkeypatch.setattr(postforme, "create_post", lambda key, caption, media, slot, **k: sent.update(
        key=key, caption=caption, media=media) or "pfm_1")
    from tfs.publish import meta
    monkeypatch.setattr(meta, "ig_reel", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Graph API used")))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    rid, link = publish_file._post("instagram_reel", video, {"instagram": "cap"})
    assert rid == "pfm_1" and sent["key"] == "instagram_reel" and sent["media"] == [Path(video)]

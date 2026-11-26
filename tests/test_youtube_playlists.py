"""YouTube playlist mapping and the never-raise publish hook."""
from tfs.publish import youtube_playlists as yp


def test_mapping_by_format_and_pillar():
    assert yp.keys_for("long_form", "how_it_works") == ["built_to_fail"]
    assert yp.keys_for("vertical", "how_it_works") == ["know_your_government"]
    assert yp.keys_for("vertical", "now_explained") == ["now_explained"]
    assert yp.keys_for("vertical", "myths_factchecks") == ["fact_check"]
    assert yp.keys_for("vertical", None) == ["now_explained"]          # unknown pillar -> default
    assert yp.keys_for("carousel", "how_it_works") == []               # not on YouTube


def test_every_rule_points_at_a_defined_playlist():
    cfg = yp.config()
    keys = set(cfg["playlists"])
    for rule in cfg["rules"].values():
        targets = rule if isinstance(rule, list) else [k for v in rule.values() for k in v]
        assert set(targets) <= keys


def test_hook_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("insufficient scope")
    monkeypatch.setattr(yp, "add", boom)
    assert yp.add_for("abc123", "vertical", "how_it_works") == []


def test_insert_retries_while_new_playlist_is_404(monkeypatch):
    import tfs.publish.youtube as yt
    tries = []

    class NotYet(Exception):
        resp = type("R", (), {"status": 404})()

    class Items:
        def insert(self, part, body):
            class Run:
                def execute(self_inner):
                    tries.append(1)
                    if len(tries) < 3:
                        raise NotYet()
                    return {}
            return Run()

    monkeypatch.setattr(yt, "api", lambda: type("A", (), {"playlistItems": lambda self: Items()})())
    yp._insert_item("PLnew", "v1", sleep=lambda s: None)
    assert len(tries) == 3


def test_add_skips_existing_and_creates_missing(monkeypatch):
    calls = []

    class Exec:
        def __init__(self, out=None):
            self.out = out or {}

        def execute(self):
            return self.out

    class Playlists:
        def insert(self, part, body):
            calls.append(("create", body["snippet"]["title"]))
            return Exec({"id": "PLnew"})

    class Items:
        def insert(self, part, body):
            calls.append(("add", body["snippet"]["playlistId"], body["snippet"]["resourceId"]["videoId"]))
            return Exec({})

    class Api:
        def playlists(self):
            return Playlists()

        def playlistItems(self):
            return Items()

    import tfs.publish.youtube as yt
    monkeypatch.setattr(yt, "api", lambda: Api())
    monkeypatch.setattr(yp, "contains", lambda pid, vid: pid == "PLkyg")
    have = {"Know Your Government": "PLkyg"}
    assert yp.add("v1", ["know_your_government"], have) == []                     # already there
    assert yp.add("v2", ["fact_check"], have) == ["Fact Check"]                   # created, then added
    assert ("create", "Fact Check") in calls and ("add", "PLnew", "v2") in calls

"""Offline tests for tfs.media.broll: Commons parsing, licence filter, credits, retry, licence log, grade."""
import email.message
import io
import json
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:             # works with or without the editable install
    sys.path.insert(0, str(ROOT / "src"))

from tfs.media import broll  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "broll"


def load(name):
    return json.loads((FIX / f"commons_{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setenv("TFS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(broll, "MIN_INTERVAL", 0.0)
    sleeps = []
    monkeypatch.setattr(broll, "_sleep", sleeps.append)

    def no_network(*a, **k):
        raise AssertionError("network used in an offline test")
    monkeypatch.setattr(broll, "_urlopen", no_network)
    yield sleeps


class FakeHTTP:
    """Serves queued responses; an int queues an HTTPError with that code (and the given Retry-After)."""

    def __init__(self, *responses, retry_after="7"):
        self.responses, self.retry_after, self.requests = list(responses), retry_after, []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        r = self.responses.pop(0)
        if isinstance(r, int):
            hdrs = email.message.Message()
            if self.retry_after is not None:
                hdrs["Retry-After"] = self.retry_after
            raise urllib.error.HTTPError(req.full_url, r, "error", hdrs, None)
        return io.BytesIO(r if isinstance(r, bytes) else json.dumps(r).encode("utf-8"))


# ---------------------------------------------------------------- search and parsing
def test_search_sends_required_params_and_user_agent(monkeypatch):
    fake = FakeHTTP(load("batasang_pambansa"))
    monkeypatch.setattr(broll, "_urlopen", fake)
    found = broll.search("Batasang Pambansa", limit=12)
    req = fake.requests[0]
    assert req.get_header("User-agent") == broll.USER_AGENT
    assert "TheFilipinoStandardBot/1.0" in broll.USER_AGENT and broll.USER_AGENT.endswith("python-urllib")
    q = req.full_url
    for part in ("action=query", "generator=search", "gsrnamespace=6", "prop=imageinfo",
                 "iiprop=url%7Csize%7Cmime%7Cextmetadata", "iiurlwidth=2000", "gsrsearch=Batasang+Pambansa"):
        assert part in q
    assert found and all(c.allowed for c in found)
    titles = [c.title for c in found]
    assert "Batasang pambansa session hall - 2022.jpg" in titles
    assert not any("composition.svg" in t for t in titles)              # BY-SA and SVG out
    assert not any("Batasan Hills" in t for t in titles)                # BY-SA out


def test_search_all_keeps_reasons(monkeypatch):
    monkeypatch.setattr(broll, "_urlopen", FakeHTTP(load("malacanang_palace")))
    found = broll.search("Malacanang Palace", allowed_only=False)
    assert len(found) == 12
    assert [c.title for c in found][0].startswith("Stamp of Indonesia")      # ordered by search index
    by = {c.title: c for c in found}
    facade = by["Malacanang Palace facade 1910.jpg"]
    assert facade.allowed and facade.author == "Unknown author"
    assert facade.credit_text == "Photo: Unknown author, Wikimedia Commons, Public domain"
    assert facade.government_origin                                       # sourced from malacanang.gov.ph
    assert "utm_" not in facade.direct_url and "utm_" not in facade.thumb_url
    assert facade.page_url == "https://commons.wikimedia.org/wiki/File:Malacanang_Palace_facade_1910.jpg"
    assert not by["Malacanang Palace 1898.jpg"].allowed                   # 553 px
    videos = [c for c in found if c.kind == "video"]
    assert len(videos) == 2 and not any(v.allowed for v in videos)       # RTVM footage = government moving footage
    assert all("government moving footage" in v.reason for v in videos)


def test_parse_real_fixture_credit_and_government():
    found = {c.title: c for c in broll.parse_response(load("batasang_pambansa"))}
    sona = found["2011 Philippine State of the Nation Address.jpg"]
    assert sona.allowed and sona.government_origin
    assert "<" not in sona.credit_text and sona.credit_text.startswith("Photo: Robert Vi")
    house = found["Batasang pambansa session hall - 2022.jpg"]
    assert broll.government_agency(house) == "House of Representatives of the Philippines"


SYNTH = {
    "Senate building CC BY 2.0.jpg": (True, "CC BY"),
    "EDSA traffic CC BY-NC.jpg": (False, "NC"),
    "Jeepney CC BY-ND.jpg": (False, "ND"),
    "Manila Bay GFDL.jpg": (False, "GFDL"),
    "News still fair use.jpg": (False, "fair use"),
    "No licence at all.jpg": (False, "missing licence"),
    "Small CC0.jpg": (False, "too small"),
    "Rizal Park scan.tif": (False, "JPEG or PNG"),
    "Quezon City Hall CC0.png": (True, "CC0"),
    "Pasig River timelapse.webm": (False, "BY-SA"),
    "Cebu skyline drone.webm": (True, "CC BY"),
    "Intramuros wall 1900.jpg": (True, "public domain"),
    "Schoolchildren at a flag ceremony.jpg": (True, "public domain"),
    "Legislative hall CC BY 3.0 PH.jpg": (True, "CC BY"),
    "Ambiguous attribution.jpg": (False, "not on the allowed list"),
}


def test_synthetic_accept_reject_table():
    found = {c.title: c for c in broll.parse_response(load("synthetic_edge_cases"), "test")}
    assert set(found) == set(SYNTH)
    for title, (ok, why) in SYNTH.items():
        c = found[title]
        assert c.allowed is ok, (title, c.reason)
        assert why.lower() in c.reason.lower(), (title, c.reason)
    drone = found["Cebu skyline drone.webm"]
    assert drone.kind == "video" and drone.duration == 24.5
    assert drone.credit_text == "Video: Drone Pilot, Wikimedia Commons, CC BY 4.0"
    ph = found["Legislative hall CC BY 3.0 PH.jpg"]
    assert ph.licence_url == "https://creativecommons.org/licenses/by/3.0/"          # derived when missing
    assert not ph.government_origin                                                   # "Pia" is a name, not PIA
    kids = found["Schoolchildren at a flag ceremony.jpg"]
    assert kids.government_origin and set(kids.hints) >= {"schoolchildren", "mga bata"}
    assert found["Intramuros wall 1900.jpg"].author == "Unknown author"
    assert found["Senate building CC BY 2.0.jpg"].author == "Lakad & Co"


@pytest.mark.parametrize("licence,ok", [
    ("Public domain", True), ("PD-US", True), ("PD-self", True), ("pd", True), ("CC0", True),
    ("CC0 1.0 Universal", True), ("CC BY 4.0", True), ("CC BY 2.0", True), ("CC BY 3.0 us", True), ("CC BY", True),
    ("CC BY-SA 4.0", False), ("CC BY-SA 3.0", False), ("CC BY-NC 2.0", False), ("CC BY-NC-SA 2.0", False),
    ("CC BY-ND 4.0", False), ("GFDL", False), ("GFDL 1.2", False), ("Fair use", False),
    ("Not licensed. Fair use (RA 8293 s.185; 17 USC 107)", False), ("", False), ("Attribution", False),
    ("No restrictions", False), ("Copyrighted free use", False),
])
def test_licence_ok_table(licence, ok):
    assert broll.licence_ok(licence)[0] is ok


def test_normalise_licence_from_code():
    assert broll.normalise_licence("", "cc-by-4.0") == "CC BY 4.0"
    assert broll.normalise_licence("", "cc-by-sa-3.0") == "CC BY-SA 3.0"
    assert broll.normalise_licence("", "pd") == "Public domain"
    assert broll.normalise_licence("", "cc-zero") == "CC0"


# ---------------------------------------------------------------- credits and policy helpers
@pytest.mark.parametrize("artist,expected", [
    ('Unknown author<span style="display: none;">Unknown author</span>', "Unknown author"),
    ("Unknown authorUnknown author", "Unknown author"),
    ('Anonymous<span style="display: none;">Unknown author</span>', "Unknown author"),
    ('<a href="//commons.wikimedia.org/wiki/User:Judgefloro" title="User:Judgefloro">Judgefloro</a>', "Judgefloro"),
    ("<bdi><a href='x'>National Historical Commission of the Philippines</a>\n</bdi>",
     "National Historical Commission of the Philippines"),
    ("", "Unknown author"),
])
def test_credit_text_formatting(artist, expected):
    assert broll.credit_text(artist, "Public domain") == f"Photo: {expected}, Wikimedia Commons, Public domain"
    assert broll.credit_text(artist, "CC BY 4.0", "video").startswith("Video: ")


@pytest.mark.parametrize("meta,gov", [
    ({"author": "Philippine News Agency photo by Avito Dalan"}, True),
    ({"author": "PNA"}, True),
    ({"author": "Senate of the Philippines"}, True),
    ({"author": "Philippine Supreme Court Public Information Office"}, True),
    ({"author": "Supreme Court PIO"}, True),
    ({"author": "Presidential Communications Office"}, True),
    ({"author": "PCO"}, True),
    ({"author": "Malacañang Palace"}, True),
    ({"Artist": {"value": "Radio Television Malacañang"}}, True),
    ({"author": "Someone", "credit": "https://www.senate.gov.ph/photo"}, True),
    ({"author": "Judgefloro"}, False),
    ({"author": "Pia Wurtzbach fan"}, False),
    ({"author": "Clerk of the House of Representatives and Parliamentary Service"}, False),   # NZ, not PH
    ({"author": "Wide Awake!", "subject": "Philippine Senate Session Hall"}, False),          # subject is not origin
])
def test_is_government_origin(meta, gov):
    assert broll.is_government_origin(meta) is gov


def test_minor_hints_word_boundaries():
    assert broll.minor_hints({"title": "Kids playing basketball in Tondo"}) == ["kids"]
    assert broll.minor_hints({"description": "Mga bata sa plaza"}) == ["mga bata"]
    assert broll.minor_hints({"title": "Batasang Pambansa", "description": "Batangas port"}) == []
    assert {"children", "kids", "students", "pupils", "bata"} <= set(broll.REJECT_HINTS)


# ---------------------------------------------------------------- HTTP retry
def test_retry_on_429_respects_retry_after(monkeypatch, offline):
    fake = FakeHTTP(429, 503, b"payload", retry_after="7")
    monkeypatch.setattr(broll, "_urlopen", fake)
    assert broll._get("https://example.org/x") == b"payload"
    assert offline == [7.0, 7.0] and len(fake.requests) == 3
    assert all(r.get_header("User-agent") == broll.USER_AGENT for r in fake.requests)


def test_retry_gives_up_after_three_tries(monkeypatch, offline):
    fake = FakeHTTP(429, 429, 429, 429, retry_after=None)
    monkeypatch.setattr(broll, "_urlopen", fake)
    with pytest.raises(urllib.error.HTTPError) as err:
        broll._get("https://example.org/x")
    assert err.value.code == 429 and len(fake.requests) == 3
    assert offline == [5.0, 10.0]                                        # exponential when no Retry-After


def test_no_retry_on_404_and_wait_is_capped(monkeypatch, offline):
    monkeypatch.setattr(broll, "_urlopen", FakeHTTP(404))
    with pytest.raises(urllib.error.HTTPError):
        broll._get("https://example.org/x")
    assert offline == []
    monkeypatch.setattr(broll, "_urlopen", FakeHTTP(429, b"ok", retry_after="9999"))
    assert broll._get("https://example.org/x") == b"ok" and offline == [broll.MAX_WAIT]


# ---------------------------------------------------------------- fetch
def test_fetch_photo_uses_thumbnail_and_refuses_disallowed(monkeypatch, tmp_path):
    found = {c.title: c for c in broll.parse_response(load("synthetic_edge_cases"))}
    fake = FakeHTTP(b"\xff\xd8jpegbytes", b"\x89PNGbytes", b"webmbytes")
    monkeypatch.setattr(broll, "_urlopen", fake)
    p = broll.fetch(found["Senate building CC BY 2.0.jpg"], tmp_path / "dl")
    assert p.name == "senate-building-cc-by-2-0.jpg" and p.read_bytes().startswith(b"\xff\xd8")
    assert "/thumb/" in fake.requests[0].full_url and "utm_" not in fake.requests[0].full_url
    png = broll.fetch(found["Quezon City Hall CC0.png"], tmp_path / "dl")
    assert png.suffix == ".png"
    vid = broll.fetch(found["Cebu skyline drone.webm"], tmp_path / "dl")
    assert vid.suffix == ".webm" and "/thumb/" not in fake.requests[2].full_url
    assert broll.fetch(found["Senate building CC BY 2.0.jpg"], tmp_path / "dl") == p   # cached, no request
    assert len(fake.requests) == 3
    with pytest.raises(ValueError):
        broll.fetch(found["EDSA traffic CC BY-NC.jpg"], tmp_path / "dl")


# ---------------------------------------------------------------- licence log
def test_licence_log_round_trip_and_check(tmp_path):
    found = {c.title: c for c in broll.parse_response(load("synthetic_edge_cases"), "senate building")}
    lg = broll.LicenceLog.for_item("2026-11-24-test")
    a = lg.add(found["Senate building CC BY 2.0.jpg"], tmp_path / "senate.jpg", subject="Senate exterior")
    b = lg.add(found["Schoolchildren at a flag ceremony.jpg"], "kids.jpg", asset_id="L2-01")
    assert a["id"] == "B001" and b["id"] == "L2-01"
    lg.mark_used("B001", "long_form", 12.4, 15.9, "SENATE")
    lg.mark_used("B001", "long_form", 12.4, 15.9, "SENATE")                       # no duplicate
    lg.mark_used("B001", "vertical", 3, 6.5)
    path = lg.save()
    assert path == tmp_path / "items" / "2026-11-24-test" / "licences.json"

    again = broll.LicenceLog(path.parent)
    row = again.get("B001")
    for key in ("id", "file", "kind", "subject", "query", "source_url", "direct_url", "licence", "licence_url",
                "author", "credit_text", "date_read", "status", "used_at"):
        assert key in row
    assert row["file"] == "senate.jpg" and row["subject"] == "Senate exterior" and row["query"] == "senate building"
    assert row["licence"] == "CC BY 2.0" and row["licence_url"].startswith("https://creativecommons.org/licenses/by/2.0")
    assert row["credit_text"] == "Photo: Lakad & Co, Wikimedia Commons, CC BY 2.0"
    assert len(row["date_read"]) == 10 and row["date_read"][4] == "-"
    assert row["used_at"] == [{"video": "long_form", "from_s": 12.4, "to_s": 15.9, "word": "SENATE"},
                              {"video": "vertical", "from_s": 3.0, "to_s": 6.5, "word": ""}]
    kids = again.get("L2-01")
    assert kids["government_origin"] and "Government-origin still" in kids["notes"] and "check by eye" in kids["notes"]
    assert again.check() == []

    again.upsert({"id": "B001", "status": "graded"})                                # update keeps used_at
    assert again.get("B001")["status"] == "graded" and len(again.get("B001")["used_at"]) == 2
    again.rows += [
        {"id": "X1", "licence": "", "credit_text": "c", "source_url": "u"},
        {"id": "X2", "licence": "CC BY-SA 4.0", "credit_text": "c", "source_url": "u"},
        {"id": "X3", "licence": "Public domain", "credit_text": " ", "source_url": "u"},
        {"id": "X4", "licence": "CC BY 4.0", "credit_text": "c", "source_url": "u"},
        {"id": "X5", "licence": "Not licensed. Fair use (RA 8293 s.185)", "credit_text": "c", "source_url": "u"},
        {"id": "X6", "kind": "video", "licence": "Public domain", "credit_text": "c", "source_url": "u",
         "government_origin": True},
    ]
    problems = again.check()
    assert "X1: missing licence" in problems
    assert any(p.startswith("X2: disallowed licence") for p in problems)
    assert "X3: missing credit" in problems
    assert "X4: CC BY without a licence URL" in problems
    assert any(p.startswith("X5: disallowed licence") for p in problems)
    assert any(p.startswith("X6: government moving footage") for p in problems)
    assert len(problems) == 6


def test_mark_used_unknown_id(tmp_path):
    with pytest.raises(KeyError):
        broll.LicenceLog(tmp_path).mark_used("nope", "v", 0, 1)


# ---------------------------------------------------------------- grade (needs ffmpeg)
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")


@needs_ffmpeg
def test_grade_photo_and_gate(tmp_path):
    src = tmp_path / "src.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=1",
                    "-frames:v", "1", str(src)], check=True)
    colour = broll.grade(src, tmp_path / "out.jpg", "photo")
    assert Path(colour["out"]).is_file() and colour["satavg"] is not None
    assert broll.SAT_MIN <= colour["saturation"] <= broll.SAT_MAX
    assert colour["satavg"] < colour["sat_before"]                     # a very saturated test card is pulled down
    bw = broll.grade(src, tmp_path / "bw.jpg", "photo", gate=True)
    assert bw["gate"] and bw["saturation"] is None and bw["satavg"] < 1.0


@needs_ffmpeg
def test_grade_video_to_60fps_1080p(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25",
                    "-t", "0.4", "-pix_fmt", "yuv420p", str(src)], check=True)
    res = broll.grade(src, tmp_path / "out.mp4", "video")
    assert res["satavg"] is not None
    if shutil.which("ffprobe"):
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height,r_frame_rate", "-of", "csv=p=0", res["out"]],
                               capture_output=True, text=True).stdout.strip()
        assert probe == "1920,1080,60/1"

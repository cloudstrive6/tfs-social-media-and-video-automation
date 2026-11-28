"""The revamp posting cadence (owner, 2026-11-24) as encoded in config/schedule.yaml and tfs.slots.

Source of truth: vault page wiki/answers/tfs-weekly-posting-schedule-2026-11.md (all times PHT).
The week tested is Monday 2026-11-30 to Sunday 2026-12-06, the first full week of the 4-week test.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml

MON = date(2026, 11, 30)
WEEK = [MON + timedelta(days=i) for i in range(7)]

S = ["07:30", "12:30"]
CAROUSEL_DAY = {"youtube_shorts": S + ["20:30"], "instagram_reel": S, "tiktok": S, "facebook_reel": S,
                "instagram_carousel": ["19:30"], "facebook_post": ["19:30"], "tiktok_carousel": ["19:30"],
                "threads_carousel": ["20:00"]}
LONG_DAY = {"youtube": ["19:15"], "facebook_video": ["19:15"], "youtube_shorts": S,
            "instagram_reel": S + ["21:00"], "tiktok": S + ["21:00"], "facebook_reel": S}
PLAIN_DAY = {p: S + ["20:30"] for p in ("youtube_shorts", "instagram_reel", "tiktok", "facebook_reel")}

# weekday -> (day type, {kind: units}, posts per platform with times)
TABLE = {
    0: ("carousel", {"vertical": 3, "carousel": 1}, CAROUSEL_DAY),
    1: ("long_form", {"long_form": 1, "vertical": 3}, LONG_DAY),
    2: ("carousel_single", {"vertical": 3, "carousel": 1}, CAROUSEL_DAY),
    3: ("long_form", {"long_form": 1, "vertical": 3}, LONG_DAY),
    4: ("carousel", {"vertical": 3, "carousel": 1}, CAROUSEL_DAY),
    5: ("long_form", {"long_form": 1, "vertical": 3}, LONG_DAY),
    6: ("plain", {"vertical": 3}, PLAIN_DAY),
}


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TFS_DATA_DIR", str(tmp_path))
    from tfs import slots
    monkeypatch.setattr(slots, "paused_kinds", lambda: set())       # the full table, whatever is on pause
    yield tmp_path


def _hhmm(posts):
    return {p: [t.strftime("%H:%M") for t in ts] for p, ts in posts.items()}


def _counts(units):
    out = {}
    for u in units:
        out[u.kind] = out.get(u.kind, 0) + 1
    return out


@pytest.mark.parametrize("d", WEEK, ids=lambda d: d.strftime("%a"))
def test_each_weekday_matches_the_table(d):
    from tfs import slots

    kind, units_expected, posts_expected = TABLE[d.weekday()]
    assert slots.day_type(d) == kind
    units = slots.day_units(d)
    assert _counts(units) == units_expected
    assert _hhmm(slots.day_posts(d)) == posts_expected
    assert all(t.tzinfo is not None and t.utcoffset() == timedelta(hours=8)
               for u in units for t in u.platforms.values())


def test_rule_counts_from_owners_cadence():
    from tfs import slots

    for d in WEEK:
        kind = slots.day_type(d)
        n = {p: len(ts) for p, ts in slots.day_posts(d).items()}
        carousel_day, long_day = kind.startswith("carousel"), kind == "long_form"
        assert n["youtube_shorts"] == (2 if long_day else 3)
        assert n["instagram_reel"] == n["tiktok"] == (2 if carousel_day else 3)
        assert n["facebook_reel"] == (2 if carousel_day or long_day else 3)
        assert n["tiktok"] + n.get("tiktok_carousel", 0) == 3                  # photo post counts toward 3 a day
        assert n.get("youtube", 0) == n.get("facebook_video", 0) == (1 if long_day else 0)
        assert n.get("threads_carousel", 0) == (1 if carousel_day else 0)


def test_weekly_totals_and_unique_items():
    from tfs import slots

    units = [u for d in WEEK for u in slots.day_units(d)]
    assert _counts(units) == {"long_form": 3, "vertical": 21, "carousel": 3}     # 27 items to make a week
    totals = {}
    for d in WEEK:
        for p, ts in slots.day_posts(d).items():
            totals[p] = totals.get(p, 0) + len(ts)
    assert totals == {"youtube": 3, "youtube_shorts": 18, "instagram_reel": 18, "instagram_carousel": 3,
                      "tiktok": 18, "tiktok_carousel": 3, "facebook_video": 3, "facebook_reel": 15,
                      "facebook_post": 3, "threads_carousel": 3}
    formats = [u.format for u in units if u.kind == "carousel"]
    assert formats == ["multi", "single", "multi"]                               # Mon, Wed, Fri


def test_config_goes_live_at_live_from():
    from datetime import datetime

    from tfs import config, slots

    sched = config.schedule()
    assert sched["live"] is True and sched["live_from"] == "2026-11-27T13:00:00+08:00"   # The owner said go, 2026-11-26
    assert not slots.is_live(sched, at=datetime.fromisoformat("2026-11-27T12:59:00+08:00"))
    assert slots.is_live(sched, at=datetime.fromisoformat("2026-11-27T13:00:00+08:00"))
    assert not slots.is_live({"live": False, "live_from": "2020-01-01T00:00:00+08:00"})
    assert "long_form" not in (sched.get("paused") or [])                       # unpaused, held by `live`
    assert slots.is_live({"slots": {}}) is True                                 # old configs keep running
    assert sched["platforms"]["carousel"] == ["instagram_carousel", "facebook_post", "tiktok_carousel",
                                              "threads_carousel"]               # post-now and samples use these


def test_pht_across_midnight():
    from tfs import slots
    from tfs.config import PHT

    vert0 = next(u for u in slots.day_units(MON) if u.id == "2026-11-30-vert0")
    assert vert0.anchor.astimezone(timezone.utc) == datetime(2026, 11, 29, 23, 30, tzinfo=timezone.utc)
    caro0 = slots.unit_by_id("2026-11-30-caro0")
    assert caro0.platforms["threads_carousel"].astimezone(timezone.utc) == datetime(2026, 11, 30, 12, 0,
                                                                                   tzinfo=timezone.utc)
    # 01:00 PHT Monday is still Sunday in UTC: the weekday comes from the PHT date
    pht_day = datetime(2026, 11, 29, 17, 0, tzinfo=timezone.utc).astimezone(PHT).date()
    assert pht_day == MON and slots.day_type(pht_day) == "carousel"


def test_override_shifts_units_and_keeps_offsets(data_dir):
    from tfs import config, slots

    (data_dir / "schedule_override.yaml").write_text(
        "slots: {vertical: ['08:30', '12:30', '23:30'], carousel: ['18:30'], long_form: ['09:00']}\n"
        "youtube_long: ['10:00']\n")
    assert config.schedule()["slots"]["long_form"] == ["09:00"]
    tue = slots.day_units(date(2026, 12, 1))
    assert {p: t.strftime("%H:%M") for p, t in tue[0].platforms.items()} == {"youtube": "09:00",
                                                                             "facebook_video": "09:00"}
    vert0 = slots.unit_by_id("2026-12-01-vert0")
    assert {t.strftime("%H:%M") for t in vert0.platforms.values()} == {"08:30"}
    vert2 = slots.unit_by_id("2026-12-01-vert2")                 # 21:00 + 3 h: rolls into Wednesday (PHT)
    assert set(vert2.platforms) == {"instagram_reel", "tiktok"}
    assert vert2.anchor.isoformat() == "2026-12-02T00:00:00+08:00"
    caro = slots.unit_by_id("2026-11-30-caro0")
    assert caro.platforms["instagram_carousel"].strftime("%H:%M") == "18:30"
    assert caro.platforms["threads_carousel"].strftime("%H:%M") == "19:00"    # Threads stays 30 min later


OLD_FORMAT = """
production_lead_hours: 6
paused: [long_form]
slots:
  long_form: ["21:00"]
  vertical: ["04:30", "12:30", "20:30"]
  carousel: ["08:30", "19:00"]
platforms:
  long_form: [youtube]
  vertical: [youtube_shorts, instagram_reel, facebook_reel, tiktok]
  carousel: [instagram_carousel, facebook_post, tiktok_carousel, threads_carousel]
daily_production:
  long_form: 1
  vertical: 3
  carousel: 2
"""


def test_old_format_config_still_parses():
    from tfs import slots

    old = yaml.safe_load(OLD_FORMAT)
    assert slots.day_type(MON, old) is None and slots.is_live(old)
    units = slots.day_units(date(2026, 9, 28), old)
    assert _counts(units) == {"long_form": 1, "vertical": 3, "carousel": 2}
    vert0 = next(u for u in units if u.id.endswith("vert0"))
    assert vert0.anchor.strftime("%H:%M") == "04:30" and len(set(vert0.platforms.values())) == 1
    caro0 = next(u for u in units if u.id.endswith("caro0"))
    assert set(caro0.platforms) == {"instagram_carousel", "facebook_post", "tiktok_carousel", "threads_carousel"}
    assert caro0.anchor.strftime("%H:%M") == "08:30"

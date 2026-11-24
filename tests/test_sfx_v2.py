"""Offline tests for the v2 sound design (tfs.media.sfx_v2): cue timing against the atlas.js animation beats,
cue spacing rules, reveal detection, the pad drop-out, the voice-over-SFX margin and determinism."""
import shutil

import numpy as np
import pytest

from tfs.media import sfx_v2 as sv

SR = sv.SR


def shot_list():
    """One of each cue-bearing shot, timed like a real chapter."""
    return [
        {"k": "title", "mat": True, "t0": 2.0, "t1": 5.0, "text": "THE LAW", "num": "01"},
        {"k": "doc", "t0": 5.0, "t1": 11.0, "head": "CONSTITUTION", "sec": "ART. VI", "body": "alpha beta gamma",
         "hl": ["alpha", "gamma"]},
        {"k": "cards", "t0": 11.0, "t1": 15.0, "items": [{"big": "12", "small": "seats"}, {"big": "0", "small": "won"}]},
        {"k": "broll", "t0": 15.0, "t1": 18.0, "src": "broll/manila.jpg", "kind": "photo"},
        {"k": "broll", "t0": 18.0, "t1": 22.0, "src": "broll/archive.mp4", "kind": "video", "gate": True},
        {"k": "broll", "t0": 22.0, "t1": 26.0, "src": "broll/hero.mp4", "kind": "video"},
    ]


def cue_times(cues, name):
    return [t for t, nm, _ in cues if nm == name]


@pytest.fixture(scope="module")
def built():
    return sv.build_cues(shot_list(), 27.0)


def test_cues_land_on_animation_beats(built):
    cues, track, reveals = built
    # title mat: riser peaks into the card, heavy slap as the card settles (atlas: card lands at t0)
    assert cue_times(cues, "riser") == [1.05]
    assert cue_times(cues, "card slap (heavy)") == [2.08]
    # doc: paper at t0, pen with the ring (atlas: t0 + 0.35), markers with each highlight
    # (atlas: t0 + 0.5 + i * max(0.8, (dur - 1.2) / n)); the first one overlaps the pen circle and is skipped
    assert cue_times(cues, "paper swish") == [5.0]
    assert cue_times(cues, "pen circle") == [5.35]
    assert cue_times(cues, "marker swipe") == [round(5.0 + 0.5 + 1 * max(0.8, (6.0 - 1.2) / 2), 2)]
    # cards: each card lands at t0 + i * max(0.5, (dur - 1) / n), the slap 0.05 s later
    assert cue_times(cues, "card slap") == [11.05, round(11.0 + max(0.5, 3.0 / 2) + 0.05, 2)]
    # broll: photo gets air just before the cut, archive gets the projector, hero gets the push
    assert cue_times(cues, "soft air") == [14.9]
    assert cue_times(cues, "projector") == [18.0]
    assert cue_times(cues, "camera push") == [22.0]
    # the cards shot with a big "0" is the reveal: one low hit on it
    assert reveals == [11.0]
    assert cue_times(cues, "low hit") == [11.05]
    assert track.dtype == np.float32 and track.ndim == 1 and len(track) == int(27.5 * SR)
    assert np.abs(track).max() < 1.0
    # sound is actually there at each cue
    for t, _, _ in cues:
        s = int(t * SR)
        assert np.abs(track[s:s + int(0.1 * SR)]).max() > 1e-4


def test_min_gap_for_ordinary_cues():
    shots = [{"k": "bigtext", "t0": t, "t1": t + 0.5, "text": "X"} for t in (1.0, 1.5, 2.3, 2.6, 4.0)]
    cues, _, _ = sv.build_cues(shots, 6.0)
    times = cue_times(cues, "card slap")
    assert times == [1.0, 2.3, 4.0]
    assert all(b - a >= sv.MIN_GAP for a, b in zip(times, times[1:]))


def test_item_cues_nudged_or_skipped():
    # three cards 1.1 s apart: the second is nudged 0.1 s to keep 1.2 s, the third would need 0.2 s and is skipped
    shots = [{"k": "cards", "t0": 1.0, "t1": 5.3, "items": [{"big": "1"}, {"big": "2"}, {"big": "3"}]}]
    cues, _, _ = sv.build_cues(shots, 6.0)
    assert cue_times(cues, "card slap") == [1.05, 2.25]


def test_reveal_detection():
    assert sv.is_reveal({"k": "cards", "items": [{"big": "4"}, {"big": "0"}]})
    assert sv.is_reveal({"k": "timeline", "items": [{"date": "1987", "text": "x"}], "foot": "Seats won by party lists: 0"})
    assert sv.is_reveal({"k": "bigtext", "text": "WINNERS\n0"})
    assert not sv.is_reveal({"k": "cards", "items": [{"big": "10"}, {"big": "20"}]})
    assert not sv.is_reveal({"k": "bigtext", "text": "2020"})
    assert not sv.is_reveal({"k": "timeline", "items": [], "foot": "Seats: 10"})
    cues, _, reveals = sv.build_cues(
        [{"k": "timeline", "t0": 3.0, "t1": 9.0, "items": [{"date": "1", "text": "a"}, {"date": "2", "text": "b"}],
          "foot": "Seats won: 0"}], 10.0)
    assert reveals == [3.0] and cue_times(cues, "low hit") == [3.05]


def test_pad_silent_inside_reveal_window():
    total, r = 20.0, 10.0
    L = int((total + 0.5) * SR)
    pad = sv.music_pad(total, L) * sv.pad_gain_curve(np.zeros(L), [r])
    seg = lambda a, b: np.abs(pad[int(a * SR) + 1:int(b * SR)])  # noqa: E731  (+1: float rounding at the edge)
    assert seg(r - 0.8, r + 1.6).max() == 0.0                          # silent from r - 0.8 to r + 1.6
    assert seg(r + 2.4, r + 3.4).max() > 0.01                          # back after 0.8 s
    assert seg(r - 1.2, r - 0.85).mean() > 2.5 * seg(r - 4.0, r - 3.0).mean()   # swell before the cut
    # under speech the pad sits about 15 dB lower than in the gaps
    assert 20 * np.log10(sv.pad_gain_curve(np.ones(10), [])[0] / sv.pad_gain_curve(np.zeros(10), [])[0]) == \
        pytest.approx(-14.9, abs=0.3)


def synthetic_voice(total, seed=3):
    """Narration stand-in: 2.6 s sentences with 0.7 s pauses, syllable-modulated speech-band noise
    at about -20 dBFS RMS while talking."""
    rng = np.random.default_rng(seed)
    L = int(total * SR)
    t = np.arange(L) / SR
    x = sv.band(rng.standard_normal(L).astype(np.float32), 200, 3400, order=3)
    syll = 0.35 + 0.65 * np.abs(np.sin(2 * np.pi * 2.2 * t))
    talking = ((t % 3.3) < 2.6) & (t > 0.3)
    env = sv._smooth(talking.astype(np.float64) * syll, int(0.02 * SR))
    v = x * env
    on = env > 0.5
    return (v / np.sqrt((v[on] ** 2).mean()) * sv.db(-20)).astype(np.float32)


def test_voice_sits_well_over_effects():
    total = 27.0
    mixed, report = sv.mix(synthetic_voice(total), shot_list(), total)
    assert mixed.dtype == np.float32 and len(mixed) == int((total + 0.5) * SR)
    assert report["reveals"] == [11.0] and len(report["cues"]) >= 10
    assert report["voice_over_sfx_db_p10"] >= 15.0
    assert report["voice_over_sfx_db_median"] >= report["voice_over_sfx_db_p10"]


def test_deterministic():
    a = sv.build_cues(shot_list(), 27.0)
    b = sv.build_cues(shot_list(), 27.0)
    assert a[0] == b[0] and a[2] == b[2] and np.array_equal(a[1], b[1])
    v = synthetic_voice(27.0)
    m1, r1 = sv.mix(v, shot_list(), 27.0)
    m2, r2 = sv.mix(v, shot_list(), 27.0)
    assert np.array_equal(m1, m2) and r1 == r2


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_master_hits_target(tmp_path):
    total = 8.0
    mixed, _ = sv.mix(synthetic_voice(total), [{"k": "bigtext", "t0": 1.0, "t1": 4.0, "text": "X"}], total)
    raw = sv.write_wav(tmp_path / "raw.wav", mixed)
    back = sv.load_audio(raw)
    assert np.allclose(back[: len(mixed)], mixed, atol=1e-6)
    lufs, peak = sv.master(raw, tmp_path / "out.wav")
    assert abs(lufs + 14.0) <= 0.3
    assert peak < -1.0
    assert len(sv.load_audio(tmp_path / "out.wav")) == pytest.approx(len(mixed), abs=SR // 100)

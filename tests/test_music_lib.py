"""Music bed from the documentary library (owner, 2026-11-27): bar-line assembly, reveal on the space section,
25 dB phone-band level held through pauses, chapter cue changes, pad fallback."""
import json

import subprocess

import numpy as np
import pytest

from tfs.media import music_lib, sfx_v2

SR = 48000
BAR = 2.0
LEAD = 0.3


def _meta(cid, mood):
    secs, b = {}, 0
    for k, n in (("intro", 2), ("drive", 8), ("build", 4), ("space", 2), ("return", 4), ("ending", 2)):
        secs[k] = {"start_s": LEAD + b * BAR, "end_s": LEAD + (b + n) * BAR, "bars": n}
        b += n
    return {"cue_id": cid, "mood": mood, "key": "D minor", "bpm": 120, "bar_s": BAR, "first_downbeat_s": LEAD,
            "length_s": LEAD + b * BAR + 3.0, "bars": b, "sections": secs,
            "loop": {"start_s": LEAD + 6 * BAR, "end_s": LEAD + 10 * BAR}}


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    idx = []
    for cid, mood in (("doc-investigation-a", "investigation"), ("doc-investigation-b", "investigation"),
                      ("doc-dark-a", "dark"), ("doc-somber-a", "somber")):
        m = _meta(cid, mood)
        t = np.arange(int(m["length_s"] * SR)) / SR
        # a steady bed with a soft 8th-note pulse, so levels are measurable
        x = (0.2 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 660 * t)) * (0.8 + 0.2 * np.sin(2 * np.pi * 4 * t))
        wav = sfx_v2.write_wav(tmp_path / f"{cid}.wav", x.astype(np.float32))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "flac", str(tmp_path / f"{cid}.flac")],
                       check=True)
        wav.unlink()
        (tmp_path / f"{cid}.json").write_text(json.dumps(m))
        idx.append({"cue_id": cid, "mood": mood})
    (tmp_path / "index.json").write_text(json.dumps(idx))
    monkeypatch.setenv("TFS_MUSIC_DIR", str(tmp_path))
    return tmp_path


def _on_bar(t):
    k = (t - LEAD) / BAR
    return abs(k - round(k)) < 1e-6


@pytest.mark.parametrize("length,reveal", [(43.4, 30.34), (43.4, 9.1), (120.0, 61.7), (12.0, 5.0), (60.0, 2.5)])
def test_plan_puts_space_on_the_reveal_and_joins_on_bars(lib, length, reveal):
    meta = json.loads((lib / "doc-investigation-a.json").read_text())
    spans = music_lib.plan(meta, length, reveal)
    starts = np.cumsum([0] + [b - a for a, b in spans])
    i = next(i for i, (a, b) in enumerate(spans) if abs(a - meta["sections"]["space"]["start_s"]) < 1e-9)
    assert abs(starts[i] - reveal) < 1e-3
    assert starts[-1] <= length + 1e-6
    for a, b in spans[1:]:
        assert _on_bar(a), (a, b)
    for a, b in spans[:-1]:
        assert _on_bar(b), (a, b)


@pytest.mark.parametrize("length", [20.0, 43.4, 300.0])
def test_plan_without_reveal_fills_to_within_a_bar_plus_tail(lib, length):
    meta = json.loads((lib / "doc-investigation-a.json").read_text())
    spans = music_lib.plan(meta, length, None)
    total = sum(b - a for a, b in spans)
    assert length - BAR - 1e-6 <= total <= length + 1e-6
    for a, _ in spans[1:]:
        assert _on_bar(a)


def test_pick_is_stable_and_follows_the_mood(lib):
    assert music_lib.mood_of("Paano mo tatanggalin ang presidente?") == "investigation"
    assert music_lib.mood_of("Alam mo ba kung paano bumoto?") == "curiosity"
    assert music_lib.mood_of("Kaso ng korapsyon sa DPWH") == "dark"
    assert music_lib.mood_of("Senado at Kamara") == "investigation"
    a = music_lib.pick("Senado at Kamara", "2026-11-27.a", 3)
    assert a == music_lib.pick("Senado at Kamara", "2026-11-27.a", 3)
    assert a[0].startswith("doc-investigation-")
    assert music_lib.pick("Kaso ng korapsyon", "x")[0] == "doc-dark-a"


def _voice(total, pauses):
    t = np.arange(int(total * SR)) / SR
    v = np.zeros_like(t)
    on = np.ones_like(t, bool)
    for a, b in pauses:
        on &= ~((t >= a) & (t < b))
    on &= t > 0.4
    v[on] = 0.3 * np.sin(2 * np.pi * 180 * t[on]) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t[on]))
    return v.astype(np.float32)


def test_bed_level_is_25_db_and_holds_through_short_pauses(lib):
    total = 43.4
    v = _voice(total, [(10.0, 10.8), (20.0, 21.5)])
    n = int((total + 0.5) * SR)
    bed, rep = music_lib.bed(v, n, [30.34], [], "Senado", "id1")
    assert rep["music"] == "library" and abs(rep["phone_gap_db"] - 25) < 0.6
    db = lambda a, b: 20 * np.log10(np.sqrt(np.mean(bed[int(a * SR):int(b * SR)] ** 2)) + 1e-12)
    assert db(10.1, 10.7) - db(8.5, 9.5) < 1.5          # 0.8 s pause: no rise
    assert db(20.2, 21.3) - db(18.5, 19.5) < 1.5        # 1.5 s pause: no rise
    assert rep["reveal_aligned"] == [30.34]


def test_long_form_changes_cue_at_chapter_cards(lib):
    total = 200.0
    v = _voice(total, [(60.0, 62.6), (130.0, 132.6)])
    bed, rep = music_lib.bed(v, int(total * SR), [], [60.0, 130.0], "Senado", "id2")
    assert rep["chapters"] == 3 and len(rep["cues"]) == 3 and len(set(rep["cues"])) >= 2
    assert np.isfinite(bed).all() and len(bed) == int(total * SR)


def test_mix_falls_back_to_the_pad_without_a_library(tmp_path, monkeypatch):
    monkeypatch.setenv("TFS_MUSIC_DIR", str(tmp_path))       # empty: no index
    v = _voice(12.0, [])
    out, rep = sfx_v2.mix(v, [], 12.0, music_text="x", music_seed="y")
    assert rep["music"]["music"].startswith("pad") and np.isfinite(out).all()


def test_mix_uses_the_library_when_present(lib):
    v = _voice(43.4, [])
    shots = [{"k": "bigtext", "t0": 30.34, "t1": 34.0, "text": "0"}]
    out, rep = sfx_v2.mix(v, shots, 43.4, music_text="Senado", music_seed="z")
    assert rep["music"]["music"] == "library" and rep["reveals"] == [30.34]
    assert rep["music"]["reveal_aligned"] == [30.34]


def _clicks(meta, n_bars_extra=0):
    """Cue audio that is silent except a click on every bar line and a double click at the space section start."""
    x = np.zeros(int(meta["length_s"] * SR), np.float32)
    t = LEAD
    while t < meta["length_s"] - 3.0:
        x[int(round(t * SR))] = 0.5
        t += BAR
    s = int(round(meta["sections"]["space"]["start_s"] * SR))
    x[s] = 1.0
    return x


@pytest.mark.parametrize("length,reveal", [(43.88, 30.34), (121.0, 60.0), (300.0, 250.0), (900.0, 610.3)])
def test_rendered_reveal_lands_on_time_and_bars_stay_even(lib, length, reveal):
    meta = json.loads((lib / "doc-investigation-a.json").read_text())
    audio = _clicks(meta)
    bed = music_lib.render_spans(audio, music_lib.plan(meta, length, reveal), int(length * SR), fade_end=False)
    peaks = np.flatnonzero(bed > 0.75)
    assert len(peaks) and abs(peaks[0] / SR - reveal) < 0.002          # the space start, within 2 ms
    bars = np.flatnonzero((bed > 0.3) & (bed < 0.75)) / SR
    gaps = np.diff(bars)
    assert np.all(np.abs(gaps - BAR) < 0.002) or np.all(np.abs(gaps[gaps < 1.5 * BAR] - BAR) < 0.002)


@pytest.mark.parametrize("length,reveal", [(10.0, 8.0), (43.4, 42.0), (8.0, 5.0), (60.0, 1.0)])
def test_plan_never_runs_past_the_target(lib, length, reveal):
    meta = json.loads((lib / "doc-investigation-a.json").read_text())
    for chain in (False, True):
        total = sum(b - a for a, b in music_lib.plan(meta, length, reveal, chain=chain))
        assert total <= length + 1e-6
        if chain:
            assert abs(total - length) < 1e-6        # a chained segment fills its slot exactly


def test_reveal_under_one_bar_is_not_reported_as_aligned(lib):
    v = _voice(20.0, [])
    _, rep = music_lib.bed(v, int(20 * SR), [2.5], [], "Senado", "id3")   # bar is 2 s; 2.5 s is fine
    assert rep["reveal_aligned"] == [2.5]
    _, rep = music_lib.bed(v, int(20 * SR), [2.0], [], "Senado", "id3")
    assert rep["reveal_aligned"] in ([2.0], [None])


def test_no_speech_gives_a_fixed_quiet_bed(lib):
    silent = np.zeros(int(20 * SR), np.float32)
    bed, rep = music_lib.bed(silent, int(20 * SR), [], [], "Senado", "id4")
    lvl = 20 * np.log10(np.sqrt(np.mean(bed[SR:-2 * SR] ** 2)) + 1e-12)
    assert np.isfinite(bed).all() and -50 < lvl < -35


def test_corrupt_library_file_falls_back_to_the_pad(lib):
    (lib / "doc-investigation-a.json").write_text("{not json")
    (lib / "doc-investigation-b.json").write_text("{not json")
    out, rep = sfx_v2.mix(_voice(12.0, []), [], 12.0, music_text="Senado", music_seed="z")
    assert rep["music"]["music"].startswith("pad") and np.isfinite(out).all()

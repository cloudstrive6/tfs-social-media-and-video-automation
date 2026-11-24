"""Offline tests for the VoxCPM2 narrator provider: Modal, Whisper and ffmpeg are all mocked."""
import io
import json
import wave

import numpy as np
import pytest

from tfs.media import tts_voxcpm as vx


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TFS_DATA_DIR", str(tmp_path))
    yield tmp_path


def wav_bytes(secs=1.0, sr=48000, lead=0.3, tail=0.4, marker=0.5):
    """Silence, a tone, silence. The tone's amplitude doubles as a marker the fake Whisper reads."""
    y = np.zeros(int((lead + secs + tail) * sr), np.float32)
    t = np.arange(int(secs * sr)) / sr
    y[int(lead * sr): int(lead * sr) + len(t)] = marker * np.sin(2 * np.pi * 220 * t)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------- numbers and scoring
def test_spoken_numbers():
    assert vx.spoken("ng 1987 Constitution") == "ng nineteen eighty-seven Constitution"
    assert vx.spoken("January 20, 2001") == "January twenty, two thousand one"
    assert vx.spoken("October 14, 2023") == "October fourteen, twenty twenty-three"
    assert vx.spoken("Noong 2000 hanggang 2020") == "Noong two thousand hanggang twenty twenty"
    assert vx.spoken("65 sa 120 na seats") == "sixty-five sa one hundred twenty na seats"
    assert vx.spoken("1,500 tao, 3.5% at ₱5 billion") == "one thousand five hundred tao, three point five percent at five billion pesos"
    assert vx.spoken("ang 21st century at 1905") == "ang twenty-first century at nineteen oh five"
    assert vx.cardinal(1_000_001) == "one million one"


def test_letter_match_digits_equal_words():
    script = "Nasa Article Seven, Section Four ng 1987 Constitution iyan."
    heard = "Nasa Article 7, Section 4 ng nineteen eighty seven Constitution iyan"
    assert vx.letter_match(script, heard) == pytest.approx(1.0)
    assert vx.letter_match("Anim na taon.", "Anim na taon") == pytest.approx(1.0)
    assert vx.letter_match("Anim na taon, isang termino lang.", "pitong taon") < 0.85
    assert vx.letter_match("Pilipinas", "Pílipinas") == pytest.approx(1.0)       # accents dropped


def test_trim_keeps_pilot_padding():
    y, sr = vx.read_wav(wav_bytes(secs=1.0, lead=0.5, tail=0.6))
    seg = vx.trim(y, sr)
    assert 1.1 <= len(seg) / sr <= 1.3            # 1.0 s tone + 0.05 s before + 0.12 s after (+ frame slack)
    assert len(vx.trim(np.zeros(4800, np.float32), sr)) == 0


# ---------------------------------------------------------------- word times
def test_map_words_keeps_script_spelling():
    script = "Noong 2001, na-impeach si Estrada."
    heard = [("Noong", 0.0, 0.3), ("2001,", 0.3, 1.1), ("na", 1.1, 1.3), ("impeach", 1.3, 1.7),
             ("si", 1.7, 1.8), ("Estrada.", 1.8, 2.3)]
    words = vx.map_words(script, heard, 2.5)
    assert [w for w, _, _ in words] == script.split()
    assert words[1] == ("2001,", 0.3, 1.1)
    assert words[2] == ("na-impeach", 1.1, 1.7)   # two heard words joined onto one script word
    assert words[-1] == ("Estrada.", 1.8, 2.3)


def test_map_words_interpolates_missed_and_reads_spelled_numbers():
    script = "Sa 1987 Constitution, Section Four."
    heard = [("Sa", 0.0, 0.2), ("nineteen", 0.2, 0.5), ("eighty-seven", 0.5, 0.9), ("Section", 1.6, 1.9),
             ("4.", 1.9, 2.1)]
    words = vx.map_words(script, heard, 2.4)
    assert words[1] == ("1987", 0.2, 0.9)
    w, s, e = words[2]                            # "Constitution," was not heard: placed in the gap
    assert w == "Constitution," and 0.9 <= s < e <= 1.6
    assert words[4] == ("Four.", 1.9, 2.1)
    assert all(a <= b for _, a, b in words)


# ---------------------------------------------------------------- the provider end to end (mocked)
class FakeFunction:
    def __init__(self, plan):
        self.plan, self.calls = plan, []

    def _one(self, lines, seed, takes):
        self.calls.append((list(lines), seed, takes))
        return [[wav_bytes(marker=self.plan(line, seed, k)) for k in range(takes)] for line in lines]

    def remote(self, lines, seed=19, takes=2):
        return self._one(lines, seed, takes)

    def map(self, chunks, kwargs):
        for c in chunks:
            yield self._one(c, kwargs["seed"], kwargs["takes"])


def install(monkeypatch, plan, heard_for):
    """plan(line, seed, take) -> marker amplitude; heard_for(marker, line) -> what Whisper 'hears'."""
    fn = FakeFunction(plan)
    sent = {}

    def transcribe(path):
        y, _ = vx.read_wav(path.read_bytes())
        marker = round(float(np.abs(y).max()), 2)
        text = heard_for(marker, sent[path.name.split("_")[0]])
        n = len(text.split()) or 1
        return text, [(w, k * 0.2, k * 0.2 + 0.18) for k, w in enumerate(text.split())][:n]

    real_score = vx.score_take

    def score(text, data, tmp, tag):
        sent[tag.split("_")[0]] = text
        return real_score(text, data, tmp, tag)

    def encode(wav, mp3):
        mp3.write_bytes(wav.read_bytes())
        y, sr = vx.read_wav(wav.read_bytes())
        return len(y) / sr

    monkeypatch.setattr(vx, "_function", lambda: fn)
    monkeypatch.setattr(vx, "_transcribe", transcribe)
    monkeypatch.setattr(vx, "score_take", score)
    monkeypatch.setattr(vx, "_encode", encode)
    return fn


def test_picks_best_take_and_caches(tmp_path, monkeypatch):
    texts = ["Anim na taon ang termino.", "Nasa 1987 Constitution iyan."]
    fn = install(monkeypatch, plan=lambda line, seed, k: 0.3 if k == 0 else 0.6,
                 heard_for=lambda m, line: line if m == 0.6 else "Anim na taon ang terminong ito")
    clips = vx.synthesize_scenes(texts, tmp_path / "audio", ids=[1, 2])
    assert fn.calls == [(["Anim na taon ang termino.", "Nasa nineteen eighty-seven Constitution iyan."], 19, 2)]
    meta = json.loads((tmp_path / "audio" / "002.json").read_text(encoding="utf-8"))
    assert meta["take"] == 1 and meta["letter_match"] == 1.0
    assert [w for w, _, _ in clips[1].words] == ["Nasa", "1987", "Constitution", "iyan."]
    assert clips[0].path.name == "001.mp3" and 1.1 <= clips[0].duration <= 1.3
    vx.synthesize_scenes(texts, tmp_path / "audio", ids=[1, 2])
    assert len(fn.calls) == 1                     # second run is served from the cache


def test_retry_then_fail_below_threshold(tmp_path, monkeypatch):
    fn = install(monkeypatch, plan=lambda line, seed, k: 0.5, heard_for=lambda m, line: "walang kinalaman")
    with pytest.raises(vx.NarrationQualityError, match="scene 7 best"):
        vx.synthesize_scenes(["Isang impeachment lang kada taon."], tmp_path / "audio", ids=[7])
    assert [c[1] for c in fn.calls] == [19, 19 + vx.RETRY_SEED_STEP]
    assert not (tmp_path / "audio" / "007.json").exists()


def test_retry_round_rescues_a_line(tmp_path, monkeypatch):
    fn = install(monkeypatch, plan=lambda line, seed, k: 0.5 if seed == 19 else 0.7,
                 heard_for=lambda m, line: line if m == 0.7 else "mali")
    clips = vx.synthesize_scenes(["Sa Pilipinas.", "Sa New Zealand."], tmp_path / "audio")
    assert len(fn.calls) == 2 and fn.calls[1][1] == 19 + vx.RETRY_SEED_STEP
    assert json.loads((tmp_path / "audio" / "000.json").read_text())["seed"] == 19 + vx.RETRY_SEED_STEP
    assert len(clips) == 2


def test_chunks_go_through_map(tmp_path, monkeypatch):
    monkeypatch.setattr(vx, "CHUNK", 2)
    fn = install(monkeypatch, plan=lambda line, seed, k: 0.6, heard_for=lambda m, line: line)
    texts = [f"Linya bilang {n}." for n in range(5)]
    clips = vx.synthesize_scenes(texts, tmp_path / "audio")
    assert [len(c[0]) for c in fn.calls] == [2, 2, 1]
    assert [c.words[-1][0] for c in clips] == [f"{n}." for n in range(5)]


def test_modal_limit_becomes_usage_limit(tmp_path, monkeypatch):
    from tfs.llm import UsageLimitError

    class Boom:
        def remote(self, *a, **k):
            raise RuntimeError("Workspace spend limit reached for this billing cycle")

    monkeypatch.setattr(vx, "_function", lambda: Boom())
    with pytest.raises(UsageLimitError):
        vx.synthesize_scenes(["Sa Pilipinas."], tmp_path / "audio")


def test_synthesize_takes_scene_objects(tmp_path, monkeypatch):
    class Scene:
        def __init__(self, id, text):
            self.id, self.text = id, text

    fn = install(monkeypatch, plan=lambda line, seed, k: 0.6, heard_for=lambda m, line: line)
    clips = vx.synthesize([Scene(3, "Sa *Pilipinas*, anim na taon. [S1]")], tmp_path / "audio")
    assert fn.calls[0][0] == ["Sa Pilipinas, anim na taon."]
    assert clips[0].path.name == "003.mp3"

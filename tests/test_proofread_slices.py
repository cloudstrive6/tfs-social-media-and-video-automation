"""Proofreader (2026-11-25): every scene is transcribed from its own slice of audio, so Whisper losing its place
on a long-form can never shift later scenes; source tags with letter suffixes never reach the narrator."""
import numpy as np

from tfs import qa
from tfs.media.tts import clean


class Seg:
    def __init__(self, text):
        self.text = text


def test_each_scene_is_transcribed_from_its_own_slice(monkeypatch):
    sr = 16000
    audio = np.concatenate([np.full(sr * 2, k, np.float32) for k in (1, 2, 3)])     # three 2 s scenes
    monkeypatch.setattr(qa, "audio16k", lambda media: audio)
    seen = []

    class W:
        def transcribe(self, piece, **kw):
            seen.append((len(piece), float(np.median(piece)), kw.get("condition_on_previous_text")))
            return [Seg(f" scene {int(np.median(piece))} ")], None
    monkeypatch.setattr(qa, "_whisper", lambda: W())
    out = qa.transcribe_scenes("v.mp4", [0.0, 2.0, 4.0, 6.0])
    assert out == ["scene 1", "scene 2", "scene 3"]
    assert [m for _, m, _ in seen] == [1.0, 2.0, 3.0] and all(c is False for _, _, c in seen)


def test_letter_suffixed_source_tags_are_stripped():
    assert clean("Ayon sa batas. [S14a] Totoo [S1, S2b] ito. [S17c]") == "Ayon sa batas. Totoo ito."

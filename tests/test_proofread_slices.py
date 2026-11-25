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


def test_blocking_frames_go_back_to_the_designer_with_the_reviewers_notes(monkeypatch, tmp_path):
    """Atlas (2026-11-25): a wrong number on a card is blocking and must be re-planned, not posted with a warning."""
    from tfs.models import Scene, Script, Shot, ShotList, ShotVerdict
    script = Script(scenes=[Scene(id=i, chapter="c", speaker="NARRATOR", text=f"line {i}", visual="v") for i in (0, 1)],
                    sources=[])
    shots = ShotList(shots=[Shot(scene_id=i, kind="card", style="story", image_prompt="", card_type="stat",
                                 card_title="t", card_lines=[], reuse_of_scene=0, motion="static") for i in (0, 1)])
    monkeypatch.setattr(qa, "duration", lambda v: 10.0)
    monkeypatch.setattr(qa, "grab", lambda v, t, out: out)
    monkeypatch.setattr(qa, "proofread", lambda *a: ({}, [], "ok", []))
    verdict = ShotVerdict(frame="scene 1", ok=False, blocking=True, problems=["P3.91 trillion should be P19.66 trillion"],
                          fix_prompt="")
    monkeypatch.setattr(qa, "_look", lambda frames, ctx: ([verdict], 7, 8, []))
    report = qa.review_video("vertical", tmp_path, script, shots, [0.0, 5.0], tmp_path / "v.mp4", None, "hook")
    assert report.redo_images == {"1": "P3.91 trillion should be P19.66 trillion"} and not report.passed

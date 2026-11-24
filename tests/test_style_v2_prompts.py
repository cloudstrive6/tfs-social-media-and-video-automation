"""Style v2 (atlas engine): the writers and reviewers get the v2 bible and briefs, never the cartoon-era ones
(Bryce, 2026-11-24: "don't use that old one")."""
from tfs import config


def test_atlas_engine_uses_v2_bible_and_briefs(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "channel", lambda: {"video": {"engine": "atlas"}})
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    bible = config.style_bible()
    assert bible.startswith("# The Filipino Standard: Style Bible v2") and "HeyHistorically" not in bible
    for agent in ("scriptwriter", "hook_master", "visual_qa"):
        assert "(style v2" in config.load_prompt(agent).splitlines()[0], agent
    sw = config.load_prompt("scriptwriter")
    assert "Cold open (≤30 s). A skit" not in sw and "Ritual:" not in sw
    assert config.notes_dir("creative_notes") == tmp_path / "creative_notes_v2"
    (tmp_path / "creative_notes").mkdir()
    (tmp_path / "creative_notes" / "scriptwriter.md").write_text("Bring Tito Trapo into every cold open.")
    assert "Tito Trapo into every cold open" not in config.load_prompt("scriptwriter")      # cartoon-era notes ignored


def test_vector_engine_keeps_the_old_set(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "channel", lambda: {"video": {"engine": "vector"}})
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    assert "Style Bible v2" not in config.style_bible().splitlines()[0]
    assert config.load_prompt("scriptwriter").startswith("# Role: Head Writer\n")

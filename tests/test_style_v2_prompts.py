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


def test_v2_numbers_stay_digits_and_are_read_in_english(monkeypatch, tmp_path):
    """Bryce, 2026-11-25: numbers need not be Tagalog; the narrator says "one point three trillion pesos",
    "one hundred seventy thousand five hundred ninety eight", "twenty twenty six", "two thousand one"."""
    from tfs.media.tts_voxcpm import spoken
    monkeypatch.setattr(config, "channel", lambda: {"video": {"engine": "atlas"}})
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    ed = config.load_prompt("narration_editor")
    assert "(style v2" in ed.splitlines()[0] and "limang punto apat" not in ed
    assert "Never write a number in Tagalog words" in ed
    assert "never spell them out in Tagalog" in config.load_prompt("scriptwriter")
    assert spoken("₱1.3 trillion") == "one point three trillion pesos"
    assert spoken("₱170,598") == "one hundred seventy thousand five hundred ninety-eight pesos"
    assert spoken("noong 2026") == "noong twenty twenty-six"
    assert spoken("noong 2001") == "noong two thousand one"


ATLAS_PATH = ("trend_scout", "editor_in_chief", "researcher", "scriptwriter", "hook_master", "fact_checker",
              "narration_editor", "atlas_designer", "title_writer", "seo_writer", "thumbnail_artist", "audio_qa",
              "visual_qa", "analyst", "creative_director", "screen_checker")


def test_atlas_path_loads_only_v2_briefs_and_old_ones_are_retired(monkeypatch, tmp_path):
    """Bryce, 2026-11-25: any old-style element (storytelling, narration, style) is removed and never used."""
    import pytest
    from tfs.agents import creative
    monkeypatch.setattr(config, "channel", lambda: {"video": {"engine": "atlas"}})
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "schedule", lambda: {"paused": []})
    old_markers = ("Tito Trapo", "Historically", "Kuya Standard", "Resibo", "limang punto", "skit idea",
                   "alam mo ba?\" moment", "country-ball", "Josh")
    for agent in ATLAS_PATH:
        text = config.load_prompt(agent)
        for m in old_markers:
            assert m not in text, (agent, m)
        assert "\u2014" not in text and "\u2013" not in text, agent          # no em or en dashes
    for agent in ("motion_designer", "carousel_designer", "sound_designer", "visual_critic", "visual_director",
                  "preflight_art"):
        with pytest.raises(config.RetiredBriefError):
            config.load_prompt(agent)
    assert "carousel" in config.paused_kinds()
    assert creative.agents() == ("atlas_designer", "thumbnail_artist")

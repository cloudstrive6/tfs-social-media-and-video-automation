"""Natural Taglish (Bryce, 2026-11-25: "Sa 7 buwan ng 2026" is not how anyone says it; a blind reviewer flagged
"Bayaran mo ba iyon?"). A digit is read in English, so it takes English units; a future question takes the
contemplated aspect. Guide with sources: Bryce-Brain wiki/answers/tfs-natural-taglish-2026-11.md."""
import re

import pytest

from tfs import config
from tfs.media.tts_voxcpm import spoken
from tfs.taglish_lint import problems, script_problems

# Lines the dry runs actually produced (runs 3 and 4 of the ₱170,598 debt follow-up, 2026-11-25).
DRY_RUN_BAD = [
    "Ayon sa Presidential Decree 1177, automatic appropriation ang debt service, bayad bago ang budget debate. "
    "Sa 7 buwan ng 2026, ₱1.37 trillion na ang nabayaran. [S14][S7]",
    "Sabi ng post sa feed mo, may utang kang ₱170,598. [S6] Bayaran mo ba iyon?",
    "Pero ₱1.37 trillion ang debt service sa unang 7 buwan ng 2026, pondong hindi na mapupunta sa ospital. [S4]",
    "Pero totoo ang bayad, ₱1.37 trillion sa 7 months. [S10]",
]

NATURAL = [
    "Sa first 7 months ng 2026, ₱1.37 trillion na ang nabayaran. [S14][S7]",
    "Sabi ng post sa feed mo, may utang kang ₱170,598. [S6] Babayaran mo ba iyon?",
    "Kailangan mo bang bayaran?",
    "Ikaw ba ang magbabayad?",
    "Saan mo ba makikita ang utang ng bansa?",
    "Alam mo ba kung sino ang nangutang?",
    "₱1.37 trillion ang nabayaran sa loob lang ng 7 months.",
    "30 days mula nang matanggap niya ang bill.",
    "Sa 6 years na termino, isang beses lang.",
    "24 na senador ang bumoto, ayon sa journal ng Senado.",
    "Hindi, average lang iyon: ₱19.66 trillion, hinati sa 115 million na Pilipino. [S1][S18]",
    "Bumaba ito sa 55.9% noong July 2026.",
    "Ayon sa Article 7, Section 20 ng 1987 Constitution, ang Republika ang nangungutang.",
    "Hindi iyon bill na nakapangalan sa iyo.",
    "Yung budget na iyon ang pinag-uusapan, hindi ang share mo.",
]


@pytest.mark.parametrize("line", DRY_RUN_BAD)
def test_dry_run_lines_are_flagged(line):
    assert problems(line), line


@pytest.mark.parametrize("line", NATURAL)
def test_natural_lines_pass(line):
    assert problems(line) == [], (line, problems(line))


def test_each_rule_names_the_fix():
    assert "7 months" in problems("7 buwan na ang lumipas.")[0]
    assert "3 years" in problems("3 taon ang termino.")[0]
    assert "trillion" in problems("₱19.66 trilyon ang utang.")[0]
    assert "%" in problems("55.9 porsyento ang boto.")[0]
    assert "July" in problems("noong Hulyo 15, 2026")[0]
    assert "7th" in problems("sa ika-7 buwan")[-1]
    assert "Babayaran" in problems("Bayaran mo ba iyon?")[0]
    assert "Gawin ba" in problems("Gawin ba iyon ng Senado?")[0]
    assert "sa loob ng 3 years" in problems("Natapos ito sa 3 years.")[0]
    # Bryce, 2026-11-25: "iyong" is "yung" (the/that) or "mo" (your); "sa iyo" and "iyon" are fine.
    msg = problems("Hindi bill ang iyong share sa utang.")[0]
    assert "yung" in msg and "share mo" in msg
    assert problems("Iyong budget na iyon ang pinag-uusapan.")
    assert "spell it" in problems("'Yung budget na iyon ang pinag-uusapan.")[0]
    assert "after ng or sa" in problems("Tumaas ang presyo ng yung bigas.")[0]
    assert problems("Yung budget na iyon, napunta sa bahay mo.") == []


def test_script_problems_name_the_scene():
    assert script_problems(["Okay ito.", "Bayaran mo ba iyon?"])[0].startswith("scene 2: ")


def test_the_narrator_reads_the_natural_forms_in_english():
    assert spoken("sa first 7 months ng 2026") == "sa first seven months ng twenty twenty-six"
    assert spoken("sa 7th month ng 2026") == "sa seventh month ng twenty twenty-six"
    assert spoken("₱1.37 trillion") == "one point three seven trillion pesos"


def _brief(monkeypatch, tmp_path, name):
    monkeypatch.setattr(config, "channel", lambda: {"video": {"engine": "atlas"}})
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    return config.load_prompt(name)


def test_scriptwriter_write_and_not_table_matches_the_lint(monkeypatch, tmp_path):
    """Every 'Write' example in the brief passes the lint and every 'Not' example fails it, so the brief and the
    checks cannot drift apart."""
    sw = _brief(monkeypatch, tmp_path, "scriptwriter")
    section = sw.split("## Natural Taglish", 1)[1].split("\n## ", 1)[0]
    rows = [r for r in section.splitlines() if r.startswith("| ") and not r.startswith("| Write") and "---" not in r]
    assert len(rows) >= 6
    for row in rows:
        write, avoid = [c.strip() for c in row.strip("|").split("|")][:2]
        assert problems(write) == [], (write, problems(write))
        assert problems(avoid), avoid


def test_scriptwriter_reference_script_is_natural(monkeypatch, tmp_path):
    sw = _brief(monkeypatch, tmp_path, "scriptwriter")
    ref = sw.split("## A reference you may imitate", 1)[1].split("\n## ", 1)[0]
    lines = [s.strip() for s in re.split(r"\s/\s", ref.split("\n", 1)[1].replace("\n", " ")) if s.strip()]
    assert len(lines) >= 5
    assert script_problems(lines) == []


def test_briefs_carry_the_language_rules(monkeypatch, tmp_path):
    sw = _brief(monkeypatch, tmp_path, "scriptwriter")
    ed = _brief(monkeypatch, tmp_path, "narration_editor")
    assert "A number and its unit are in the same language" in sw
    assert "Babayaran" in sw and "Babayaran" in ed
    assert '"7 buwan" becomes "7 months"' in ed
    assert '"iyong" never stays' in ed and "Never \"iyong\"" in sw
    assert "A number and its unit are in the same language" in config.style_bible()


# ---------------------------------------------------------------- the narration editor step runs the lint
def _script(*texts):
    from tfs.models import Scene, Script
    return Script(scenes=[Scene(id=i, chapter="Hook", speaker="NARRATOR", text=t, visual="map")
                          for i, t in enumerate(texts, 1)], sources=["[S1] x"])


def _fake_editor(monkeypatch, replies):
    from tfs.agents import writers
    calls = []

    def structured(agent, prompt, model):
        calls.append((agent, prompt))
        return replies[len(calls) - 1]
    monkeypatch.setattr(writers.llm, "structured", structured)
    return writers, calls


def test_clean_edit_makes_one_call(monkeypatch):
    clean = _script("Babayaran mo ba iyon?", "Sa first 7 months ng 2026, ₱1.37 trillion na ang nabayaran.")
    writers, calls = _fake_editor(monkeypatch, [clean])
    assert writers.narration_edit(clean) == clean and len(calls) == 1


def test_flagged_edit_gets_one_retry_with_the_problems(monkeypatch):
    bad = _script("Bayaran mo ba iyon?", "Sa 7 buwan ng 2026, ₱1.37 trillion na ang nabayaran.")
    fixed = _script("Babayaran mo ba iyon?", "Sa first 7 months ng 2026, ₱1.37 trillion na ang nabayaran.")
    writers, calls = _fake_editor(monkeypatch, [bad, fixed])
    assert writers.narration_edit(bad) == fixed and len(calls) == 2
    assert calls[1][0] == "narration_editor"
    assert "scene 1:" in calls[1][1] and "scene 2:" in calls[1][1] and "Babayaran" in calls[1][1]


def test_worse_or_reshaped_retry_is_dropped_and_logged(monkeypatch, caplog):
    bad = _script("Bayaran mo ba iyon?", "Okay ito.")
    worse = _script("Bayaran mo ba iyon?", "3 taon na.")
    writers, calls = _fake_editor(monkeypatch, [bad, worse])
    with caplog.at_level("WARNING"):
        assert writers.narration_edit(bad) == bad
    assert "Taglish lint left 1 problem" in caplog.text
    reshaped = _script("Babayaran mo ba iyon?")                       # lost a scene: never used
    writers, calls = _fake_editor(monkeypatch, [bad, reshaped])
    caplog.clear()
    with caplog.at_level("WARNING"):
        assert writers.narration_edit(bad) == bad and len(calls) == 2
    assert "Taglish lint left 1 problem" in caplog.text


def test_retry_that_changes_content_is_dropped(monkeypatch):
    """The retry runs after the fact check, so it may only change wording: no lost tag, number or sentence."""
    bad = _script("Sa 7 buwan ng 2026, ₱1.37 trillion na ang nabayaran. [S14][S7] Buwis ang pinagkukunan.")
    for retry in (_script("Sa first 7 months ng 2026, ₱1.37 trillion na ang nabayaran. [S14] Buwis ang pinagkukunan."),
                  _script("Sa first 7 months ng 2026, ₱1.4 trillion na ang nabayaran. [S14][S7] Buwis ang pinagkukunan."),
                  _script("Buwis ang pinagkukunan. [S14][S7] 7 2026 ₱1.37")):
        writers, calls = _fake_editor(monkeypatch, [bad, retry])
        assert writers.narration_edit(bad) == bad, retry.scenes[0].text
    good = _script("Sa first 7 months ng 2026, ₱1.37 trillion na ang nabayaran. [S14][S7] Galing iyon sa buwis.")
    writers, calls = _fake_editor(monkeypatch, [bad, good])
    assert writers.narration_edit(bad) == good


def test_failed_retry_keeps_the_first_edit(monkeypatch, caplog):
    from tfs.agents import writers
    bad = _script("Bayaran mo ba iyon?")
    calls = []

    def structured(agent, prompt, model):
        calls.append(agent)
        if len(calls) == 2:
            raise RuntimeError("usage limit")
        return bad
    monkeypatch.setattr(writers.llm, "structured", structured)
    with caplog.at_level("WARNING"):
        assert writers.narration_edit(bad) == bad
    assert "retry failed" in caplog.text and len(calls) == 2


def test_first_edit_with_other_scenes_returns_the_original_without_retry(monkeypatch):
    original = _script("Bayaran mo ba iyon?", "Okay ito.")
    writers, calls = _fake_editor(monkeypatch, [_script("Babayaran mo ba iyon?")])
    assert writers.narration_edit(original) == original and len(calls) == 1

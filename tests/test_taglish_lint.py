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
    assert "A number and its unit are in the same language" in config.style_bible()

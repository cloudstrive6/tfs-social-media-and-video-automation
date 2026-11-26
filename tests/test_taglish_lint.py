"""Natural Taglish (Bryce, 2026-11-25: "Sa 7 buwan ng 2026" is not how anyone says it; a blind reviewer flagged
"Bayaran mo ba yon?"; 2026-11-26: "Isang chief justice", not "one chief justice"). Small counts are Tagalog
linked numerals, big figures stay digits read in English with English units; a future question takes the
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
    "Sabi ng post sa feed mo, may utang kang ₱170,598. [S6] Bayaran mo ba yon?",
    "Pero ₱1.37 trillion ang debt service sa unang 7 buwan ng 2026, pondong hindi na mapupunta sa ospital. [S4]",
    "Pero totoo ang bayad, ₱1.37 trillion sa 7 months. [S10]",
]

NATURAL = [
    "Sa unang pitong buwan ng 2026, ₱1.37 trillion na ang nabayaran. [S14][S7]",
    "Sabi ng post sa feed mo, may utang kang ₱170,598. [S6] Babayaran mo ba yon?",
    "Kailangan mo bang bayaran?",
    "Ikaw ba ang magbabayad?",
    "Saan mo ba makikita ang utang ng bansa?",
    "Alam mo ba kung sino ang nangutang?",
    "₱1.37 trillion ang nabayaran sa loob lang ng pitong buwan.",
    "30 days mula nang matanggap niya ang bill.",
    "Sa anim na taong termino, isang beses lang.",
    "Isang chief justice lang ang uupo bilang presiding officer.",
    "20 to 3 ang boto, ayon sa journal ng Senado.",
    "Step 1: sa House, ayon sa Article 11, Section 3 ng 1987 Constitution.",
    "24 na senador ang bumoto, ayon sa journal ng Senado.",
    "Hindi, average lang yon: ₱19.66 trillion, hinati sa 115 million na Pilipino. [S1][S18]",
    "Bumaba ito sa 55.9% noong July 2026.",
    "Ayon sa Article 7, Section 20 ng 1987 Constitution, ang Republika ang nangungutang.",
    "Hindi yon bill na nakapangalan sa iyo.",
    "Yung budget na yon ang pinag-uusapan, hindi ang share mo.",
]


@pytest.mark.parametrize("line", DRY_RUN_BAD)
def test_dry_run_lines_are_flagged(line):
    assert problems(line), line


@pytest.mark.parametrize("line", NATURAL)
def test_natural_lines_pass(line):
    assert problems(line) == [], (line, problems(line))


def test_each_rule_names_the_fix():
    assert "pitong buwan" in problems("7 buwan na ang lumipas.")[0]
    assert "tatlong taon" in problems("3 taon ang termino.")[0]
    assert "24 months" in problems("24 buwan ang lumipas.")[0]
    # Bryce, 2026-11-26: "Isang chief justice", not "one chief justice"; "Isang pangulo", not "one pangulo".
    assert "isang chief" in problems("1 chief justice lang ang uupo.")[0]
    assert "isang pangulo" in problems("one pangulo lang")[0]
    assert "tatlong taon" in problems("3 years ang termino.")[0]
    assert "ikapitong" in problems("sa 7th month ng 2026")[0]
    assert "digits" in problems("Dalawampu't apat na senador ang bumoto.")[0]
    assert "trillion" in problems("₱19.66 trilyon ang utang.")[0]
    assert "%" in problems("55.9 porsyento ang boto.")[0]
    assert "July" in problems("noong Hulyo 15, 2026")[0]
    assert "ikapitong" in problems("sa ika-7 buwan")[-1]
    assert "Babayaran" in problems("Bayaran mo ba yon?")[0]
    assert "Gawin ba" in problems("Gawin ba yon ng Senado?")[0]
    assert "sa loob ng tatlong taon" in problems("Natapos ito sa 3 years.")[-1]
    # Bryce, 2026-11-25: "iyong" is "yung" (the/that) or "mo" (your); "sa iyo" and "yon" are fine.
    msg = problems("Hindi bill ang iyong share sa utang.")[0]
    assert "yung" in msg and "share mo" in msg
    assert problems("Iyong budget na yon ang pinag-uusapan.")
    assert "spell it" in problems("'Yung budget na yon ang pinag-uusapan.")[0]
    assert "after ng or sa" in problems("Tumaas ang presyo ng yung bigas.")[0]
    assert problems("Yung budget na yon, napunta sa bahay mo.") == []


def test_script_problems_name_the_scene():
    assert script_problems(["Okay ito.", "Bayaran mo ba yon?"])[0].startswith("scene 2: ")


def test_the_narrator_reads_the_natural_forms_in_english():
    assert spoken("sa unang pitong buwan ng 2026") == "sa unang pitong buwan ng twenty twenty-six"
    assert spoken("isang chief justice") == "isang chief justice"
    assert spoken("1 chief justice") == "one chief justice"          # why the script spells out "isang"
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
    assert '"7 buwan" becomes "pitong buwan"' in ed and '"1 chief justice" becomes "isang chief justice"' in ed
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
    clean = _script("Babayaran mo ba yon?", "Sa unang pitong buwan ng 2026, ₱1.37 trillion na ang nabayaran.")
    writers, calls = _fake_editor(monkeypatch, [clean])
    assert writers.narration_edit(clean) == clean and len(calls) == 1


def test_flagged_edit_gets_one_retry_with_the_problems(monkeypatch):
    bad = _script("Bayaran mo ba yon?", "Sa 7 buwan ng 2026, ₱1.37 trillion na ang nabayaran.")
    fixed = _script("Babayaran mo ba yon?", "Sa unang pitong buwan ng 2026, ₱1.37 trillion na ang nabayaran.")
    writers, calls = _fake_editor(monkeypatch, [bad, fixed])
    assert writers.narration_edit(bad) == fixed and len(calls) == 2
    assert calls[1][0] == "narration_editor"
    assert "scene 1:" in calls[1][1] and "scene 2:" in calls[1][1] and "Babayaran" in calls[1][1]


def test_worse_or_reshaped_retry_is_dropped_and_logged(monkeypatch, caplog):
    bad = _script("Bayaran mo ba yon?", "Okay ito.")
    worse = _script("Bayaran mo ba yon?", "3 taon na.")
    writers, calls = _fake_editor(monkeypatch, [bad, worse])
    with caplog.at_level("WARNING"):
        assert writers.narration_edit(bad) == bad
    assert "Taglish lint left 1 problem" in caplog.text
    reshaped = _script("Babayaran mo ba yon?")                       # lost a scene: never used
    writers, calls = _fake_editor(monkeypatch, [bad, reshaped])
    caplog.clear()
    with caplog.at_level("WARNING"):
        assert writers.narration_edit(bad) == bad and len(calls) == 2
    assert "Taglish lint left 1 problem" in caplog.text


def test_retry_that_changes_content_is_dropped(monkeypatch):
    """The retry runs after the fact check, so it may only change wording: no lost tag, number or sentence."""
    bad = _script("Sa 7 buwan ng 2026, ₱1.37 trillion na ang nabayaran. [S14][S7] Buwis ang pinagkukunan.")
    for retry in (_script("Sa unang pitong buwan ng 2026, ₱1.37 trillion na ang nabayaran. [S14] Buwis ang pinagkukunan."),
                  _script("Sa unang pitong buwan ng 2026, ₱1.4 trillion na ang nabayaran. [S14][S7] Buwis ang pinagkukunan."),
                  _script("Sa unang walong buwan ng 2026, ₱1.37 trillion na ang nabayaran. [S14][S7] Buwis ang pinagkukunan."),
                  _script("Buwis ang pinagkukunan. [S14][S7] 7 2026 ₱1.37")):
        writers, calls = _fake_editor(monkeypatch, [bad, retry])
        assert writers.narration_edit(bad) == bad, retry.scenes[0].text
    good = _script("Sa unang pitong buwan ng 2026, ₱1.37 trillion na ang nabayaran. [S14][S7] Galing yon sa buwis.")
    writers, calls = _fake_editor(monkeypatch, [bad, good])
    assert writers.narration_edit(bad) == good


def test_failed_retry_keeps_the_first_edit(monkeypatch, caplog):
    from tfs.agents import writers
    bad = _script("Bayaran mo ba yon?")
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
    original = _script("Bayaran mo ba yon?", "Okay ito.")
    writers, calls = _fake_editor(monkeypatch, [_script("Babayaran mo ba yon?")])
    assert writers.narration_edit(original) == original and len(calls) == 1


# ---------------------------------------------------------------- small counts (Bryce, 2026-11-26), review cases
def _says(line, fix):
    return any(fix in p for p in problems(line))


@pytest.mark.parametrize("line", [
    "Noong July 4 nagdeklara ang Senado.", "Sa June 5 magsisimula ang hearing.", "Grade 7 na estudyante siya.",
    "Ayon sa Executive Order 1 na inilabas noong 2022.", "Category 5 na bagyo ang tumama.", "Top 3 na probinsya.",
    "Sa 3rd and final reading, pumasa ang bill.", "Republic Act 9184 ang batas.", "Section 1 ng Article 11.",
    "Ten Commandments ang tawag dito.", "Mula 5 hanggang 20 years ang parusa.", "10:30 ng umaga nagsimula.",
])
def test_labels_dates_and_references_are_not_counts(line):
    assert problems(line) == [], (line, problems(line))


def test_zero_never_crashes():
    problems("Sa 0 araw ng palugit, wala nang extension.")          # used to raise KeyError: 0


def test_bare_counts_and_big_tagalog_words_are_caught():
    assert _says("1 lang ang bumoto.", '"isa lang"')
    assert _says("2 o 3 senador ang nag-abstain.", '"dalawa o"') and _says("2 o 3 senador", '"tatlong senador"')
    assert _says("1 sa bawat 3 Pilipino ang may utang.", '"isa sa"')
    for big in ("isang daang taon", "dalawang daang libo", "sandaang tao", "sampung libong piso",
                "isang trilyong piso", "limang bilyong piso"):
        assert _says(f"Umabot sa {big} ang halaga.", "digits"), big
    assert _says("Tumaas nang tatlong porsyento ang presyo.", "percent sign")


def test_retry_may_spell_out_small_counts_but_not_change_or_swap_them(monkeypatch):
    bad = _script("Tatlong senador at 2 congressman ang bumoto noong 2026, sa ika-7 buwan.")
    spelled = _script("Tatlong senador at dalawang congressman ang bumoto noong 2026, sa ikapitong buwan.")
    swapped = _script("Dalawang senador at tatlong congressman ang bumoto noong 2026, sa ikapitong buwan.")
    added = _script("Tatlong senador at dalawang congressman at limang mayor ang bumoto noong 2026, sa ikapitong buwan.")
    writers, calls = _fake_editor(monkeypatch, [bad, spelled])
    assert writers.narration_edit(bad) == spelled
    for retry in (swapped, added):
        writers, calls = _fake_editor(monkeypatch, [bad, retry])
        assert writers.narration_edit(bad) == bad, retry.scenes[0].text


def test_voice_and_fact_check_briefs_keep_small_counts_as_words(monkeypatch, tmp_path):
    qa = _brief(monkeypatch, tmp_path, "audio_qa")
    fc = _brief(monkeypatch, tmp_path, "fact_checker")
    assert "never in Tagalog number words" not in qa and "Small\ncounts of 1 to 10 stay Tagalog words" in qa
    assert "small counts of 1 to 10 stay Tagalog words" in fc


def test_yon_pwede_and_law_dates(monkeypatch, tmp_path):
    """Bryce, 2026-11-27: "yon sounds more natural", "pwede is what we normally use", and law dates as
    "ikalawang Lunes ng Mayo"."""
    assert _says("Average iyon, hindi bill.", '"yon"')
    assert _says("Puwede bang magbayad?", '"pwede"')
    assert _says("tuwing second Monday ng May ang eleksyon", '"ikalawang Lunes"')
    for ok in ("Average yon, hindi bill.", "Pwede bang magbayad ang gustong tumulong?",
               "Tuwing ikalawang Lunes ng Mayo ang eleksyon, ayon sa Article 6, Section 8.",
               "Babayaran mo ba yon?"):
        assert problems(ok) == [], (ok, problems(ok))
    assert _says("Bayaran mo ba yon?", "Babayaran")
    ed = _brief(monkeypatch, tmp_path, "narration_editor")
    assert '"iyon" (that) becomes "yon"' in ed and '"ikalawang Lunes ng\n   Mayo"' in ed

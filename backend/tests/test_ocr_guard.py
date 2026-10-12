"""The OCR check's corrections are applied only where safe (`translator/ocr/guard.py`)."""

from translator.ocr.guard import guard


def test_small_misreadings_are_fixed_and_rewordings_held_back():
    original = "| 1 | Kabelprische im Kellergeschoss nicht geerdet | 30.04.2026 |\n\nDie Mängel sind zu beseitigen."
    checked = "| 1 | Kabelpritsche im Kellergeschoss nicht geerdet | 30.04.2025 |\n\nDie Mängel sind unverzüglich zu beheben."
    md, applied, held = guard(original, checked)
    assert md == "| 1 | Kabelpritsche im Kellergeschoss nicht geerdet | 30.04.2026 |\n\nDie Mängel sind zu beseitigen."
    assert applied == ["“Kabelprische” → “Kabelpritsche”"]
    assert held == ["“2026” → “2025”?", "the checker reads more here: “unverzüglich”", "“beseitigen” → “beheben”?"]


def test_the_text_layer_confirms_bigger_fixes_and_repeats_are_dropped():
    md, applied, held = guard("Die Frist endet am 30.04.2025.", "Die Frist endet am 30.04.2026.",
                                        text_layer="Die Frist endet am 30.04.2026.")
    assert md == "Die Frist endet am 30.04.2026." and applied and not held  # a number, but the PDF says so
    md, applied, _ = guard("Die Anlage. Die Anlage.", "Die Anlage.")
    assert md == "Die Anlage." and applied == ["repeated text removed: “Die Anlage.”"]


def test_in_chinese_a_change_needs_the_text_layer():
    # 复查 → 检查 is one character, and another word: held back on a scan…
    md, applied, held = guard("本次复查范围为", "本次检查范围为")
    assert md == "本次复查范围为" and not applied and held == ["“本次复查范围为” → “本次检查范围为”?"]
    # …applied when the PDF's text layer has it, with its neighbours.
    md, applied, _ = guard("地下室电缆桥架末接地。", "地下室电缆桥架未接地。", text_layer="地下室电缆桥架未接地。")
    assert md == "地下室电缆桥架未接地。" and applied == ["“电缆桥架末接地。” → “电缆桥架未接地。”"]


def test_the_checker_cannot_restructure_the_page():
    original = "## 1. Gegenstand\n\n| A | B |\n| --- | --- |\n| 1 | 2 |"
    md, applied, held = guard(original, "1. Gegenstand\n\n| A | B | 1 | 2 |")
    assert md == original and not applied and not held  # markdown structure is the first reading's


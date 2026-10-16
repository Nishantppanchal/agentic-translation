"""Two readings compared word by word (ocr/compare.py), the arbiter's and the check's replies, and the guard."""

from __future__ import annotations

import io

from PIL import Image

from translator.agents.steps.settle import decide
from translator.document.pages import enlarged
from translator.models.replies import parse_arbitration, parse_ocr_fixes
from translator.ocr import compare
from translator.ocr.guard import apply_fixes, guard


def test_markup_spacing_case_hyphens_and_widths_are_no_differences():
    ours = "# Prüfbericht\n\nDie **Kabel-\npritsche** ist im KELLER. Projekt ＵＷ－２２９１, 16 mm²\n\n| Nr | Frist |\n|---|---|\n| 1 | 30.04. |"
    theirs = "Prüfbericht\nDie Kabelpritsche ist im Keller. Projekt UW-2291, 16 mm2\nNr Frist 1 30.04."
    assert compare.disputes(ours, theirs) == []


def test_a_difference_knows_where_it_is_in_both_readings():
    ours = "Die **Kabelprische** ist nicht geerdet. Frist 30.04.2026."
    theirs = "Die Kabelpritsche ist geerdet. Frist 30.04.2028."
    found = compare.disputes(ours, theirs)
    assert [(d.ours, d.theirs) for d in found] == [("Kabelprische", "Kabelpritsche"), ("nicht", ""), ("2026", "2028")]
    assert found[0].before == "Die" and found[0].after == "ist nicht geerdet"
    assert ours[slice(*found[2].span)] == "2026" and theirs[slice(*found[2].their_span)] == "2028"
    # the other version put in where chosen: the markup around it stays, a word taken out leaves one space
    assert compare.apply(ours, found, [0, 1]) == "Die **Kabelpritsche** ist geerdet. Frist 30.04.2026."
    assert compare.rate(ours, found) == 100 * 3 / 9  # "30.04.2026" is three words


def test_text_only_the_other_reading_has_goes_in_apart_from_its_neighbours():
    ours, theirs = "| 1 | Kabelpritsche |", "1 Kabelpritsche fehlt"
    [d] = compare.disputes(ours, theirs)
    assert (d.ours, d.theirs) == ("", "fehlt")
    assert compare.apply(ours, [d], [0]) == "| 1 | Kabelpritsche fehlt |"


def test_chinese_is_compared_character_by_character():
    found = compare.disputes("止步，高压危险！\n禁止合闸\n有人工作", "止步，高压险！\n禁止合同\n有人工作")
    assert [(d.ours, d.theirs) for d in found] == [("危", ""), ("闸", "同")]
    assert compare.apply("止步，高压危险！\n禁止合闸", found, [1]) == "止步，高压危险！\n禁止合同"


def test_the_arbiters_answers_decide():
    ours = "Die Kabelprische ist nicht geerdet. Frist 30.04.2026."
    found = compare.disputes(ours, "Die Kabelpritsche ist geerdet. Frist 30.04.2028.")
    settled = decide(ours, found, {1: "Kabelpritsche", 2: "nicht", 3: "?"})
    assert settled.text == "Die Kabelpritsche ist nicht geerdet. Frist 30.04.2026."
    assert len(settled.changed) == 1 and "Kabelprische" in settled.changed[0] and "Kabelpritsche" in settled.changed[0]
    assert len(settled.open) == 1 and "2026" in settled.open[0] and "2028" in settled.open[0]
    # reading neither version is left open, with what the arbiter read
    assert "the OCR check read “2027”" in decide(ours, found, {3: "2027"}).open[-1]
    # "(nothing)" is a version too: the second reading had no word there
    assert decide(ours, found, {2: "(nothing)"}).text == "Die Kabelprische ist geerdet. Frist 30.04.2026."


def test_replies_parsed():
    assert parse_arbitration("1: Kabelpritsche\n2: ?\n 3. 禁止合闸\nnoise") == {1: "Kabelpritsche", 2: "?", 3: "禁止合闸"}
    ok, fixes, page = parse_ocr_fixes("<verdict>fixed</verdict>\n<fix>\n<read>wird abgenomen.</read>\n"
                                      "<printed>wird abgenommen.</printed>\n</fix>")
    assert (ok, fixes, page) == (False, [("wird abgenomen.", "wird abgenommen.")], None)
    assert parse_ocr_fixes("<verdict>ok</verdict>")[0] is True
    assert parse_ocr_fixes("<verdict>fixed</verdict>\n<markdown>\nganze Seite\n</markdown>")[2] == "ganze Seite"


def test_amendments_are_made_where_their_words_are_found():
    page = "Die Anlage\nwird abgenomen."
    fixed, missing = apply_fixes(page, [("Anlage wird abgenomen", "Anlage wird abgenommen"), ("nicht da", "x")])
    assert fixed == "Die Anlage wird abgenommen." and missing == [("nicht da", "x")]


def test_full_width_and_normal_characters_are_the_same_for_the_guard():
    """A checker writing 2026 for ２０２６ isn't a misreading: nothing changed, nothing listed."""
    page = "日期：２０２６年３月１４日 · ＵＷ－２２９１"
    assert guard(page, "日期：2026年3月14日 · UW-2291", "") == (page, [], [])


def _png(w: int, h: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(out, "PNG")
    return out.getvalue()


def test_small_images_are_enlarged_for_the_readers():
    size = lambda png: Image.open(io.BytesIO(png)).size  # noqa: E731
    assert size(enlarged(_png(542, 417), 1000)) == (1084, 834)  # at least 2×
    assert size(enlarged(_png(159, 122), 1000)) == (477, 366)  # at most 3×
    assert size(enlarged(_png(520, 737), 1600)) == (1129, 1600)  # to the size wanted
    big = _png(1240, 1755)
    assert enlarged(big, 1600) is big  # an A4 page at 150 dpi: as it is
    assert size(enlarged(_png(900, 1300), 1600, max_pixels=2_000_000))[0] <= 1180  # never past what models take

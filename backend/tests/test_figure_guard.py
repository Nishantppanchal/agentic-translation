"""Which layout regions are really pictures (ocr/figures.py): checks that need no model."""

from __future__ import annotations

import pymupdf
import pytest

from translator.agents import steps
from translator.config import get_settings
from translator.document.pages import load_pages
from translator.models.replies import parse_figure_reply
from translator.ocr.figures import judge

PAGE = (1000.0, 1400.0)
PICTURE = (100.0, 300.0, 700.0, 800.0)


def _region(label, box, score=0.9):
    return {"label": label, "score": score, "box": list(box)}


def test_a_picture_with_nothing_against_it_is_kept():
    assert judge(PICTURE, "image", 0.9, PAGE, [_region("image", PICTURE)], []) is None


def test_a_text_block_the_layout_also_read_as_text_is_not_a_picture():
    twin = (102.0, 305.0, 698.0, 796.0)
    regions = [_region("image", PICTURE, 0.6), _region("text", twin, 0.58)]
    assert judge(PICTURE, "image", 0.6, PAGE, regions, []) == "layout-text"
    # A much more confident picture is not overruled by a weak text reading.
    assert judge(PICTURE, "image", 0.95, PAGE, [_region("text", twin, 0.4)], []) is None


def test_a_box_mostly_covered_by_text_regions_is_text():
    lines = [_region("text", (100.0, 300.0 + 60 * i, 700.0, 350.0 + 60 * i)) for i in range(8)]  # 8 paragraphs
    assert judge(PICTURE, "image", 0.9, PAGE, lines, []) == "layout-text"


def test_a_chart_keeps_its_labels():
    labels = [_region("text", (120.0, 320.0 + 90 * i, 260.0, 345.0 + 90 * i)) for i in range(5)]  # axis labels
    assert judge(PICTURE, "chart", 0.8, PAGE, labels, []) is None


def test_specks_and_whole_pages_are_not_pictures():
    assert judge((10.0, 10.0, 40.0, 40.0), "image", 0.9, PAGE, [], []) == "size"
    assert judge((0.0, 0.0, 990.0, 1390.0), "image", 0.9, PAGE, [], []) == "size"
    assert judge((10.0, 10.0, 50.0, 60.0), "seal", 0.9, PAGE, [], []) is None  # a small stamp still counts


def test_a_seal_is_never_overruled_by_the_text_under_it():
    seal = (500.0, 900.0, 800.0, 1200.0)
    assert judge(seal, "seal", 0.7, PAGE, [_region("text", seal, 0.9)], []) is None


def test_a_born_digital_paragraph_labelled_image_is_text():
    doc = pymupdf.open()
    page = doc.new_page()
    paragraph = ("Die Anlage besteht aus einem Schaltschrank, einer Kabelpritsche und der Erdung im Keller. "
                 "Alle Mängel aus der ersten Begehung sind beseitigt, die Prüfprotokolle liegen der Akte bei. ") * 3
    page.insert_textbox(pymupdf.Rect(72, 100, 520, 300), paragraph, fontsize=11)
    [p] = load_pages(doc.tobytes(), "a.pdf", dpi=150)
    [block] = p.text_blocks
    box = (block[0] - 6, block[1] - 6, block[2] + 6, block[3] + 6)  # the layout's box around the paragraph
    size = (612 * 150 / 72, 792 * 150 / 72)
    assert judge(box, "image", 0.9, size, [_region("image", box)], p.text_blocks) == "text-layer"
    assert p.text_layer_outside([box]).strip() == ""  # the figure's text is left out of the layer the OCR is held to
    assert "Schaltschrank" in p.text_layer_outside([])


@pytest.mark.parametrize(
    "reply, expected",
    [
        ("<kind>text</kind>\n<text>\nDie Anlage ist abgenommen.\n</text>", ("text", "Die Anlage ist abgenommen.")),
        ("<kind>picture</kind>\n<text>\n<none/>\n</text>", ("picture", "")),
        ("Schaltschrank", ("picture", "Schaltschrank")),  # a model that ignores the format: a picture, nothing lost
        ('{"kind": "text", "text": "Ergebnis"}', ("text", "Ergebnis")),
    ],
)
def test_the_figure_check_reply(reply, expected):
    assert parse_figure_reply(reply) == expected


def test_changing_the_figure_settings_reads_the_page_again(monkeypatch):
    [page] = load_pages(_one_page(), "a.pdf")
    before = steps.page.signature(page)
    monkeypatch.setattr(get_settings(), "layout_thresholds", {"image": 0.7})
    assert steps.page.signature(page) != before
    monkeypatch.setattr(get_settings(), "figure_check", "off")
    assert steps.page.signature(page) != before


def _one_page() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Ergebnis der Prüfung")
    return doc.tobytes()

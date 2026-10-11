"""Layout-preserving PDF: align segments to the PDF's lines, erase the source, typeset the translation."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from translator.filters.align import align, markdown_grid
from translator.filters.pdf_layout import render

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "abnahmeprotokoll.pdf"


def _png() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 40), False)
    pix.clear_with(180)
    return pix.tobytes("png")


def _pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 80), "Wartungsbericht Keller", fontsize=18, fontname="hebo")
    page.insert_textbox(pymupdf.Rect(72, 100, 520, 160),
                        "Die Anlage im Kellergeschoss wurde am zweiten April vollständig geprüft und dokumentiert.", fontsize=11)
    # Borderless table; the last column sits right next to the description (same PDF line).
    page.draw_rect(pymupdf.Rect(72, 175, 400, 190), color=None, fill=(0.85, 0.85, 0.85))  # header shading
    page.insert_text((76, 186), "Beschreibung", fontsize=10, fontname="hebo")
    page.insert_text((300, 186), "Frist", fontsize=10, fontname="hebo")
    page.insert_text((76, 204), "Kabelpritsche nicht geerdet 30.04.2026", fontsize=10)
    page.insert_image(pymupdf.Rect(72, 230, 192, 310), stream=_png())
    # A short word boxed in by neighbours (right and below): its long translation can't fit → overflow.
    page.insert_text((76, 342), "Kurz", fontsize=11)
    page.insert_text((150, 342), "Nachbar", fontsize=11)
    page.insert_text((76, 358), "Darunter steht noch etwas", fontsize=11)
    return doc.tobytes()


SEGMENTS = [
    {"id": "p1.1", "page": 1, "kind": "heading", "source": "# Wartungsbericht Keller", "translatable": True},
    {"id": "p1.2", "page": 1, "kind": "paragraph",
     "source": "Die Anlage im Kellergeschoss wurde am zweiten April vollständig geprüft und dokumentiert.", "translatable": True},
    {"id": "p1.3", "page": 1, "kind": "table",
     "source": "| Beschreibung | Frist |\n|---|---|\n| Kabelpritsche nicht geerdet | 30.04.2026 |", "translatable": True},
    {"id": "p1.4", "page": 1, "kind": "paragraph", "source": "Kurz", "translatable": True},
    {"id": "p1.5", "page": 1, "kind": "paragraph", "source": "Dieser Absatz steht nicht im PDF.", "translatable": True},
]
TARGETS = {
    "p1.1": "# Maintenance report basement",
    "p1.2": "The basement installation was fully inspected and documented on the second of April.",
    "p1.3": "| Description | Deadline |\n|---|---|\n| Cable tray not earthed | 30.04.2026 |",
    "p1.4": "This translation is far too long to ever fit into the tiny box that held one short German word, "
            "even when shrunk to the smallest allowed size, so it must be reported as an overflow.",
    "p1.5": "This paragraph is not in the PDF.",
}


def test_render_replaces_text_in_place_and_keeps_graphics():
    original = pymupdf.open(stream=_pdf(), filetype="pdf")
    pdf, report = render(_pdf(), SEGMENTS, TARGETS)
    out = pymupdf.open(stream=pdf, filetype="pdf")
    text = out[0].get_text()

    assert "Maintenance report basement" in text and "Wartungsbericht" not in text
    assert "fully inspected and documented" in text and "Kellergeschoss" not in text
    assert "Cable tray not earthed" in text and "Kabelpritsche" not in text
    assert "Deadline" in text and "30.04.2026" in text  # the date shared its line with the cell, and survived
    # Images, vector graphics and shading are untouched.
    assert len(out[0].get_images()) == len(original[0].get_images()) == 1
    assert len(out[0].get_drawings()) == len(original[0].get_drawings())

    seg = report["segments"]
    assert seg["p1.4"]["status"] == "overflow" and "Kurz" in text  # couldn't fit → source kept, reported
    assert seg["p1.5"]["status"] == "unaligned"
    assert {seg[i]["status"] for i in ("p1.1", "p1.2", "p1.3")} <= {"fit", "shrunk"}
    assert all(b["page"] == 1 and len(b["rect"]) == 4 for b in seg["p1.2"]["boxes"])
    assert report["summary"]["overflow"] == 1 and report["summary"]["unaligned"] == 1


def test_paragraph_across_a_page_break_is_split_between_pages():
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(72, 700, 520, 790),
                                  "Die Gewährleistungsfrist für alle Leistungen des Auftragnehmers beginnt mit dem Tag der", fontsize=11)
    doc.new_page().insert_textbox(pymupdf.Rect(72, 72, 520, 120), "förmlichen Abnahme durch den Auftraggeber.", fontsize=11)
    seg = {"id": "p1.1", "page": 1, "kind": "paragraph", "pages": [1, 2], "translatable": True,
           "source": "Die Gewährleistungsfrist für alle Leistungen des Auftragnehmers beginnt mit dem Tag der förmlichen Abnahme durch den Auftraggeber."}
    pdf, report = render(doc.tobytes(), [seg], {"p1.1": "The warranty period for all of the contractor's services begins on the day of formal acceptance by the client."})
    out = pymupdf.open(stream=pdf, filetype="pdf")
    p1, p2 = out[0].get_text(), out[1].get_text()
    assert "Gewährleistungsfrist" not in p1 and "Auftraggeber" not in p2
    assert "warranty" in p1 and "client" in p2
    assert sorted(b["page"] for b in report["segments"]["p1.1"]["boxes"]) == [1, 2]


def test_cjk_translation_is_typeset():
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(72, 72, 520, 120), "Die Anlage wird unter Vorbehalt abgenommen.", fontsize=12)
    seg = {"id": "p1.1", "page": 1, "kind": "paragraph", "source": "Die Anlage wird unter Vorbehalt abgenommen.", "translatable": True}
    pdf, report = render(doc.tobytes(), [seg], {"p1.1": "设备在上述缺陷整改完成前有条件验收。"})
    assert "有条件验收" in pymupdf.open(stream=pdf, filetype="pdf")[0].get_text()
    assert report["segments"]["p1.1"]["status"] in {"fit", "shrunk"}
    assert len(pdf) < 200_000  # fonts (incl. the large CJK fallback) are subset, not embedded whole


def test_real_sample_aligns_every_segment():
    segs = [
        ("p1.1", "heading", "# Abnahmeprotokoll – Umspannwerk Nord"),
        ("p1.3", "heading", "## 1. Gegenstand der Abnahme"),
        ("p1.6", "table", "| Nr. | Beschreibung | Frist |\n| --- | --- | --- |\n| 1 | Kabelpritsche im Kellergeschoss nicht geerdet | 30.04.2026 |\n"
                          "| 2 | Beschriftung der Abgangsfelder unvollständig | 15.04.2026 |\n| 3 | Restarbeiten am Zwischenkreis der USV-Anlage | 30.04.2026 |"),
        ("p2.1", "heading", "## 3. Ergebnis"),
    ]
    targets = {"p1.1": "# Acceptance Report", "p1.3": "## 1. Subject of Acceptance", "p2.1": "## 3. Result",
               "p1.6": "| No. | Description | Deadline |\n|---|---|---|\n| 1 | Cable tray in basement not earthed | 30.04.2026 |\n"
                       "| 2 | Labelling of outgoing bays incomplete | 15.04.2026 |\n| 3 | Remaining work on the UPS DC link | 30.04.2026 |"}
    doc = pymupdf.open(SAMPLE)
    result = align(doc, [{"id": i, "page": int(i[1]), "kind": k, "source": s, "translatable": True} for i, k, s in segs], targets)
    assert result.unaligned == []
    # "1. Gegenstand der Abnahme" must land on its own heading, not on the paragraph repeating the phrase.
    heading = next(u for u in result.units if u.segment_id == "p1.3")
    assert [ln.text for ln in heading.lines] == ["1. Gegenstand der Abnahme"]
    # Row 3's description shares a PDF line with its date: only the description words are taken.
    row3 = next(u for u in result.units if u.segment_id == "p1.6" and u.cell == (3, 1))
    assert row3.rects and len(row3.rects) == 5


def test_markdown_grid_skips_the_separator_row():
    assert markdown_grid("| a | b |\n| :--- | ---: |\n| 1 | 2 |") == [["a", "b"], ["1", "2"]]


def test_headers_and_footers_are_translated_in_place():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 40), "Vertraulich – nur für den internen Gebrauch", fontsize=8)
    page.insert_textbox(pymupdf.Rect(72, 100, 520, 140), "Die Anlage wird unter Vorbehalt abgenommen.", fontsize=11)
    page.insert_text((260, 810), "Seite 1 von 1", fontsize=8)
    segs = [
        {"id": "p1.1", "page": 1, "kind": "header", "source": "Vertraulich – nur für den internen Gebrauch", "translatable": True},
        {"id": "p1.2", "page": 1, "kind": "paragraph", "source": "Die Anlage wird unter Vorbehalt abgenommen.", "translatable": True},
        {"id": "p1.3", "page": 1, "kind": "footer", "source": "Seite 1 von 1", "translatable": True},
    ]
    pdf, report = render(doc.tobytes(), segs, {"p1.1": "Confidential – internal use only",
                                                 "p1.2": "The plant is accepted with reservations.", "p1.3": "Page 1 of 1"})
    text = pymupdf.open(stream=pdf, filetype="pdf")[0].get_text()
    assert "Confidential – internal use only" in text and "Page 1 of 1" in text
    assert "Vertraulich" not in text and "Seite" not in text
    assert {r["status"] for r in report["segments"].values()} <= {"fit", "shrunk"}


def test_furniture_and_repeated_sentences_across_pages():
    """A paragraph running over the page break must not swallow the footer in between; a sentence printed on
    both pages goes to each page's own segment even when the PDF's text order on page 1 differs from the
    reading order; a footer inside the bottom margin keeps a box to be set in."""
    from translator.filters.align import align
    from translator.filters.pdf_layout import render

    doc = pymupdf.open()
    repeat = "Der Auftragnehmer meldet die Fertigstellung schriftlich."
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 300), repeat, fontsize=11)  # drawn first: first in the text layer, though lower on the page
    p1.insert_text((72, 40), "Umspannwerk Nord · Projekt UW-2291", fontsize=9)
    p1.insert_text((72, 120), "Die Anlage wurde am 20.05.2026 geprüft.", fontsize=11)
    p1.insert_text((72, 760), "Die Restarbeiten an der USV-Anlage werden", fontsize=11)
    p1.insert_text((72, 820), "Seite 1 von 2", fontsize=9)
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 40), "Umspannwerk Nord · Projekt UW-2291", fontsize=9)
    p2.insert_text((72, 80), "im Juni durchgeführt.", fontsize=11)
    p2.insert_text((72, 200), repeat, fontsize=11)
    p2.insert_text((72, 820), "Seite 2 von 2", fontsize=9)
    data = doc.tobytes()
    segs = [
        {"id": "p1.1", "page": 1, "kind": "header", "source": "Umspannwerk Nord · Projekt UW-2291", "translatable": True},
        {"id": "p1.2", "page": 1, "kind": "paragraph", "source": "Die Anlage wurde am 20.05.2026 geprüft.", "translatable": True},
        {"id": "p1.3", "page": 1, "kind": "paragraph", "source": repeat, "translatable": True},
        {"id": "p1.4", "page": 1, "pages": [1, 2], "kind": "paragraph",
         "source": "Die Restarbeiten an der USV-Anlage werden im Juni durchgeführt.", "translatable": True},
        {"id": "p1.5", "page": 1, "kind": "footer", "source": "Seite 1 von 2", "translatable": True},
        {"id": "p2.1", "page": 2, "kind": "header", "source": "Umspannwerk Nord · Projekt UW-2291", "translatable": True},
        {"id": "p2.2", "page": 2, "kind": "paragraph", "source": repeat, "translatable": True},
        {"id": "p2.3", "page": 2, "kind": "footer", "source": "Seite 2 von 2", "translatable": True},
    ]
    targets = {
        "p1.1": "Substation North · Project UW-2291", "p1.2": "The system was inspected on 20 May 2026.",
        "p1.3": "The Contractor reports completion in writing.", "p1.4": "The remaining work on the UPS system will be done in June.",
        "p1.5": "Page 1 of 2", "p2.1": "Substation North · Project UW-2291",
        "p2.2": "The Contractor reports completion in writing.", "p2.3": "Page 2 of 2",
    }
    a = align(pymupdf.open(stream=data), segs, targets)
    pages = {u.segment_id: {ln.page for ln in u.lines} for u in a.units}
    assert a.unaligned == []
    assert pages["p1.3"] == {1} and pages["p2.2"] == {2}  # each copy on its own page
    assert pages["p1.4"] == {1, 2} and pages["p1.5"] == {1}  # the paragraph spans the break; the footer stays its own
    _, report = render(data, segs, targets)
    assert report["summary"]["overflow"] == 0 and report["summary"]["unaligned"] == 0, report["segments"]



def test_fuzzy_match_does_not_pull_in_a_neighbouring_table_cell():
    """OCR dropped characters in a paragraph, so the fuzzy window slides left onto the table's last row: the
    one-character cell "3" must not become part of the paragraph (it would be painted over)."""
    from translator.filters.align import Line, _Stream, norm

    texts = ["2026年4月30日", "3", "UPS直流母线遗留工作", "经现场核查，第1项缺陷已消缺：电缆桥架已加装16mm2黄绿双色铜芯接地跨接线，实测接地导通电",
             "阻为0.08Ω，满不于0.2Ω的要求。第2项缺陷已整改完毕，出线间隔标识齐全、清晰。第3项缺", "陷尚未消缺。",
             "乙方应在整改完成后5个工作日内书面通知甲方，并申请复验。", "图1：地下室设备概览"]
    lines = [Line(page=1, index=i, rect=pymupdf.Rect(0, i * 10, 100, i * 10 + 8), text=t, size=10, color=0, bold=False,
                  italic=False, block=0, key=norm(t)) for i, t in enumerate(texts)]
    stream = _Stream(lines)
    stream.claimed.update({0, 2})  # the row's other cells, already taken by the table
    key = norm("经现场核查，第1项缺陷已消缺：电缆桥架已加装16 mm²黄绿双色铜芯接地跨接线，实测接地导通电阻为0.08 Ω，满足不大于0.2 Ω的要求。"
               "第2项缺陷已整改完毕，出线间隔标识齐全、清晰。第3项缺陷尚未消缺。")
    found = stream.lines_in(*stream.find(key, 0))
    assert [ln.index for ln in found] == [3, 4, 5]

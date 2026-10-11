"""Office filters: Word / PowerPoint / Excel extract → write round trips, codes, and what is preserved."""

from __future__ import annotations

import io
import re
import zipfile

import pytest
from docx import Document
from lxml import etree
from openpyxl import load_workbook
from pptx import Presentation

from tests.fixtures_office import docx_full, pptx_deck, xlsx_book
from translator.filters import inline, office

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def pseudo(text: str) -> str:
    """Pseudo-translation: words upper-cased and lengthened, codes untouched."""
    return re.sub(r"(<[^>]+>)|([^<]+)", lambda m: m[1] or (m[2].upper() + " ++" if m[2].strip() else m[2]), text)


def translate_all(segments: list[dict], fn=pseudo) -> list[dict]:
    return [{**s, "target": fn(s["source"])} if s["translatable"] else s for s in segments]


def part(data: bytes, name: str) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read(name).decode()


@pytest.mark.parametrize("fmt, build", [("docx", docx_full), ("pptx", pptx_deck), ("xlsx", xlsx_book)])
def test_writing_the_source_back_reads_the_same(fmt, build):
    data = build()
    segments, _ = office.extract(data, fmt)
    out, report = office.write(data, fmt, [{**s, "target": s["source"]} for s in segments])
    again, _ = office.extract(out, fmt)
    assert [(s["id"], s["source"], s["where"]) for s in again] == [(s["id"], s["source"], s["where"]) for s in segments]
    assert report["mismatch"] == [] and report["repaired"] == {}


def test_word_extract():
    segments, info = office.extract(docx_full(), "docx")
    by = {s["where"] + "|" + inline.strip(s["source"]): s for s in segments}
    assert info["tracked_changes"] == 2 and info["unit"] == "part"
    assert by["Body|Abnahmeprotokoll"]["kind"] == "heading"
    p = next(s for s in segments if "Kabelpritsche" in s["source"])
    assert p["source"] == 'Die <g id="1">Kabelpritsche</g> im Kellergeschoss ist <g id="2">nicht</g> geerdet.<x id="3"/>Frist: 30.04.2026'
    assert p["codes"] == {"1": "bold", "2": "italic", "3": "tab"}
    assert "Body|Die Anlage ist vollständig geerdet." in by  # tracked changes read as accepted
    assert by["Text box|Hinweis im Textfeld"]  # read once although stored twice
    assert [s["kind"] for s in segments if s["where"] in ("Header", "Footer")] == ["footer", "header"]
    field = next(s for s in segments if "Abschnitt" in s["source"])
    assert field["source"] == 'Details in Abschnitt <x id="1"/>Ergebnis der Prüfung<x id="2"/>.'  # result is text
    assert next(s for s in segments if s["where"] == "Footnote 1")["page"] == 2
    assert not by["Table 1|1"]["translatable"] and by["Table 1|1"]["target"] == "1"


def test_word_write_keeps_formatting_links_fields_controls_and_text_boxes():
    data = docx_full()
    segments, _ = office.extract(data, "docx")
    out, report = office.write(data, "docx", translate_all(segments), lang="en-GB")
    assert report["tracked_changes_accepted"] >= 2 and not report["mismatch"]
    doc = Document(io.BytesIO(out))
    para = next(p for p in doc.paragraphs if "KABELPRITSCHE" in p.text)
    runs = [(r.text, r.bold, r.italic) for r in para.runs]
    assert ("KABELPRITSCHE ++", True, None) in runs and ("NICHT ++", None, True) in runs and ("\t", None, None) in runs
    body = part(out, "word/document.xml")
    root = etree.fromstring(body.encode())
    # Hyperlink kept (same relationship), its text translated.
    link = next(root.iter(f"{W}hyperlink"))
    assert link.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") == "rIdLink1"
    assert "".join(link.itertext()) == "WEBSITE DES NETZBETREIBERS ++"
    # Field instruction untouched, visible result translated.
    assert " REF _Ref1 \\h " in body and "ERGEBNIS DER PRÜFUNG ++" in body
    # Content control kept around the translated text.
    sdt = next(root.iter(f"{W}sdt"))
    assert sdt.find(f"{W}sdtPr/{W}tag").get(f"{W}val") == "inspector" and "NAME EINTRAGEN ++" in "".join(sdt.itertext())
    # Tracked changes accepted: no revision marks, deleted text gone.
    assert "<w:ins " not in body and "<w:del " not in body and "nicht " not in body
    # The text box is translated in both copies (modern and fallback).
    assert body.count("HINWEIS IM TEXTFELD ++") == 2
    assert "GEMÄSS VOB/B § 12. ++" in part(out, "word/footnotes.xml") and "<w:footnoteRef/>" in part(out, "word/footnotes.xml")
    footer = next(n for n in zipfile.ZipFile(io.BytesIO(out)).namelist() if re.fullmatch(r"word/footer\d*\.xml", n))
    assert " PAGE " in part(out, footer) and "SEITE" in part(out, footer)  # field kept, text translated
    assert 'w:val="en-GB"' in part(out, "word/styles.xml")  # document language


def test_word_write_repairs_codes_and_skips_changed_paragraphs():
    data = docx_full()
    segments, _ = office.extract(data, "docx")
    p = next(s for s in segments if "Kabelpritsche" in s["source"])
    p_missing = {**p, "target": 'The <g id="1">cable tray</g> in the basement is not earthed. Deadline: 30.04.2026'}  # italic + tab lost
    other = next(s for s in segments if s["source"] == "Beschreibung")
    stale = {**other, "source": "Something else", "target": "Description"}
    out, report = office.write(data, "docx", [p_missing, stale])
    assert report["repaired"] == {p["id"]: ['lost the formatting of <g id="2">…</g>', 'appended <x id="3"/>']}
    assert report["mismatch"] == [other["id"]]
    text = next(par.text for par in Document(io.BytesIO(out)).paragraphs if "cable tray" in par.text)
    assert text.endswith("30.04.2026\t")
    assert any(c.text == "Beschreibung" for row in Document(io.BytesIO(out)).tables[0].rows for c in row.cells)


def test_powerpoint():
    data = pptx_deck()
    segments, info = office.extract(data, "pptx")
    rows = [(s["id"], s["kind"], s["where"], s["source"]) for s in segments]
    assert rows[0] == ("p1.1", "heading", "Slide 1 · Title 1", "Abnahme Umspannwerk Nord")
    assert ("p1.2", "paragraph", "Slide 1 · Content Placeholder 2", 'Erste Zeile<x id="1"/>nach dem Umbruch') in rows
    assert any(r[3] == '<g id="1">Wichtig: </g>Erdung prüfen' for r in rows)
    assert any(r[2] == "Slide 1 · Notes" for r in rows) and any(r[2].startswith("Slide 1 · Table") for r in rows)
    assert rows[-1][:2] == ("p2.1", "heading") and info["pages"] == 2
    out, report = office.write(data, "pptx", translate_all(segments), lang="en-GB")
    assert report["autofit"] >= 1  # text that grew may shrink to fit
    prs = Presentation(io.BytesIO(out))
    body = prs.slides[0].placeholders[1].text_frame
    assert body.paragraphs[0].text == "ERSTE ZEILE ++\x0bNACH DEM UMBRUCH ++"  # \x0b = line break
    assert [(r.text, r.font.bold) for r in body.paragraphs[1].runs] == [("WICHTIG:  ++", True), ("ERDUNG PRÜFEN ++", None)]
    assert prs.slides[0].notes_slide.notes_text_frame.text == "SPRECHERNOTIZ ZUR ABNAHME ++"
    assert 'lang="en-GB"' in part(out, "ppt/slides/slide1.xml") and 'lang="de' not in part(out, "ppt/slides/slide1.xml")
    assert "<a:normAutofit/>" in part(out, "ppt/slides/slide1.xml")


def test_excel_shared_strings_rich_text_formulas_and_numbers():
    data = xlsx_book()
    segments, info = office.extract(data, "xlsx")
    rows = [(s["id"], s["where"], s["source"], s["translatable"]) for s in segments]
    assert rows[0] == ("p1.1", "Mängel!A1 (+1 more)", "Beschreibung", True)  # one shared string, used twice
    assert ("p1.4", "Mängel!B2", "2026", False) in rows
    assert ("p1.5", "Mängel!A3", '<g id="1">Wichtig:</g> Erdung prüfen', True) in rows
    assert rows[-1] == ("p2.1", "Notizen!A1", "Nachbegehung geplant", True) and info["unit"] == "sheet"
    out, _ = office.write(data, "xlsx", translate_all(segments))
    wb = load_workbook(io.BytesIO(out), rich_text=True)
    ws = wb["Mängel"]
    assert wb.sheetnames == ["Mängel", "Notizen"]  # sheet names untouched (formulas refer to them)
    assert ws["A1"].value == ws["A4"].value == "BESCHREIBUNG ++" and ws["B2"].value == "2026"
    assert ws["C2"].value == "=LEN(A2)" and ws["B4"].value == 42
    rich = ws["A3"].value
    assert [str(b.text if hasattr(b, "text") else b) for b in rich] == ["WICHTIG: ++", " ERDUNG PRÜFEN ++"]
    assert rich[0].font.b


def test_formulas_follow_the_translation_of_the_text_they_compare_against():
    """=COUNTIF(A1:A3,"offen") would count 0 once "offen" is translated: the translated workbook updates the
    literal (case-insensitively, keeping a comparison prefix), so the result stays right."""
    import xlsxwriter

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("Mängel")
    ws.write("A1", "offen")
    ws.write("A2", "behoben")
    ws.write("A3", "offen")
    ws.write_formula("B1", '=COUNTIF(A1:A3,"offen")', None, 2)
    ws.write_formula("B2", '=COUNTIF(A1:A3,"<>OFFEN")', None, 1)
    ws.write_formula("B3", '=IF(A1="Mängel","x","y")', None, "y")  # "Mängel" isn't a translated cell text: unchanged
    wb.close()
    segments, info = office.extract(buf.getvalue(), "xlsx")
    by = {s["source"]: s for s in segments}
    assert by["offen"]["formula_refs"] == ['Mängel!B1: =COUNTIF(A1:A3,"offen")', 'Mängel!B2: =COUNTIF(A1:A3,"<>OFFEN")']
    assert info["in_formulas"] == 1 and "formula_refs" not in by["behoben"]
    out, report = office.write(buf.getvalue(), "xlsx", [{**by["offen"], "target": 'open "now"'}, {**by["behoben"], "target": "fixed"}])
    assert [(c["ref"], c["after"]) for c in report["formulas_updated"]] == [
        ("Mängel!B1", '=COUNTIF(A1:A3,"open ""now""")'), ("Mängel!B2", '=COUNTIF(A1:A3,"<>open ""now""")')]
    sheet = zipfile.ZipFile(io.BytesIO(out)).read("xl/worksheets/sheet1.xml").decode()
    assert 'COUNTIF(A1:A3,&quot;open &quot;&quot;now&quot;&quot;&quot;)' in sheet or 'COUNTIF(A1:A3,"open ""now""")' in sheet
    assert 'IF(A1="Mängel"' in sheet or "IF(A1=&quot;Mängel&quot;" in sheet


def test_bad_files_are_rejected():
    with pytest.raises(ValueError, match="zip"):
        office.extract(b"not a zip", "docx")
    with pytest.raises(ValueError, match="Word"):
        office.extract(xlsx_book(), "docx")


# --------------------------------------------------------------------------- #
# Inline codes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("target, problems", [
    ('Die <g id="1">Anlage</g><x id="2"/>', []),
    ('<x id="2"/>The <g id="1">plant</g>', []),  # moved: fine
    ('The plant<x id="2"/>', ['missing <g id="1">…</g>']),
    ('The <g id="1">plant</g><x id="2"/><x id="2"/>', ['unexpected <x id="2"/>']),
    ('The <g id="1">plant<x id="2"/>', ["a <g> is not closed (or closed twice)"]),
])
def test_validate(target, problems):
    assert inline.validate('Die <g id="1">Anlage</g><x id="2"/>', target) == problems


def test_normalize_and_repair():
    assert inline.normalize("The &lt;g id='1'&gt;plant&lt;/g&gt; <x id = \"2\" />") == 'The <g id="1">plant</g> <x id="2"/>'
    fixed, fixes = inline.repair('A <g id="1">b</g><x id="2"/>', 'X <g id="1">y</g> <g id="9">z</g>')
    assert fixed == 'X <g id="1">y</g> z<x id="2"/>'
    assert fixes == ['removed <g id="9">…</g>', 'appended <x id="2"/>']
    assert inline.display('Die <g id="1">Anlage</g><x id="2"/>') == "Die {1}Anlage{/1}{2}"


def test_office_views_link_every_text_to_its_segment():
    """The Document tab's sheet and slide views: every text cell / paragraph carries its segment id; numbers,
    formula results and slide geometry come from the file."""
    from pathlib import Path

    from translator.filters import office_view

    samples = Path(__file__).resolve().parents[2] / "samples"
    for name in ("quexian-qingdan.xlsx", "anquan-peixun.pptx"):
        data = (samples / name).read_bytes()
        fmt = name.rsplit(".", 1)[1]
        segs, _ = office.extract(data, fmt)
        v = office_view.view(data, fmt, segs)
        if fmt == "xlsx":
            cells = [c for sh in v["sheets"] for c in sh["cells"]]
            assert {c["seg"] for c in cells if c.get("seg")} == {s["id"] for s in segs}
            b4 = next(c for c in cells if c["ref"] == "B4" and c.get("formula"))
            assert b4["formula"] == '=COUNTIF(缺陷!F:F,"未整改")' and b4["value"] == "3" and b4["kind"] == "number"
            assert any(c["kind"] == "date" for c in cells) and v["sheets"][0]["cells"][0]["bold"]
        else:
            paras = [p for sl in v["slides"] for sh in sl["shapes"] for p in sh.get("paragraphs", [])]
            paras += [p for sl in v["slides"] for p in sl["notes"]]
            assert {p["seg"] for p in paras if p["seg"]} == {s["id"] for s in segs}
            boxes = [sh for sl in v["slides"] for sh in sl["shapes"]]
            assert all(0 <= b["x"] < 1 and 0 <= b["y"] < 1 and 0 < b["w"] <= 1 for b in boxes)
            assert v["slides"][0]["shapes"][0]["placeholder"] == "center_title" and v["slides"][0]["notes"]

"""Word, PowerPoint and Excel files: extract segments, write translations back into the original file.

What is translated:
- Word: body (with nested tables and text boxes), headers and footers, footnotes and endnotes. Text
  boxes are stored twice (a modern and a fallback copy); both get the translation.
- PowerPoint: slides in order (shapes, groups, tables) and speaker notes. Text that grows is set to
  shrink on overflow (normAutofit), as PowerPoint does itself.
- Excel: shared strings in the order they are first used, and inline strings. Formulas, sheet names
  and numbers are untouched.

A segment's `loc` ("part#n") finds its paragraph again on writing; `where` tells people where it is
("Table 2", "Slide 3 · Title", "Prices!B4"). The writer checks that each paragraph still reads the
same as the segment's source before replacing it, and reports anything it skips or repairs.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from . import inline
from .ooxml import (
    DRAWING,
    SHEET,
    WORD,
    A,
    Paragraph,
    S,
    W,
    accept_tracked_changes,
    fallback_twins,
    in_fallback,
    parser,
    q,
    read_paragraph,
    write_paragraph,
)

FORMATS = {".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx"}
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CHUNK_CHARS = 2500  # Word has no pages in the file: the body is split into parts of about this size
_LETTER = re.compile(r"[^\W\d_]")
UNIT_LABEL = {"docx": "part", "pptx": "slide", "xlsx": "sheet"}


def detect(filename: str) -> str | None:
    return FORMATS.get(Path(filename).suffix.lower())


class Package:
    """An OPC zip: parts parsed on demand, written back with the original order and compression."""

    def __init__(self, data: bytes):
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ValueError("Not a valid Office file (it isn't a zip package).") from exc
        self.names = set(self.zip.namelist())
        self.roots: dict[str, etree._Element] = {}
        self.changed: set[str] = set()

    def has(self, name: str) -> bool:
        return name in self.names

    def root(self, name: str):
        if name not in self.roots:
            self.roots[name] = etree.fromstring(self.zip.read(name), parser())
        return self.roots[name]

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        """rId → (target part, relationship type) for a part."""
        folder, base = posixpath.split(part)
        rels_name = posixpath.join(folder, "_rels", base + ".rels")
        if rels_name not in self.names:
            return {}
        out = {}
        for rel in self.root(rels_name).iter(f"{{{PKG_REL}}}Relationship"):
            if rel.get("TargetMode") == "External":
                continue
            target = posixpath.normpath(posixpath.join(folder, rel.get("Target", ""))).lstrip("/")
            out[rel.get("Id")] = (target, rel.get("Type", "").rsplit("/", 1)[-1])
        return out

    def save(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as out:
            for info in self.zip.infolist():
                if info.filename in self.changed:
                    data = etree.tostring(self.roots[info.filename], xml_declaration=True, encoding="UTF-8", standalone=True)
                else:
                    data = self.zip.read(info.filename)
                out.writestr(info, data, compress_type=info.compress_type)
        return buf.getvalue()


@dataclass
class Unit:
    loc: str
    part: str
    para: Paragraph
    dialect: object
    kind: str = "paragraph"
    where: str = ""
    page: int = 1
    twin: object = None  # the mc:Fallback copy of this paragraph
    body: object = None  # PowerPoint text body (for autofit)


def _paragraphs(pkg: Package, part: str, para_tag: str, dialect) -> Iterator[tuple[int, object, Paragraph, object]]:
    root = pkg.root(part)
    twins = fallback_twins(root, para_tag)
    fields: list[str] = []
    n = 0
    for el in list(root.iter(para_tag)):
        if in_fallback(el):
            continue
        para, fields = read_paragraph(el, dialect, fields)
        yield n, el, para, twins.get(el)
        n += 1


def _ancestor(el, *tags: str):
    parent = el.getparent()
    while parent is not None:
        if parent.tag in tags:
            return parent
        parent = parent.getparent()
    return None


# --------------------------------------------------------------------------- #
# Word
# --------------------------------------------------------------------------- #


def _heading_styles(pkg: Package) -> set[str]:
    if not pkg.has("word/styles.xml"):
        return set()
    out = set()
    for style in pkg.root("word/styles.xml").iter(q(W, "style")):
        name = (style.find(q(W, "name")).get(q(W, "val")) if style.find(q(W, "name")) is not None else "").lower()
        ppr = style.find(q(W, "pPr"))
        outline = ppr is not None and ppr.find(q(W, "outlineLvl")) is not None
        if name.startswith("heading") or name in ("title", "subtitle") or outline:
            out.add(style.get(q(W, "styleId")))
    return out


def _word_kind(el, headings: set[str]) -> str:
    ppr = el.find(q(W, "pPr"))
    style = ppr.find(q(W, "pStyle")) if ppr is not None else None
    if style is not None and style.get(q(W, "val")) in headings:
        return "heading"
    if ppr is not None and ppr.find(q(W, "outlineLvl")) is not None:
        return "heading"
    return "paragraph"


def docx_units(pkg: Package) -> Iterator[Unit]:
    main = "word/document.xml"
    if not pkg.has(main):
        raise ValueError("Not a Word document (word/document.xml is missing).")
    headings = _heading_styles(pkg)
    rels = pkg.rels(main)
    furniture = sorted((t, kind) for t, kind in rels.values() if kind in ("header", "footer") and pkg.has(t))
    for part, kind in furniture:
        for n, el, para, twin in _paragraphs(pkg, part, q(W, "p"), WORD):
            yield Unit(f"{part}#{n}", part, para, WORD, kind, kind.capitalize(), 1, twin)

    root = pkg.root(main)
    tables = {t: i for i, t in enumerate(root.iter(q(W, "tbl")), start=1)}
    page, size = 1, 0
    for n, el, para, twin in _paragraphs(pkg, main, q(W, "p"), WORD):
        kind = _word_kind(el, headings)
        length = len(para.plain)
        if size and (size + length > CHUNK_CHARS * 1.6 or (size > CHUNK_CHARS and kind == "heading")):
            page, size = page + 1, 0
        size += length
        if _ancestor(el, q(W, "txbxContent")) is not None:
            where = "Text box"
        elif (tbl := _ancestor(el, q(W, "tbl"))) is not None:
            where = f"Table {tables.get(tbl, '?')}"
        else:
            where = "Body"
        yield Unit(f"{main}#{n}", main, para, WORD, kind, where, page, twin)

    for part, name in (("word/footnotes.xml", "Footnote"), ("word/endnotes.xml", "Endnote")):
        if not pkg.has(part):
            continue
        for n, el, para, twin in _paragraphs(pkg, part, q(W, "p"), WORD):
            note = _ancestor(el, q(W, "footnote"), q(W, "endnote"))
            if note is None or note.get(q(W, "type")) in ("separator", "continuationSeparator", "continuationNotice"):
                continue
            yield Unit(f"{part}#{n}", part, para, WORD, "paragraph", f"{name} {note.get(q(W, 'id'))}", page + 1, twin)


# --------------------------------------------------------------------------- #
# PowerPoint
# --------------------------------------------------------------------------- #


def _shape_info(el) -> tuple[str, str | None, object]:
    shape = _ancestor(el, q(P, "sp"), q(P, "graphicFrame"))
    if shape is None:
        return "", None, None
    nv = next(shape.iter(q(P, "cNvPr")), None)
    ph = next(shape.iter(q(P, "ph")), None)
    body = _ancestor(el, q(P, "txBody"))
    if _ancestor(el, q(A, "tbl")) is not None:
        return "Table", None, None
    return (nv.get("name", "") if nv is not None else ""), (ph.get("type", "body") if ph is not None else None), body


def pptx_units(pkg: Package) -> Iterator[Unit]:
    pres = "ppt/presentation.xml"
    if not pkg.has(pres):
        raise ValueError("Not a PowerPoint presentation (ppt/presentation.xml is missing).")
    rels = pkg.rels(pres)
    slides = [rels[s.get(q(R, "id"))][0] for s in pkg.root(pres).iter(q(P, "sldId")) if s.get(q(R, "id")) in rels]
    for number, slide in enumerate(slides, start=1):
        if not pkg.has(slide):
            continue
        for n, el, para, twin in _paragraphs(pkg, slide, q(A, "p"), DRAWING):
            name, ph, body = _shape_info(el)
            kind = "heading" if ph in ("title", "ctrTitle") else "paragraph"
            yield Unit(f"{slide}#{n}", slide, para, DRAWING, kind, f"Slide {number}" + (f" · {name}" if name else ""), number, twin, body)
        notes = next((t for t, kind in pkg.rels(slide).values() if kind == "notesSlide" and pkg.has(t)), None)
        if notes:
            for n, el, para, twin in _paragraphs(pkg, notes, q(A, "p"), DRAWING):
                _, ph, body = _shape_info(el)
                if ph == "body":  # the notes text (not the slide image, number or date placeholders)
                    yield Unit(f"{notes}#{n}", notes, para, DRAWING, "paragraph", f"Slide {number} · Notes", number, twin, body)


# --------------------------------------------------------------------------- #
# Excel
# --------------------------------------------------------------------------- #


def xlsx_units(pkg: Package) -> Iterator[Unit]:
    book = "xl/workbook.xml"
    if not pkg.has(book):
        raise ValueError("Not an Excel workbook (xl/workbook.xml is missing).")
    rels = pkg.rels(book)
    sheets = [(s.get("name"), rels[s.get(q(R, "id"))][0]) for s in pkg.root(book).iter(q(S, "sheet")) if s.get(q(R, "id")) in rels]
    first: dict[int, tuple[int, str, str]] = {}
    uses: dict[int, int] = {}
    inline_cells: list[tuple[int, str, str, str, object]] = []
    for number, (name, path) in enumerate(sheets, start=1):
        if not pkg.has(path):
            continue
        for c in pkg.root(path).iter(q(S, "c")):
            t, ref = c.get("t"), c.get("r", "")
            if t == "s" and c.find(q(S, "v")) is not None:
                try:
                    idx = int(c.find(q(S, "v")).text)
                except (TypeError, ValueError):
                    continue
                first.setdefault(idx, (number, name, ref))
                uses[idx] = uses.get(idx, 0) + 1
            elif t == "inlineStr" and c.find(q(S, "is")) is not None:
                inline_cells.append((number, name, path, ref, c.find(q(S, "is"))))

    sst = "xl/sharedStrings.xml"
    if pkg.has(sst):
        items = list(pkg.root(sst).findall(q(S, "si")))
        for idx in sorted(first, key=lambda i: (first[i][0], _cell_order(first[i][2]))):
            if idx >= len(items):
                continue
            number, name, ref = first[idx]
            para, _ = read_paragraph(items[idx], SHEET)
            more = f" (+{uses[idx] - 1} more)" if uses[idx] > 1 else ""
            yield Unit(f"{sst}#{idx}", sst, para, SHEET, "paragraph", f"{name}!{ref}{more}", number)
    for number, name, path, ref, is_el in inline_cells:
        para, _ = read_paragraph(is_el, SHEET)
        yield Unit(f"{path}#{ref}", path, para, SHEET, "paragraph", f"{name}!{ref}", number)


def _cell_order(ref: str) -> tuple[int, int]:
    m = re.match(r"([A-Z]+)(\d+)", ref or "")
    if not m:
        return (0, 0)
    col = 0
    for ch in m[1]:
        col = col * 26 + ord(ch) - 64
    return int(m[2]), col


_LITERAL = re.compile(r'"((?:[^"]|"")*)"')


def formula_literals(pkg: Package) -> dict[str, list[str]]:
    """Text that formulas compare against (`=COUNTIF(E2:E4,"offen")`) → where: translating such a cell
    silently changes the formula's result."""
    book = "xl/workbook.xml"
    if not pkg.has(book):
        return {}
    rels = pkg.rels(book)
    out: dict[str, list[str]] = {}
    for s in pkg.root(book).iter(q(S, "sheet")):
        path = rels.get(s.get(q(R, "id")), ("", ""))[0]
        if not pkg.has(path):
            continue
        for c in pkg.root(path).iter(q(S, "c")):
            f = c.find(q(S, "f"))
            if f is None or not f.text:
                continue
            for lit in _LITERAL.findall(f.text):
                lit = _OPERATOR.match(lit.replace('""', '"')).group(2).strip()  # "<>offen" compares against "offen"
                if lit and _LETTER.search(lit):
                    out.setdefault(lit.casefold(), []).append(f"{s.get('name')}!{c.get('r')}: ={f.text}")
    return out


_OPERATOR = re.compile(r"^(<>|>=|<=|=|<|>)?(.*)$", re.S)


def update_formula_literals(pkg: Package, segments: list[dict]) -> list[dict]:
    """Formulas that compare against a cell text (`=COUNTIF(F:F,"未整改")`) follow that text's translation, so
    their results stay right in the translated workbook (instead of counting 0). Excel compares text
    case-insensitively; a comparison prefix ("<>未整改") is kept. → [{ref, before, after}]."""
    translations: dict[str, str] = {}
    for s in segments:
        if s.get("translatable", True) and s.get("target") and s["target"] != s["source"]:
            source = inline.strip(s["source"]).strip()
            if source:
                translations.setdefault(source.casefold(), inline.strip(s["target"]).strip())
    book = "xl/workbook.xml"
    if not translations or not pkg.has(book):
        return []

    def swap(m: re.Match) -> str:
        op, core = _OPERATOR.match(m.group(1).replace('""', '"')).groups()
        new = translations.get(core.strip().casefold())
        return m.group(0) if new is None else '"' + ((op or "") + new).replace('"', '""') + '"'

    rels = pkg.rels(book)
    changes = []
    for s in pkg.root(book).iter(q(S, "sheet")):
        path = rels.get(s.get(q(R, "id")), ("", ""))[0]
        if not pkg.has(path):
            continue
        for c in pkg.root(path).iter(q(S, "c")):
            f = c.find(q(S, "f"))
            if f is None or not f.text:
                continue
            text = _LITERAL.sub(swap, f.text)
            if text != f.text:
                changes.append({"ref": f"{s.get('name')}!{c.get('r')}", "before": f"={f.text}", "after": f"={text}"})
                f.text = text
                pkg.changed.add(path)
    return changes


WALKERS = {"docx": docx_units, "pptx": pptx_units, "xlsx": xlsx_units}


# --------------------------------------------------------------------------- #
# Extract / write
# --------------------------------------------------------------------------- #


def extract(data: bytes, fmt: str) -> tuple[list[dict], dict]:
    """→ (segments, info: pages, tracked changes, segments with codes)."""
    pkg = Package(data)
    segments: list[dict] = []
    counters: dict[int, int] = {}
    tracked = 0
    literals = formula_literals(pkg) if fmt == "xlsx" else {}
    for unit in WALKERS[fmt](pkg):
        tracked += unit.para.tracked
        text = unit.para.text
        if not unit.para.plain.strip():
            continue  # nothing to translate (empty, or only an image / field)
        counters[unit.page] = counters.get(unit.page, 0) + 1
        translatable = bool(_LETTER.search(unit.para.plain))
        seg = {
            "id": f"p{unit.page}.{counters[unit.page]}",
            "page": unit.page,
            "kind": unit.kind,
            "source": text,
            "target": None if translatable else text,
            "translatable": translatable,
            "where": unit.where,
            "loc": unit.loc,
        }
        if unit.para.labels:
            seg["codes"] = dict(unit.para.labels)
        if fmt == "xlsx" and (refs := literals.get(unit.para.plain.strip().casefold())):
            seg["formula_refs"] = refs[:3]
        segments.append(seg)
    pages = max((s["page"] for s in segments), default=0)
    info = {"pages": pages, "tracked_changes": tracked, "with_codes": sum(1 for s in segments if s.get("codes")),
            "unit": UNIT_LABEL[fmt], "in_formulas": sum(1 for s in segments if s.get("formula_refs"))}
    return segments, info


def _keep_outer_space(source: str, target: str) -> str:
    lead = source[: len(source) - len(source.lstrip())]
    trail = source[len(source.rstrip()):]
    return lead + target.strip() + trail if target.strip() else target


def write(data: bytes, fmt: str, segments: list[dict], lang: str | None = None) -> tuple[bytes, dict]:
    """Put translations into a copy of the original file → (file, report)."""
    pkg = Package(data)
    report = {"written": 0, "unchanged": 0, "mismatch": [], "repaired": {}, "tracked_changes_accepted": 0, "autofit": 0}
    by_loc = {s["loc"]: s for s in segments if s.get("loc")}
    if fmt == "docx":
        for part in [n for n in pkg.names if re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml", n)]:
            found = accept_tracked_changes(pkg.root(part))
            if found:
                report["tracked_changes_accepted"] += found
                pkg.changed.add(part)
        if lang:
            _set_docx_language(pkg, lang)

    growth: dict = {}
    for unit in WALKERS[fmt](pkg):
        seg = by_loc.get(unit.loc)
        if seg is None or not seg.get("translatable", True) or not seg.get("target"):
            continue
        if unit.para.text != seg["source"]:
            report["mismatch"].append(seg["id"])  # the file doesn't match the document any more
            continue
        if seg["target"] == seg["source"]:
            report["unchanged"] += 1
            continue
        target = _keep_outer_space(seg["source"], seg["target"])
        twin_text = read_paragraph(unit.twin, unit.dialect)[0].text if unit.twin is not None else None
        fixes = write_paragraph(unit.para, target, unit.dialect, lang)
        if unit.twin is not None:
            twin = read_paragraph(unit.twin, unit.dialect)[0]
            write_paragraph(twin, target if twin_text == seg["source"] else inline.strip(target), unit.dialect, lang)
        if fixes:
            report["repaired"][seg["id"]] = fixes
        report["written"] += 1
        pkg.changed.add(unit.part)
        if unit.body is not None:
            g = growth.setdefault(id(unit.body), [unit.body, 0, 0])
            g[1] += len(inline.strip(seg["source"]))
            g[2] += len(inline.strip(target))
    if fmt == "pptx":
        for body, before, after in growth.values():
            if before and after > before * 1.1 and _shrink_on_overflow(body):
                report["autofit"] += 1
    if fmt == "xlsx":
        report["formulas_updated"] = update_formula_literals(pkg, segments)
    return pkg.save(), report


def _shrink_on_overflow(body) -> bool:
    """Let PowerPoint shrink text that no longer fits (unless the shape already resizes to fit)."""
    bpr = body.find(q(A, "bodyPr"))
    if bpr is None or bpr.find(q(A, "spAutoFit")) is not None or bpr.find(q(A, "normAutofit")) is not None:
        return False
    for el in bpr.findall(q(A, "noAutofit")):
        bpr.remove(el)
    bpr.insert(0, etree.Element(q(A, "normAutofit")))
    # bodyPr children have a fixed order: prstTxWarp, (autofit), scene3d, sp3d, flatTx, extLst
    warp = bpr.find(q(A, "prstTxWarp"))
    if warp is not None:
        fit = bpr.find(q(A, "normAutofit"))
        bpr.remove(fit)
        warp.addnext(fit)
    return True


def _set_docx_language(pkg: Package, lang: str) -> None:
    """Default language of the document = the target language (spell-check, hyphenation)."""
    if not pkg.has("word/styles.xml"):
        return
    root = pkg.root("word/styles.xml")
    for defaults in root.iter(q(W, "rPrDefault")):
        for el in defaults.iter(q(W, "lang")):
            el.set(q(W, "val"), lang)
            if lang.split("-")[0] in ("zh", "ja", "ko"):
                el.set(q(W, "eastAsia"), lang)
            pkg.changed.add("word/styles.xml")


def unit_label(fmt: str) -> str:
    return UNIT_LABEL.get(fmt, "page")



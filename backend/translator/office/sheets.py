"""Excel workbooks (.xlsx, .xlsm): the text in cells.

openpyxl reads the grid for the Layout view (office/view.py), but saving through it loses what it doesn't model
(sparklines and other extensions, shapes, some pictures) and rewrites every string. So the translation is written
by patching the XML: each shared string (`xl/sharedStrings.xml`) and inline string whose text is a segment's source
is replaced, every other file in the package is copied byte for byte.

One segment per distinct string, in the order it is first used (sheet by sheet, row by row); a sheet is a "page".
Formulas, numbers, dates and sheet names are left alone (formulas and charts refer to sheet names). A string literal
in a formula that is a translated cell text (`COUNTIF(F:F,"未整改")`) is translated too, so the result stays right.
"""

from __future__ import annotations

import copy
import io
import posixpath
import re
import zipfile

from lxml import etree

from . import markup, pictures
from .common import A, MC, S, XML_SPACE, Report, Unit, local, q, segment
from .markup import Piece

R_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REF = re.compile(r"^([A-Z]+)(\d+)$")


def _parse(data: bytes):
    return etree.fromstring(data, etree.XMLParser(resolve_entities=False, huge_tree=True))


class Book:
    """The workbook package: sheet names, paths and the shared strings."""

    def __init__(self, data: bytes):
        self.zip = zipfile.ZipFile(io.BytesIO(data))
        names = set(self.zip.namelist())
        wb = _parse(self.zip.read("xl/workbook.xml"))
        rels = _parse(self.zip.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        self.sheets: list[tuple[str, str]] = []  # (name, path)
        for sh in wb.iter(q(S, "sheet")):
            path = target.get(sh.get(q(R_DOC, "id")), "")
            path = path.lstrip("/") if path.startswith("/") else posixpath.normpath(posixpath.join("xl", path))
            if path in names:
                self.sheets.append((sh.get("name"), path))
        self.shared_path = next((posixpath.normpath(posixpath.join("xl", t)) for t in target.values() if t.endswith("sharedStrings.xml")),
                                "xl/sharedStrings.xml")
        self.shared = _parse(self.zip.read(self.shared_path)) if self.shared_path in names else None

    def strings(self) -> list:
        return list(self.shared.iter(q(S, "si"))) if self.shared is not None else []


def _rpr_key(rpr) -> str:
    """What makes a run's formatting different in a cell people would notice: bold, italic, underline, strike,
    super/subscript (a run's font name, size or colour alone don't count: Excel writers spell defaults differently)."""
    if rpr is None:
        return ""
    keys = []
    for tag in ("b", "i", "u", "strike", "vertAlign"):
        el = rpr.find(q(S, tag))
        if el is not None and el.get("val", "1") not in ("0", "false", "none", "baseline"):
            keys.append(f"{tag}={el.get('val', '1')}")
    return ";".join(keys)


def _on(el) -> bool:
    return el is not None and el.get("val", "1") not in ("0", "false")


def read(si) -> list[Piece]:
    """A shared string (si) or an inline string (is) as pieces. Phonetic guides (rPh) are left out."""
    pieces = []
    for el in si:
        tag = local(el)
        if tag == "t":
            pieces.append(Piece(text=el.text or "", style="", payload=None))
        elif tag == "r":
            rpr, t = el.find(q(S, "rPr")), el.find(q(S, "t"))
            pieces.append(Piece(text=(t.text or "") if t is not None else "", style=_rpr_key(rpr),
                                bold=rpr is not None and _on(rpr.find(q(S, "b"))),
                                italic=rpr is not None and _on(rpr.find(q(S, "i"))), payload=el))
    return pieces


def _t(text: str):
    t = etree.Element(q(S, "t"))
    t.text = text
    if text != text.strip() or "\n" in text:
        t.set(XML_SPACE, "preserve")
    return t


def rebuild(si, enc: markup.Encoded, dec: markup.Decoded) -> None:
    extras = [c for c in si if local(c) in ("rPh", "phoneticPr")]  # phonetic guides: kept after the text
    for child in list(si):
        si.remove(child)
    outs = [o for o in dec.out if o.text]
    if all(o.like is None or o.like.payload is None for o in outs):  # plain text throughout: one <t>
        si.append(_t("".join(o.text for o in outs)))
    else:
        for o in outs:
            r = etree.SubElement(si, q(S, "r"))
            like = o.like.payload if o.like is not None else None
            rpr = like.find(q(S, "rPr")) if like is not None else None
            if rpr is not None:
                r.append(copy.deepcopy(rpr))
            r.append(_t(o.text))
    for el in extras:
        si.append(el)


def _cells(book: Book):
    """(sheet index, sheet name, cell ref, kind "s"/"inline", shared index or the <is> element) in reading order."""
    for i, (name, path) in enumerate(book.sheets, start=1):
        root = _parse(book.zip.read(path))
        for c in root.iter(q(S, "c")):
            t = c.get("t")
            if t == "s":
                v = c.find(q(S, "v"))
                if v is not None and (v.text or "").strip().isdigit():
                    yield i, name, c.get("r"), "s", int(v.text), root
            elif t == "inlineStr" and c.find(q(S, "is")) is not None:
                yield i, name, c.get("r"), "inline", c.find(q(S, "is")), root


def _rels(book: Book, path: str) -> dict[str, str | None]:
    """A part's relationships: id → the target part's path (None for an external target, e.g. a linked picture)."""
    rels_path = posixpath.join(posixpath.dirname(path), "_rels", posixpath.basename(path) + ".rels")
    if rels_path not in book.zip.namelist():
        return {}
    out: dict[str, str | None] = {}
    for rel in _parse(book.zip.read(rels_path)):
        target = rel.get("Target") or ""
        if rel.get("TargetMode") == "External":
            out[rel.get("Id")] = None
        else:
            out[rel.get("Id")] = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                posixpath.join(posixpath.dirname(path), target))
    return out


def _drawings(book: Book) -> list[tuple[int, str, str]]:
    """(sheet index, sheet name, drawing part path) for each sheet that has pictures or shapes."""
    out = []
    for i, (name, path) in enumerate(book.sheets, start=1):
        drawing = _parse(book.zip.read(path)).find(q(S, "drawing"))
        if drawing is None:
            continue
        target = _rels(book, path).get(drawing.get(q(R_DOC, "id")) or "")
        if target and target in book.zip.namelist():
            out.append((i, name, target))
    return out


def _in_fallback(el) -> bool:
    parent = el.getparent()
    while parent is not None:
        if parent.tag == q(MC, "Fallback"):
            return True
        parent = parent.getparent()
    return False


def _sheet_pictures(book: Book, path: str, root) -> list[dict]:
    """The pictures of a drawing part: [{pic, cnvpr, image path (None: linked), cell, size}] in order."""
    rels = _rels(book, path)
    out = []
    for pic in root.iter(q(pictures.XDR, "pic")):
        if _in_fallback(pic):
            continue
        cnvpr = pic.find(f"{q(pictures.XDR, 'nvPicPr')}/{q(pictures.XDR, 'cNvPr')}")
        rid, linked = pictures.blip_rid(pic)
        image = None if linked or not rid else rels.get(rid)
        anchor, cell = pic.getparent(), ""
        while anchor is not None and local(anchor) not in ("twoCellAnchor", "oneCellAnchor", "absoluteAnchor"):
            anchor = anchor.getparent()
        start = anchor.find(q(pictures.XDR, "from")) if anchor is not None else None
        if start is not None:
            try:
                col = int(start.findtext(q(pictures.XDR, "col")))
                row = int(start.findtext(q(pictures.XDR, "row")))
                cell = f"{_column(col + 1)}{row + 1}"
            except (TypeError, ValueError):
                cell = ""
        ext = pic.find(f"{q(pictures.XDR, 'spPr')}/{q(A, 'xfrm')}/{q(A, 'ext')}")
        if ext is None and anchor is not None:
            ext = anchor.find(q(pictures.XDR, "ext"))
        try:
            size = (int(ext.get("cx")), int(ext.get("cy"))) if ext is not None else None
        except (TypeError, ValueError):
            size = None
        out.append({"pic": pic, "cnvpr": cnvpr, "image": image, "linked": linked, "cell": cell, "size": size,
                    "id": cnvpr.get("id") if cnvpr is not None else str(len(out) + 1)})
    return out


def _column(n: int) -> str:
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _picture_bytes(book: Book, image: str | None) -> bytes | None:
    return book.zip.read(image) if image and image in book.zip.namelist() else None


def _column_headers(book: Book) -> dict[tuple[int, str], str]:
    """(sheet, column letters) → the text in its first row, as context for short labels."""
    strings = book.strings()
    heads = {}
    for i, _name, ref, kind, value, _root in _cells(book):
        m = _REF.match(ref or "")
        if m and m.group(2) == "1":
            pieces = read(strings[value]) if kind == "s" and value < len(strings) else read(value) if kind == "inline" else []
            text = markup.plain(pieces).strip()
            if text:
                heads[(i, m.group(1))] = text
    return heads


def extract(data: bytes, finder: pictures.Finder | None = None) -> tuple[list[Unit], dict]:
    book = Book(data)
    strings = book.strings()
    heads = _column_headers(book)
    units = [Unit(name) for name, _ in book.sheets]
    seen: dict[str, dict] = {}  # encoded text → its segment (one segment per distinct string)
    for i, name, ref, kind, value, _root in _cells(book):
        if kind == "s":
            if value >= len(strings):
                continue
            pieces = read(strings[value])
        else:
            pieces = read(value)
        enc = markup.encode(pieces)
        if not enc.text.strip():
            continue
        if enc.text in seen:
            seg = seen[enc.text]
            seg["refs"] = seg.get("refs", 1) + 1
            continue
        m = _REF.match(ref or "")
        head = heads.get((i, m.group(1))) if m and m.group(2) != "1" else None
        seg = segment(0, 0, "cell", enc.text, markup.plain(pieces), f"{name}!{ref}" + (f" · column “{head[:40]}”" if head else ""),
                      f"{name}!{ref}")
        seen[enc.text] = seg
        units[i - 1].segments.append(seg)
    for seg in seen.values():
        if (n := seg.pop("refs", 1)) > 1:
            seg["where"] = seg["where"].replace(seg["loc"], f"{seg['loc']} (+{n - 1} more)", 1)
    if finder is not None:  # a sheet's pictures, after its cells
        for i, name, path in _drawings(book):
            for k, found in enumerate(_sheet_pictures(book, path, _parse(book.zip.read(path))), start=1):
                at = f" at {found['cell']}" if found["cell"] else f" {k}"
                cnvpr = found["cnvpr"]
                units[i - 1].segments.extend(finder.add(
                    f"{path}#pic{found['id']}", f"{name} · picture{at}", _picture_bytes(book, found["image"]),
                    pictures.content_type_of(found["image"] or ""), found["size"], cnvpr, linked=found["linked"],
                    descr=cnvpr.get("descr") if cnvpr is not None else None))
    return [u for u in units if u.segments], {"format": "xlsx", "not_translated": _skipped(book)}


def _skipped(book: Book) -> dict[str, int]:
    found = {"sheet names": len(book.sheets)}
    charts = sum(1 for n in book.zip.namelist() if n.startswith("xl/charts/chart"))
    comments = sum(1 for n in book.zip.namelist() if re.match(r"xl/comments\d*\.xml$", n))
    if charts:
        found["chart text"] = charts
    if comments:
        found["cell notes"] = comments
    return found


_LITERAL = re.compile(r'"((?:[^"]|"")*)"')
_OPERATOR = re.compile(r"^(<>|>=|<=|=|<|>)?(.*)$", re.S)


def _formula_literals(root, translations: dict[str, str]) -> int:
    """Translate string literals in formulas that are a translated cell text (also after a comparison operator)."""
    n = 0
    for f in root.iter(q(S, "f")):
        if not f.text:
            continue

        def sub(m: re.Match) -> str:
            nonlocal n
            op, text = _OPERATOR.match(m.group(1).replace('""', '"')).groups()
            if text in translations:
                n += 1
                return '"' + (op or "") + translations[text].replace('"', '""') + '"'
            return m.group(0)

        f.text = _LITERAL.sub(sub, f.text)
    return n


def write(data: bytes, segments: list[dict], marks: bool = False) -> tuple[bytes, Report]:
    book = Book(data)
    report = Report()
    by_source = {s["source"]: s for s in segments if s.get("loc") and s.get("kind") not in ("figure", "alt")}
    plain_translations: dict[str, str] = {}
    written: set[str] = set()
    changed: dict[str, bytes] = {}

    def patch(si) -> None:
        pieces = read(si)
        enc = markup.encode(pieces)
        seg = by_source.get(enc.text)
        if seg is None:
            return
        target = seg.get("target")
        if not seg.get("translatable", True) or not target:
            return
        dec = markup.decode(target, enc)
        if dec.simplified or enc.simplified:
            report.formatting_simplified.append(seg["id"])
        rebuild(si, enc, dec)
        plain_translations[markup.plain(pieces)] = "".join(o.text for o in dec.out)
        written.add(seg["id"])

    for si in book.strings():
        patch(si)
    if book.shared is not None:
        changed[book.shared_path] = etree.tostring(book.shared, xml_declaration=True, encoding="UTF-8", standalone=True)
    for _name, path in book.sheets:
        root = _parse(book.zip.read(path))
        touched = False
        for c in root.iter(q(S, "c")):
            if c.get("t") == "inlineStr" and (is_ := c.find(q(S, "is"))) is not None:
                before = etree.tostring(is_)
                patch(is_)
                touched = touched or etree.tostring(is_) != before
        n = _formula_literals(root, plain_translations)
        report.formulas_updated += n
        if touched or n:
            changed[path] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    if report.formulas_updated:  # results of the changed formulas are computed again when the file opens
        wb = _parse(book.zip.read("xl/workbook.xml"))
        calc = wb.find(q(S, "calcPr"))
        if calc is None:
            calc = etree.SubElement(wb, q(S, "calcPr"))
        calc.set("fullCalcOnLoad", "1")
        changed["xl/workbook.xml"] = etree.tostring(wb, xml_declaration=True, encoding="UTF-8", standalone=True)
    _write_pictures(book, segments, report, changed)
    report.written = len(written)
    report.unchanged = sum(1 for s in segments if s["id"] not in written and s.get("kind") not in ("figure", "alt"))
    pictures.count_figures(segments, report)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for info in book.zip.infolist():
            zf.writestr(info, changed.get(info.filename, book.zip.read(info.filename)))
    return out.getvalue(), report


def _write_pictures(book: Book, segments: list[dict], report: Report, changed: dict[str, bytes]) -> None:
    """A picture's alt text: translated, with the English of the text in it (the drawing part is patched; nothing
    else changes)."""
    figures, alts = pictures.by_place(segments)
    if not figures and not alts:
        return
    for _i, _name, path in _drawings(book):
        root = _parse(book.zip.read(path))
        touched = False
        for found in _sheet_pictures(book, path, root):
            loc = f"{path}#pic{found['id']}"
            figure, alt = figures.get(loc), alts.get(loc)
            if (figure is None and alt is None) or found["cnvpr"] is None:
                continue
            if figure is not None:
                blob = _picture_bytes(book, found["image"])
                if blob is None or pictures.digest(blob) != figure.get("sha1"):
                    if figure["id"] not in report.mismatch:
                        report.mismatch.append(figure["id"])
                    figure = None
            descr = pictures.new_alt_text(found["cnvpr"].get("descr"), figure, alt, report)
            if descr is not None:
                touched = pictures.describe(found["cnvpr"], descr) or touched
                report.pictures["alt_text"] += 1
        if touched:
            changed[path] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

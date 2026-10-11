"""Office Open XML paragraphs ↔ segment text with inline codes. Shared by Word (`w:p`), PowerPoint
(`a:p`) and Excel rich text (`si` / `is`).

Reading a paragraph:
- Runs are cleaned up (spell-check marks, rsids and language tags don't count as formatting) and
  runs with the same formatting are merged.
- The formatting that covers most text is the paragraph's base style. Text in other formatting, and
  Word hyperlinks, become `<g id>` spans.
- Tabs, line breaks, images, fields, footnote marks and anything unknown become `<x id/>` placeholders.
- Bookmarks and comment ranges are kept at the start/end of the paragraph.
- Tracked changes are read (and written) as accepted; the caller warns the user.
- A Word field keeps working: its hidden instruction (`TOC \\o`, `PAGEREF _Toc12`, `HYPERLINK …`) is a
  placeholder and its visible result is translated, so a table of contents or a cross-reference comes
  out translated and can still be updated in Word. Legacy form fields are fields too.
- Inline content controls (template boxes) and hyperlinks are spans that keep their wrapper.

Writing re-reads the original paragraph (no skeleton is stored), so codes map back to the original
XML: paragraph properties stay, new runs copy the original run properties, placeholders put back the
original elements.
"""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from lxml import etree

from . import inline

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, remove_blank_text=False)


# --------------------------------------------------------------------------- #
# Paragraph model
# --------------------------------------------------------------------------- #


@dataclass
class Piece:
    kind: Literal["text", "code"]
    text: str = ""
    fmt: str = ""  # formatting key of a text piece
    rpr: object = None  # run properties element to copy for this text
    link: object = None  # enclosing Word hyperlink element
    label: str = ""  # code label for people: tab, line break, image, field…
    # `link` is the wrapper a text sits in: a Word hyperlink or inline content control (w:sdt).
    source: tuple = ()  # how to put a code back: ("elem", el) | ("inrun", rpr, child) | ("elems", [els])


@dataclass
class Paragraph:
    el: object
    props: list = field(default_factory=list)  # pPr etc., kept first
    head: list = field(default_factory=list)  # bookmarkStart… (moved to the start)
    tail: list = field(default_factory=list)  # bookmarkEnd…, endParaRPr (kept at the end)
    pieces: list[Piece] = field(default_factory=list)
    base_fmt: str = ""
    base_rpr: object = None
    tracked: int = 0  # tracked changes read as accepted
    # Filled by encode():
    text: str = ""
    codes: dict = field(default_factory=dict)  # id → ("fmt", rpr) | ("link", link_el, rpr) | ("x", piece)
    labels: dict = field(default_factory=dict)  # id → label

    @property
    def plain(self) -> str:
        return inline.strip(self.text)


class Dialect:
    ns = ""
    para = run = rpr = text = ""
    noise_children: set[str] = set()
    noise_attrs: set[str] = set()

    def fmt_key(self, rpr) -> str:
        if rpr is None:
            return ""
        clean = copy.deepcopy(rpr)
        for child in list(clean):
            if local(child) in self.noise_children:
                clean.remove(child)
        for el in clean.iter():
            for attr in list(el.attrib):
                if etree.QName(attr).localname in self.noise_attrs:
                    del el.attrib[attr]
        if not len(clean) and not clean.attrib:
            return ""
        return etree.tostring(clean, encoding="unicode")

    def label(self, rpr) -> str:
        return "format"

    def set_lang(self, rpr, lang: str) -> None:
        pass

    def make_runs(self, text: str, rpr) -> list:
        raise NotImplementedError


def _on(el, attr: str = "val") -> bool:
    v = el.get(q(W, attr)) if el is not None else None
    return el is not None and v not in ("0", "false", "off", "none")


class WordDialect(Dialect):
    ns = W
    para, run, rpr, text = q(W, "p"), q(W, "r"), q(W, "rPr"), q(W, "t")
    noise_children = {"lang", "noProof", "proofErr", "webHidden", "rsid"}
    noise_attrs = {"hint", "rsidR", "rsidRPr", "rsidDel"}

    def label(self, rpr) -> str:
        if rpr is None:
            return "format"
        parts = []
        for tag, name in (("b", "bold"), ("i", "italic"), ("strike", "strike"), ("caps", "caps"), ("smallCaps", "small caps")):
            if _on(rpr.find(q(W, tag))):
                parts.append(name)
        if _on(rpr.find(q(W, "u"))):
            parts.append("underline")
        va = rpr.find(q(W, "vertAlign"))
        if va is not None:
            parts.append({"superscript": "superscript", "subscript": "subscript"}.get(va.get(q(W, "val")), ""))
        if rpr.find(q(W, "color")) is not None:
            parts.append("colour")
        if rpr.find(q(W, "highlight")) is not None or rpr.find(q(W, "shd")) is not None:
            parts.append("highlight")
        style = rpr.find(q(W, "rStyle"))
        if style is not None and not parts:
            parts.append(f"style {style.get(q(W, 'val'))}")
        return " + ".join(p for p in parts if p) or "format"

    def set_lang(self, rpr, lang: str) -> None:
        el = rpr.find(q(W, "lang")) if rpr is not None else None
        if el is not None and el.get(q(W, "val")):
            el.set(q(W, "val"), lang)

    def make_runs(self, text: str, rpr) -> list:
        runs = []
        for i, line in enumerate(text.split("\n")):
            r = etree.Element(self.run)
            if rpr is not None:
                r.append(copy.deepcopy(rpr))
            if i:
                etree.SubElement(r, q(W, "br"))
            if line:
                t = etree.SubElement(r, self.text)
                t.text = line
                if line != line.strip() or "  " in line:
                    t.set(XML_SPACE, "preserve")
            runs.append(r)
        return runs


class DrawingDialect(Dialect):
    ns = A
    para, run, rpr, text = q(A, "p"), q(A, "r"), q(A, "rPr"), q(A, "t")
    noise_attrs = {"lang", "altLang", "dirty", "err", "noProof", "smtClean", "smtId", "bmk"}

    def label(self, rpr) -> str:
        if rpr is None:
            return "format"
        parts = []
        if rpr.find(q(A, "hlinkClick")) is not None:
            parts.append("link")
        if rpr.get("b") in ("1", "true"):
            parts.append("bold")
        if rpr.get("i") in ("1", "true"):
            parts.append("italic")
        if rpr.get("u") not in (None, "none"):
            parts.append("underline")
        if rpr.get("strike") not in (None, "noStrike"):
            parts.append("strike")
        baseline = int(rpr.get("baseline", "0") or 0)
        if baseline:
            parts.append("superscript" if baseline > 0 else "subscript")
        if rpr.find(q(A, "solidFill")) is not None:
            parts.append("colour")
        if rpr.get("sz"):
            parts.append("size")
        return " + ".join(parts) or "format"

    def set_lang(self, rpr, lang: str) -> None:
        if rpr is not None:
            rpr.set("lang", lang)  # spell-check in the target language (runs otherwise inherit the deck's)

    def make_runs(self, text: str, rpr) -> list:
        out = []
        for i, line in enumerate(text.split("\n")):
            if i:
                br = etree.Element(q(A, "br"))
                if rpr is not None:
                    br.append(copy.deepcopy(rpr))
                out.append(br)
            if line or not i:
                r = etree.Element(self.run)
                if rpr is not None:
                    r.append(copy.deepcopy(rpr))
                etree.SubElement(r, self.text).text = line
                out.append(r)
        return out


class SheetDialect(Dialect):
    ns = S
    para, run, rpr, text = q(S, "si"), q(S, "r"), q(S, "rPr"), q(S, "t")

    def label(self, rpr) -> str:
        if rpr is None:
            return "format"
        names = {"b": "bold", "i": "italic", "u": "underline", "strike": "strike", "color": "colour", "vertAlign": "script"}
        return " + ".join(names[local(c)] for c in rpr if local(c) in names) or "format"

    def make_runs(self, text: str, rpr) -> list:
        r = etree.Element(self.run)
        if rpr is not None:
            r.append(copy.deepcopy(rpr))
        t = etree.SubElement(r, self.text)
        t.text = text
        if text != text.strip() or "\n" in text:
            t.set(XML_SPACE, "preserve")
        return [r]


WORD, DRAWING, SHEET = WordDialect(), DrawingDialect(), SheetDialect()

# Word paragraph children
_W_HEAD = {"bookmarkStart", "commentRangeStart", "permStart", "moveFromRangeStart", "moveToRangeStart",
           "customXmlInsRangeStart", "customXmlDelRangeStart"}
_W_TAIL = {"bookmarkEnd", "commentRangeEnd", "permEnd", "moveFromRangeEnd", "moveToRangeEnd",
           "customXmlInsRangeEnd", "customXmlDelRangeEnd"}
_W_UNWRAP = {"ins", "moveTo", "smartTag", "customXml", "dir", "bdo"}
_W_SKIP = {"del", "moveFrom"}
_W_DROP = {"proofErr"}
# Word run children
_W_CODE_LABEL = {
    "tab": "tab", "ptab": "tab", "br": "line break", "cr": "line break", "sym": "symbol",
    "drawing": "image", "pict": "image", "object": "object", "AlternateContent": "image",
    "footnoteReference": "footnote mark", "endnoteReference": "endnote mark", "footnoteRef": "footnote number",
    "endnoteRef": "endnote number", "commentReference": "comment", "annotationRef": "comment",
    "separator": "separator", "continuationSeparator": "separator", "pgNum": "page number",
}


_TRACKED = {"ins", "del", "moveFrom", "moveTo"}
_REVISION_PROPS = {"rPrChange", "pPrChange", "sectPrChange", "tblPrChange", "trPrChange", "tcPrChange",
                   "tblGridChange", "numberingChange"}


def _field_types(run) -> list[str]:
    return [fc.get(q(W, "fldCharType")) for fc in run.iter(q(W, "fldChar"))]


def read_paragraph(el, dialect: Dialect, fields: list[str] | None = None) -> tuple[Paragraph, list[str]]:
    """→ (model, open Word fields after this paragraph). Read-only: the XML is not modified.

    `fields` is the stack of Word fields still open from earlier paragraphs ("instr" while reading a
    field's instruction, "result" while reading its visible result) — a table of contents begins in
    one paragraph and ends many paragraphs later.
    """
    para = Paragraph(el)
    stack = list(fields or [])
    instr: list = []  # elements of the field instruction being read

    def flush_instr() -> None:
        if instr:
            para.pieces.append(Piece("code", label="field", source=("elems", list(instr))))
            instr.clear()

    def in_instr() -> bool:
        return bool(stack) and stack[-1] == "instr"

    def word_field_run(run, link) -> bool:
        """Field markup (begin / instruction / separate / end). True if the run was consumed."""
        types = _field_types(run)
        if not types and not in_instr():
            return False
        if in_instr() or "begin" in types:
            instr.append(run)
        else:  # a `separate`/`end` mark after the visible result
            para.pieces.append(Piece("code", label="field end", link=link, source=("elem", run)))
        for t in types:
            if t == "begin":
                stack.append("instr")
            elif t == "separate" and stack:
                stack[-1] = "result"
            elif t == "end" and stack:
                stack.pop()
        if not in_instr():
            flush_instr()
        return True

    def add_run(run, link) -> None:
        if dialect is WORD and word_field_run(run, link):
            return
        rpr = run.find(dialect.rpr)
        fmt = dialect.fmt_key(rpr)
        for child in run:
            name = local(child)
            if child.tag == dialect.rpr or not name:
                continue
            if child.tag == dialect.text:
                para.pieces.append(Piece("text", child.text or "", fmt, rpr, link))
            elif dialect is WORD and name == "noBreakHyphen":
                para.pieces.append(Piece("text", "\u2011", fmt, rpr, link))
            elif dialect is WORD and name == "softHyphen":
                para.pieces.append(Piece("text", "\u00ad", fmt, rpr, link))
            elif name in ("lastRenderedPageBreak", "delText", "instrText", "rPh"):
                continue
            else:
                label = _W_CODE_LABEL.get(name, "object")
                if name == "br" and child.get(q(W, "type")) == "page":
                    label = "page break"
                para.pieces.append(Piece("code", label=label, link=link, source=("inrun", rpr, child)))

    def walk(parent, link=None) -> None:
        for child in parent:
            name = local(child)
            if not name:
                continue  # comments, processing instructions
            if dialect is WORD:
                if name in _TRACKED:
                    para.tracked += 1
                if name == "pPr":
                    para.tracked += sum(1 for c in child.iter() if local(c) in _REVISION_PROPS | {"ins", "del"})
                    para.props.append(child)
                elif name == "r":
                    para.tracked += sum(1 for c in child.iter(q(W, "rPrChange")))
                    add_run(child, link)
                elif in_instr() and name not in _W_HEAD | _W_TAIL:
                    instr.append(child)  # anything inside a field instruction belongs to it
                elif name == "hyperlink":
                    walk(child, child)
                elif name in _W_UNWRAP:
                    walk(child, link)
                elif name == "sdt":
                    content = child.find(q(W, "sdtContent"))
                    if content is not None:
                        walk(content, child)  # the content control stays around its translated text
                elif name in _W_HEAD:
                    para.head.append(child)
                elif name in _W_TAIL:
                    para.tail.append(child)
                elif name in _W_SKIP | _W_DROP:
                    continue
                elif name == "fldSimple":
                    para.pieces.append(Piece("code", label="field", link=link, source=("elem", child)))
                elif child.tag in (q(M, "oMath"), q(M, "oMathPara")):
                    para.pieces.append(Piece("code", label="equation", link=link, source=("elem", child)))
                else:
                    para.pieces.append(Piece("code", label="object", link=link, source=("elem", child)))
            elif dialect is DRAWING:
                if name == "pPr":
                    para.props.append(child)
                elif name == "r":
                    add_run(child, None)
                elif name == "endParaRPr":
                    para.tail.append(child)
                elif name == "br":
                    para.pieces.append(Piece("code", label="line break", source=("elem", child)))
                elif name == "fld":
                    para.pieces.append(Piece("code", label="field", source=("elem", child)))
                else:
                    para.pieces.append(Piece("code", label="object", source=("elem", child)))
            else:  # spreadsheet rich text
                if child.tag == q(S, "t"):
                    para.pieces.append(Piece("text", child.text or "", "", None, None))
                elif name == "r":
                    add_run(child, None)
                elif name == "rPh":
                    continue  # phonetic guide (Japanese): dropped on write
                else:
                    para.tail.append(child)

    walk(el)
    flush_instr()  # an instruction continuing into the next paragraph (rare)
    _merge(para)
    _base(para)
    encode(para, dialect)
    return para, stack


def accept_tracked_changes(root) -> int:
    """Accept every tracked change in a Word part (before writing) → how many were found."""
    n = 0
    for el in list(root.iter(q(W, "del"), q(W, "moveFrom"))):
        parent = el.getparent()
        if parent is None:
            continue
        n += 1
        parent.remove(el)  # deleted text goes; a deleted paragraph mark (in rPr) just loses its marker
    for el in list(root.iter(q(W, "ins"), q(W, "moveTo"))):
        parent = el.getparent()
        if parent is None:
            continue
        n += 1
        if local(parent) == "rPr":
            parent.remove(el)
            continue
        i = parent.index(el)
        for j, child in enumerate(list(el)):
            parent.insert(i + j, child)
        parent.remove(el)
    for tag in _REVISION_PROPS:
        for el in list(root.iter(q(W, tag))):
            n += 1
            el.getparent().remove(el)
    for tag in ("moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd"):
        for el in list(root.iter(q(W, tag))):
            el.getparent().remove(el)
    return n


def _merge(para: Paragraph) -> None:
    merged: list[Piece] = []
    for p in para.pieces:
        last = merged[-1] if merged else None
        if p.kind == "text" and last and last.kind == "text" and last.fmt == p.fmt and last.link is p.link:
            last.text += p.text
        elif p.kind == "text" and not p.text:
            continue
        else:
            merged.append(Piece(**p.__dict__))
    para.pieces = merged


def _base(para: Paragraph) -> None:
    """The base formatting is the one that needs the fewest spans: the formatting of the most separate
    stretches of text ("Gegen **Wiedereinschalten** sichern" → plain, one bold span), then the most text."""
    groups: Counter = Counter()
    chars: Counter = Counter()
    rprs: dict[str, object] = {}
    previous = None
    for p in para.pieces:
        if p.kind != "text" or p.link is not None:
            previous = None
            continue
        if p.fmt != previous:
            groups[p.fmt] += 1
        previous = p.fmt
        chars[p.fmt] += len(p.text)
        rprs.setdefault(p.fmt, p.rpr)
    if not chars:  # all text is inside links
        for p in para.pieces:
            if p.kind == "text":
                chars[p.fmt] += len(p.text)
                rprs.setdefault(p.fmt, p.rpr)
    if chars:
        para.base_fmt = max(chars, key=lambda f: (groups[f], chars[f]))
        para.base_rpr = rprs[para.base_fmt]


def encode(para: Paragraph, dialect: Dialect) -> None:
    out: list[str] = []
    codes: dict[str, tuple] = {}
    labels: dict[str, str] = {}
    open_key = None
    next_id = 1

    def new_id() -> str:
        nonlocal next_id
        i = str(next_id)
        next_id += 1
        return i

    def close() -> None:
        nonlocal open_key
        if open_key is not None:
            out.append("</g>")
            open_key = None

    def open_group(key, piece: Piece) -> None:
        nonlocal open_key
        gid = new_id()
        out.append(f'<g id="{gid}">')
        if key[0] == "link":
            codes[gid] = ("link", piece.link, piece.rpr)
            labels[gid] = "link" if local(piece.link) == "hyperlink" else "content control"
        else:
            codes[gid] = ("fmt", piece.rpr)
            labels[gid] = dialect.label(piece.rpr)
        open_key = key

    for p in para.pieces:
        if p.kind == "text":
            key = ("link", id(p.link)) if p.link is not None else (("fmt", p.fmt) if p.fmt != para.base_fmt else None)
            if key != open_key:
                close()
                if key is not None:
                    open_group(key, p)
            out.append(p.text)
        else:
            link_key = ("link", id(p.link)) if p.link is not None else None
            if open_key is not None and open_key != link_key and not (open_key[0] == "fmt" and link_key is None):
                close()
            if link_key is not None and open_key != link_key:
                open_group(link_key, Piece("text", rpr=para.base_rpr, link=p.link))
            xid = new_id()
            out.append(f'<x id="{xid}"/>')
            codes[xid] = ("x", p)
            labels[xid] = p.label
    close()
    para.text, para.codes, para.labels = "".join(out), codes, labels


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def _materialize(piece: Piece, dialect: Dialect) -> list:
    kind = piece.source[0]
    if kind == "elem":
        return [piece.source[1]]
    if kind == "elems":
        return list(piece.source[1])
    _, rpr, child = piece.source  # a code that lived inside a run: give it a run of its own
    run = etree.Element(dialect.run)
    if rpr is not None:
        run.append(copy.deepcopy(rpr))
    run.append(child)
    return [run]


def write_paragraph(para: Paragraph, target: str, dialect: Dialect, lang: str | None = None) -> list[str]:
    """Replace the paragraph's content with `target` (codes repaired first) → list of repairs made."""
    target, fixes = inline.repair(para.text, target)
    nodes = inline.parse(target)
    used: set[str] = set()
    new: list = []

    def runs(text: str, rpr) -> list:
        made = dialect.make_runs(text, rpr)
        if lang:
            for r in made:
                if dialect is DRAWING and r.find(dialect.rpr) is None:
                    r.insert(0, etree.Element(dialect.rpr))
                for rp in r.iter(dialect.rpr):
                    dialect.set_lang(rp, lang)
        return made

    def walk(items: list[inline.Node], rpr, sink: list) -> None:
        for n in items:
            if n.kind == "text":
                if n.text:
                    sink.extend(runs(n.text, rpr))
                continue
            spec = para.codes.get(n.id)
            if spec is None:
                if n.kind == "g":
                    walk(n.children, rpr, sink)
                continue
            if n.kind == "x" and spec[0] == "x":
                els = _materialize(spec[1], dialect)
                if n.id in used:
                    els = [copy.deepcopy(e) for e in els]
                used.add(n.id)
                sink.extend(els)
            elif spec[0] == "fmt":
                walk(n.children, spec[1], sink)
            elif spec[0] == "link":
                wrapper = spec[1]
                inner: list = []
                walk(n.children, spec[2] if spec[2] is not None else rpr, inner)
                copy_ = etree.Element(wrapper.tag, attrib=dict(wrapper.attrib), nsmap=wrapper.nsmap)
                if local(wrapper) == "sdt":  # content control: keep its properties, new content
                    for child in wrapper:
                        if local(child) in ("sdtPr", "sdtEndPr"):
                            copy_.append(copy.deepcopy(child))
                    content = etree.SubElement(copy_, q(W, "sdtContent"))
                    content.extend(inner)
                else:
                    copy_.extend(inner)
                sink.append(copy_)

    walk(nodes, para.base_rpr, new)
    for child in list(para.el):
        para.el.remove(child)
    para.el.extend([*para.props, *para.head, *new, *para.tail])
    if dialect is SHEET:
        _collapse_sheet_runs(para.el)
    return fixes


def _collapse_sheet_runs(si) -> None:
    """Excel: runs without formatting → one plain <t> (the usual shape of a shared string)."""
    runs = [c for c in si if c.tag == q(S, "r")]
    if runs and all(r.find(q(S, "rPr")) is None for r in runs):
        text = "".join(t.text or "" for r in runs for t in r.iter(q(S, "t")))
        for r in runs:
            si.remove(r)
        t = etree.Element(q(S, "t"))
        t.text = text
        if text != text.strip() or "\n" in text:
            t.set(XML_SPACE, "preserve")
        si.insert(0, t)
    elif not runs and si.find(q(S, "t")) is None:
        si.insert(0, etree.Element(q(S, "t")))


def in_fallback(el) -> bool:
    """Inside mc:Fallback (the duplicate of an mc:Choice for older readers)."""
    parent = el.getparent()
    while parent is not None:
        if parent.tag == q(MC, "Fallback"):
            return True
        parent = parent.getparent()
    return False


def fallback_twins(root, para_tag: str) -> dict:
    """mc:Choice paragraph → the matching mc:Fallback paragraph (text boxes are stored twice)."""
    twins = {}
    for ac in root.iter(q(MC, "AlternateContent")):
        choice, fallback = ac.find(q(MC, "Choice")), ac.find(q(MC, "Fallback"))
        if choice is None or fallback is None:
            continue
        a, b = list(choice.iter(para_tag)), list(fallback.iter(para_tag))
        if len(a) == len(b):
            twins.update(zip(a, b, strict=True))
    return twins

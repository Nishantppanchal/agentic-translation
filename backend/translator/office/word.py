"""Word documents (.docx, .docm), read and written with python-docx.

What is translated: the body (with nested tables, text boxes and content controls), headers and footers, footnotes
and endnotes. A paragraph's runs become one segment (office/markup.py says how formatting and objects survive).
Tracked changes are accepted first (reported). Not translated, and reported: comments, equations, inline content
controls and simple fields (`w:fldSimple`), whose text stays as it is.

python-docx doesn't load footnotes as XML parts, nor macro-enabled documents: both are registered below. It only
walks top-level body paragraphs, so the paragraphs are found with XPath and their runs read from the XML.
"""

from __future__ import annotations

import copy
import io
from dataclasses import dataclass

from docx.opc.constants import CONTENT_TYPE as CT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.part import PartFactory, XmlPart
from docx.package import Package
from docx.parts.document import DocumentPart
from lxml import etree

from . import markup, pictures
from .common import LANG, R, W, XML_SPACE, Report, Unit, fallback_twins, in_fallback, local, prefix, q, segment, without_prefix
from .markup import Piece

DOCM_MAIN = "application/vnd.ms-word.document.macroEnabled.main+xml"
PART_CHARS, MAX_PART_CHARS = 1500, 4000  # a new part starts at a top-level heading after this much text; always after the max

# Run children that are text (everything else in a run is an object: a picture, a footnote mark, a field…).
_TEXT = {"t", "tab", "br", "cr", "noBreakHyphen", "softHyphen", "lastRenderedPageBreak", "rPr"}
_MARKS = {"bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd", "permStart", "permEnd"}
_STARTS = {"bookmarkStart", "commentRangeStart", "permStart"}
_RUN_NOISE = {"lang", "noProof", "rsid"}
_REVISION_PROPS = {"rPrChange", "pPrChange", "sectPrChange", "tblPrChange", "trPrChange", "tcPrChange", "tblGridChange",
                   "numberingChange"}


def _register() -> None:
    PartFactory.part_type_for.setdefault(CT.WML_FOOTNOTES, XmlPart)
    PartFactory.part_type_for.setdefault(CT.WML_ENDNOTES, XmlPart)
    PartFactory.part_type_for.setdefault(DOCM_MAIN, DocumentPart)


def open_document(data: bytes) -> DocumentPart:
    _register()
    part = Package.open(io.BytesIO(data)).main_document_part
    if not isinstance(part, DocumentPart):
        raise ValueError("This isn't a Word document.")
    return part


def accept_tracked_changes(root) -> int:
    """Accept every tracked change in a Word part → how many there were."""
    n = 0
    for el in list(root.iter(q(W, "del"), q(W, "moveFrom"))):
        if (parent := el.getparent()) is not None:
            n += 1
            parent.remove(el)
    for el in list(root.iter(q(W, "ins"), q(W, "moveTo"))):
        parent = el.getparent()
        if parent is None:
            continue
        n += 1
        if local(parent) == "rPr":  # an inserted paragraph mark
            parent.remove(el)
            continue
        i = parent.index(el)
        for j, child in enumerate(list(el)):
            parent.insert(i + j, child)
        parent.remove(el)
    for el in [e for e in root.iter() if local(e) in _REVISION_PROPS]:
        n += 1
        el.getparent().remove(el)
    for el in [e for e in root.iter() if local(e) in ("moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd")]:
        el.getparent().remove(el)
    return n


def _unwrap(root) -> None:
    """Smart tags and custom XML around runs say nothing about the text: keep their runs."""
    for el in [e for e in root.iter(q(W, "smartTag"), q(W, "customXml"), q(W, "dir"), q(W, "bdo")) if e.getparent() is not None
               and local(e.getparent()) in ("p", "hyperlink", "smartTag", "customXml", "dir", "bdo")]:
        parent = el.getparent()
        i = parent.index(el)
        for j, child in enumerate([c for c in el if local(c) not in ("smartTagPr", "customXmlPr")]):
            parent.insert(i + j, child)
        parent.remove(el)


@dataclass
class Story:
    name: str  # header, footer, footnote, endnote or body
    part: object
    root: object


def stories(main: DocumentPart) -> list[Story]:
    out = [Story("body", main, main.element.body)]
    others = []
    for rel in main.rels.values():
        if rel.is_external:
            continue
        name = {RT.HEADER: "header", RT.FOOTER: "footer", RT.FOOTNOTES: "footnote", RT.ENDNOTES: "endnote"}.get(rel.reltype)
        if name and hasattr(rel.target_part, "element"):
            others.append(Story(name, rel.target_part, rel.target_part.element))
    order = {"header": 0, "footer": 1, "footnote": 2, "endnote": 3}
    return out + sorted(others, key=lambda s: (order[s.name], str(s.part.partname)))


def prepare(main: DocumentPart) -> int:
    """Accept tracked changes and unwrap smart tags in every story (reading and writing see the same text)."""
    n = 0
    for story in stories(main):
        n += accept_tracked_changes(story.root)
        _unwrap(story.root)
    return n


def paragraphs(story: Story) -> list:
    return [p for p in story.root.iter(q(W, "p")) if not in_fallback(p)]


# ---- reading a paragraph ------------------------------------------------------ #


def _on(el) -> bool:
    return el is not None and el.get(q(W, "val"), "true") not in ("0", "false", "off", "none")


def _rpr_key(rpr) -> str:
    if rpr is None:
        return ""
    rpr = copy.deepcopy(rpr)
    for el in [e for e in rpr if local(e) in _RUN_NOISE]:
        rpr.remove(el)
    for el in rpr.iter(q(W, "rFonts")):
        el.attrib.pop(q(W, "hint"), None)
    return etree.tostring(rpr, method="c14n").decode()


def _style(run) -> tuple[str, bool, bool]:
    rpr = run.find(q(W, "rPr"))
    if rpr is None:
        return "", False, False
    return _rpr_key(rpr), _on(rpr.find(q(W, "b"))), _on(rpr.find(q(W, "i")))


def _run_text(run) -> str | None:
    """The run's text (\\t for a tab, \\n for a line break), or None if the run holds an object."""
    out = []
    for child in run:
        tag = local(child)
        if tag not in _TEXT:
            return None
        if tag == "t":
            out.append(child.text or "")
        elif tag == "tab":
            out.append("\t")
        elif tag == "br":
            if child.get(q(W, "type")) in ("page", "column"):
                return None
            out.append("\n")
        elif tag == "cr":
            out.append("\n")
        elif tag == "noBreakHyphen":
            out.append("‑")
        elif tag == "softHyphen":
            out.append("­")
    return "".join(out)


def _field_char(run) -> str | None:
    fc = run.find(q(W, "fldChar"))
    return fc.get(q(W, "fldCharType")) if fc is not None else None


def _link_target(link, part) -> str:
    rid = link.get(q(R, "id"))
    if rid and rid in part.rels:
        rel = part.rels[rid]
        return rel.target_ref if rel.is_external else ""
    anchor = link.get(q(W, "anchor"))
    return f"#{anchor}" if anchor else ""


@dataclass
class Para:
    pieces: list[Piece]
    lead_marks: list
    tail_marks: list
    ppr: object


def read(p, part) -> Para:
    """A paragraph's direct content as pieces (objects carry their elements)."""
    pieces: list[Piece] = []
    lead, tail = [], []
    children = list(p)
    i = 0
    while i < len(children):
        el = children[i]
        tag = local(el)
        i += 1
        if tag in ("pPr", "proofErr") or not isinstance(el.tag, str):
            continue
        if tag in _MARKS:
            (lead if tag in _STARTS else tail).append(el)
            continue
        if tag == "r":
            if _field_char(el) == "begin":
                # A complex field: its instruction (begin … separate) is kept as one object and its result text is
                # translated (a cross-reference reads in English; Word recomputes results when it updates fields).
                group, depth = [el], 1
                while i < len(children):
                    nxt = children[i]
                    kind = _field_char(nxt) if local(nxt) == "r" else None
                    if kind == "separate" and depth == 1:
                        group.append(nxt)
                        i += 1
                        break
                    if kind == "end" and depth == 1:  # no result: the whole field is the object
                        group.append(nxt)
                        i += 1
                        depth = 0
                        break
                    group.append(nxt)
                    i += 1
                    depth += 1 if kind == "begin" else -1 if kind == "end" else 0
                pieces.append(Piece(obj=group))
                continue
            if _field_char(el) in ("separate", "end"):  # a field's end (or one begun in an earlier paragraph)
                pieces.append(Piece(obj=[el]))
                continue
            text = _run_text(el)
            if text is None:
                pieces.append(Piece(obj=[el]))
                continue
            key, bold, italic = _style(el)
            pieces.append(Piece(text=text, style=key, bold=bold, italic=italic, payload=el))
            continue
        if tag == "hyperlink":
            runs = [c for c in el if local(c) == "r"]
            texts = [_run_text(r) for r in runs]
            if runs and all(t is not None for t in texts) and len(runs) == len([c for c in el if isinstance(c.tag, str)]):
                key, bold, italic = _style(runs[0])
                pieces.append(Piece(text="".join(texts), style=key, bold=bold, italic=italic, payload=el,
                                    link=_link_target(el, part)))
            else:  # a link with a field inside (a table of contents entry): kept as it is
                pieces.append(Piece(obj=[el]))
            continue
        pieces.append(Piece(obj=[el]))  # fldSimple, sdt, oMath, …
    return Para(pieces, lead, tail, p.find(q(W, "pPr")))


# ---- kinds and where ---------------------------------------------------------- #


class Styles:
    def __init__(self, main: DocumentPart):
        self.names: dict[str, str] = {}
        self.outline: dict[str, int] = {}
        try:
            root = main._styles_part.element
        except Exception:  # noqa: BLE001 — a document without styles
            return
        for st in root.iter(q(W, "style")):
            sid = st.get(q(W, "styleId"))
            name = st.find(q(W, "name"))
            if sid:
                self.names[sid] = (name.get(q(W, "val")) if name is not None else sid).lower()
                lvl = st.find(f"{q(W, 'pPr')}/{q(W, 'outlineLvl')}")
                if lvl is not None:
                    self.outline[sid] = int(lvl.get(q(W, "val"), "9"))

    def kind(self, p) -> tuple[str, int]:
        ppr = p.find(q(W, "pPr"))
        sid = ppr.find(q(W, "pStyle")).get(q(W, "val")) if ppr is not None and ppr.find(q(W, "pStyle")) is not None else ""
        name = self.names.get(sid, sid.lower())
        if name == "title":
            return "heading", 1
        if name.startswith("heading") and name[7:].strip().isdigit():
            return "heading", int(name[7:].strip())
        level = self.outline.get(sid)
        own = ppr.find(q(W, "outlineLvl")) if ppr is not None else None
        if own is not None:
            level = int(own.get(q(W, "val"), "9"))
        if level is not None and level < 9:
            return "heading", level + 1
        if (ppr is not None and ppr.find(q(W, "numPr")) is not None) or name.startswith("list"):
            return "list", 1
        return "paragraph", 1


def _ancestor(el, tag: str):
    parent = el.getparent()
    while parent is not None:
        if parent.tag == q(W, tag):
            return parent
        parent = parent.getparent()
    return None


def _where(p, story: Story, tables: dict) -> tuple[str, str]:
    """(kind override or "", where) for a paragraph."""
    if story.name in ("footnote", "endnote"):
        note = _ancestor(p, story.name)
        return "note", f"{story.name.capitalize()} {note.get(q(W, 'id')) if note is not None else ''}".strip()
    if story.name in ("header", "footer"):
        return story.name, story.name.capitalize()
    if _ancestor(p, "txbxContent") is not None:
        return "", "Text box"
    tc = _ancestor(p, "tc")
    if tc is not None:
        tr, tbl = tc.getparent(), _ancestor(tc, "tbl")
        row = [r for r in tbl if local(r) == "tr"].index(tr) + 1 if tbl is not None and tr is not None else 0
        col = [c for c in tr if local(c) == "tc"].index(tc) + 1 if tr is not None else 0
        return "cell", f"Table {tables.get(tbl, '?')} · R{row}C{col}"
    return "", "Body"


# ---- extract ------------------------------------------------------------------ #


def _picture_part(story: Story, pic):
    """(the image part of a picture, whether it is linked rather than in the file)."""
    rid, linked = pictures.blip_rid(pic)
    if not rid or linked:
        return None, linked
    try:
        return story.part.related_parts.get(rid), False
    except Exception:  # noqa: BLE001 — a broken relationship
        return None, False


def extract(data: bytes, finder: pictures.Finder | None = None) -> tuple[list[Unit], dict]:
    main = open_document(data)
    tracked = prepare(main)
    styles = Styles(main)
    info = {"tracked_changes": tracked, "not_translated": {}, "format": "docx"}
    skipped = info["not_translated"]
    body, header, footer, notes = [], [], [], []
    n_pictures: dict[str, int] = {}
    for story in stories(main):
        tables = {t: i for i, t in enumerate(story.root.iter(q(W, "tbl")), start=1)}
        out = {"body": body, "header": header, "footer": footer}.get(story.name, notes)
        for index, p in enumerate(paragraphs(story)):
            para = read(p, story.part)
            for piece in para.pieces:
                if piece.is_object:
                    tag = local(piece.obj[0])
                    label = {"oMath": "equations", "oMathPara": "equations", "sdt": "content controls",
                             "fldSimple": "simple fields"}.get(tag)
                    if label:
                        skipped[label] = skipped.get(label, 0) + 1
            enc = markup.encode(para.pieces)
            override, where = _where(p, story, tables)
            if enc.text.strip():
                kind, level = styles.kind(p)
                kind = override or kind
                source = prefix(kind, level) + enc.text
                out.append(segment(0, 0, kind, source, markup.plain(para.pieces), where, f"{story.part.partname}#{index}"))
            if finder is None:
                continue
            for k, (container, pic) in enumerate(pictures.word_pictures(p, in_fallback)):
                n_pictures[story.name] = n_pictures.get(story.name, 0) + 1
                part, linked = _picture_part(story, pic)
                docpr = container.find(q(pictures.WP, "docPr"))
                nv = docpr if pictures.decorative(docpr) else pic.find(f"{q(pictures.PIC, 'nvPicPr')}/{q(pictures.PIC, 'cNvPr')}")
                out.extend(finder.add(f"{story.part.partname}#{index}/pic{k}", f"{where} · picture {n_pictures[story.name]}",
                                      getattr(part, "blob", None), getattr(part, "content_type", ""),
                                      pictures.word_size(container, pic), nv, linked=linked,
                                      descr=pictures.word_descr(container, pic)))
    if (comments := _comment_count(main)):
        skipped["comments"] = comments
    units: list[Unit] = []
    current = Unit("Part 1")
    size = 0
    for seg in body:
        top = seg["kind"] == "heading" and seg["source"].startswith(("# ", "## "))
        if current.segments and (size >= MAX_PART_CHARS or (top and size >= PART_CHARS)):
            units.append(current)
            current, size = Unit(f"Part {len(units) + 1}"), 0
        current.segments.append(seg)
        size += len(seg["source"])
    units.append(current)
    units[0].segments = header + units[0].segments + footer
    if notes:
        units.append(Unit("Notes", notes))
    return [u for u in units if u.segments], info


def _comment_count(main: DocumentPart) -> int:
    for rel in main.rels.values():
        if not rel.is_external and rel.reltype == RT.COMMENTS:
            part = rel.target_part
            root = part.element if hasattr(part, "element") else etree.fromstring(part.blob)
            return len(root.findall(q(W, "comment")))
    return 0


# ---- write -------------------------------------------------------------------- #


def _text_children(text: str) -> list:
    out = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            t = etree.Element(q(W, "t"))
            t.text = buf
            t.set(XML_SPACE, "preserve")
            out.append(t)
            buf = ""

    for ch in text:
        if ch in "\t\n":
            flush()
            out.append(etree.Element(q(W, "tab" if ch == "\t" else "br")))
        elif ch == "‑":
            flush()
            out.append(etree.Element(q(W, "noBreakHyphen")))
        else:
            buf += ch
    flush()
    return out


def _english(rpr) -> None:
    for el in rpr.iter(q(W, "rFonts")):
        el.attrib.pop(q(W, "hint"), None)
    lang = rpr.find(q(W, "lang"))
    if lang is None:
        lang = etree.SubElement(rpr, q(W, "lang"))
    lang.set(q(W, "val"), LANG)


def _run(text: str, like_run) -> object:
    r = etree.Element(q(W, "r"))
    rpr = like_run.find(q(W, "rPr")) if like_run is not None and local(like_run) == "r" else None
    rpr = copy.deepcopy(rpr) if rpr is not None else etree.Element(q(W, "rPr"))
    _english(rpr)
    r.append(rpr)
    for child in _text_children(text):
        r.append(child)
    return r


def _first_run(link):
    return next((c for c in link if local(c) == "r"), None)


def rebuild(p, para: Para, enc: markup.Encoded, dec: markup.Decoded, bookmark: tuple[int, str] | None = None) -> None:
    for child in list(p):
        if child is not para.ppr:
            p.remove(child)
    content = []
    if bookmark:
        start = etree.Element(q(W, "bookmarkStart"), {q(W, "id"): str(bookmark[0]), q(W, "name"): bookmark[1]})
        content += [start, etree.Element(q(W, "bookmarkEnd"), {q(W, "id"): str(bookmark[0])})]
    content += para.lead_marks
    for piece in enc.lead:
        content += piece.obj
    for out in dec.out:
        if out.obj is not None:
            content += out.obj.obj
        elif out.link and out.like is not None and local(out.like.payload) == "hyperlink":
            link = copy.deepcopy(out.like.payload)
            first = _first_run(link)
            for child in list(link):
                if local(child) == "r":
                    link.remove(child)
            link.append(_run(out.text, first))
            content.append(link)
        elif out.text:
            like = out.like.payload if out.like is not None else None
            content.append(_run(out.text, _first_run(like) if like is not None and local(like) == "hyperlink" else like))
    for piece in dec.moved:  # objects the translation lost: kept, before the end
        content += piece.obj
    for piece in enc.tail:
        content += piece.obj
    content += para.tail_marks
    for el in content:
        p.append(el)


def write(data: bytes, segments: list[dict], marks: bool = False) -> tuple[bytes, Report]:
    """The original document with the translations in place (segments without a translation keep their text);
    a picture's translated text becomes its alt text and, in the body, a caption under it."""
    main = open_document(data)
    prepare(main)
    by_loc = {s["loc"]: s for s in segments if s.get("loc") and s.get("kind") not in ("figure", "alt")}
    figures, alts = pictures.by_place(segments)
    caption_style = next((sid for sid, name in Styles(main).names.items() if name == "caption"), None)
    report = Report()
    bookmark_id = 900_000
    has_toc = False
    for story in stories(main):
        twins = fallback_twins(story.root, q(W, "p"))
        for index, p in enumerate(paragraphs(story)):
            has_toc = has_toc or any("TOC" in (t.text or "") for t in p.iter(q(W, "instrText")))
            if figures or alts:
                _write_pictures(p, story, index, figures, alts, caption_style, report)
            seg = by_loc.get(f"{story.part.partname}#{index}")
            if seg is None:
                continue
            para = read(p, story.part)
            enc = markup.encode(para.pieces)
            source = without_prefix(seg["source"], seg["kind"])
            if enc.text != source:
                report.mismatch.append(seg["id"])
                continue
            target = seg.get("target")
            if not seg.get("translatable", True) or not target:
                report.unchanged += 1
                if marks:
                    bookmark_id += 1
                    _mark(p, bookmark_id, seg["id"])
                continue
            dec = markup.decode(without_prefix(target, seg["kind"]), enc)
            if dec.simplified or enc.simplified:
                report.formatting_simplified.append(seg["id"])
            if dec.moved:
                report.anchors_moved.append(seg["id"])
            bookmark_id += 1
            rebuild(p, para, enc, dec, (bookmark_id, _bookmark(seg["id"])) if marks else None)
            if (twin := twins.get(p)) is not None:
                twin_para = read(twin, story.part)
                twin_enc = markup.encode(twin_para.pieces)
                rebuild(twin, twin_para, twin_enc, markup.decode(without_prefix(target, seg["kind"]), twin_enc))
            report.written += 1
    pictures.count_figures(segments, report)
    _document_language(main)
    if has_toc:
        _update_fields_on_open(main)
    out = io.BytesIO()
    main.package.save(out)
    return out.getvalue(), report


def _write_pictures(p, story: Story, index: int, figures: dict[str, dict], alts: dict[str, dict], caption_style: str | None,
                    report: Report) -> None:
    """The pictures this paragraph holds: their alt text, and (in the body) a caption paragraph after each with the
    English of the text in it."""
    after = p
    for k, (container, pic) in enumerate(pictures.word_pictures(p, in_fallback)):
        loc = f"{story.part.partname}#{index}/pic{k}"
        figure, alt = figures.get(loc), alts.get(loc)
        if figure is None and alt is None:
            continue
        if figure is not None:
            part, _ = _picture_part(story, pic)
            if part is None or pictures.digest(part.blob) != figure.get("sha1"):
                if figure["id"] not in report.mismatch:
                    report.mismatch.append(figure["id"])
                figure = None
        descr = pictures.new_alt_text(pictures.word_descr(container, pic), figure, alt, report)
        if descr is not None:
            for el in pictures.word_alt_targets(container, pic):
                pictures.describe(el, descr)
            report.pictures["alt_text"] += 1
        text = pictures.plain_lines(figure.get("target") or "") if figure is not None and figure.get("translatable", True) else ""
        if text and story.name == "body":
            caption = _caption(text, caption_style)
            after.addnext(caption)
            after = caption
            report.pictures["captions"] += 1


def _caption(text: str, style: str | None):
    """A caption paragraph: the document's Caption style, or small italic text if it has none."""
    p = etree.Element(q(W, "p"))
    ppr = etree.SubElement(p, q(W, "pPr"))
    rpr = etree.Element(q(W, "rPr"))
    if style:
        etree.SubElement(ppr, q(W, "pStyle"), {q(W, "val"): style})
    else:
        etree.SubElement(rpr, q(W, "i"))
        etree.SubElement(rpr, q(W, "sz"), {q(W, "val"): "18"})
    etree.SubElement(rpr, q(W, "lang"), {q(W, "val"): LANG})
    r = etree.SubElement(p, q(W, "r"))
    r.append(rpr)
    for child in _text_children(text):
        r.append(child)
    return p


def _bookmark(seg_id: str) -> str:
    return "_seg_" + seg_id.replace(".", "_")


def _mark(p, bookmark_id: int, seg_id: str) -> None:
    ppr = p.find(q(W, "pPr"))
    at = 1 if ppr is not None else 0
    p.insert(at, etree.Element(q(W, "bookmarkEnd"), {q(W, "id"): str(bookmark_id)}))
    p.insert(at, etree.Element(q(W, "bookmarkStart"), {q(W, "id"): str(bookmark_id), q(W, "name"): _bookmark(seg_id)}))


def _document_language(main: DocumentPart) -> None:
    try:
        styles = main._styles_part.element
    except Exception:  # noqa: BLE001
        return
    defaults = styles.find(q(W, "docDefaults"))
    if defaults is None:
        defaults = etree.Element(q(W, "docDefaults"))
        styles.insert(0, defaults)
    rpr_default = defaults.find(q(W, "rPrDefault"))
    if rpr_default is None:
        rpr_default = etree.SubElement(defaults, q(W, "rPrDefault"))
    rpr = rpr_default.find(q(W, "rPr"))
    if rpr is None:
        rpr = etree.SubElement(rpr_default, q(W, "rPr"))
    lang = rpr.find(q(W, "lang"))
    if lang is None:
        lang = etree.SubElement(rpr, q(W, "lang"))
    lang.set(q(W, "val"), LANG)


def _update_fields_on_open(main: DocumentPart) -> None:
    """A table of contents lists the headings as they were: Word rebuilds it from the translated ones on opening."""
    settings = main._settings_part.element
    if settings.find(q(W, "updateFields")) is None:
        etree.SubElement(settings, q(W, "updateFields"), {q(W, "val"): "true"})

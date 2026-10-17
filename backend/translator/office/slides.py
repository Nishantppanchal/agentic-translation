"""PowerPoint presentations (.pptx, .pptm), read and written with python-pptx.

What is translated: every slide in order — text in shapes (groups included), placeholders, tables (merged cells
once) — and its speaker notes. A slide is a "page". Not translated, and reported: SmartArt, chart text, slide
layouts and masters. Text that grows by more than a tenth in English is set to shrink to fit (`normAutofit` with a
font scale), as PowerPoint does itself.
"""

from __future__ import annotations

import copy
import io
import math
import re

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.enum.lang import MSO_LANGUAGE_ID
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.shapes.picture import Picture

from . import markup, pictures
from .common import LANG, R, Report, Unit, A, local, prefix, q, segment, without_prefix
from .markup import Piece

_NOISE_ATTRS = {"lang", "altLang", "dirty", "err", "smtClean", "smtId", "noProof", "bmk"}
_TITLES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.VERTICAL_TITLE}


def open_presentation(data: bytes):
    return Presentation(io.BytesIO(data))


def _rpr_key(rpr) -> str:
    if rpr is None:
        return ""
    rpr = copy.deepcopy(rpr)
    for attr in _NOISE_ATTRS:
        rpr.attrib.pop(attr, None)
    return etree.tostring(rpr, method="c14n").decode()


def _link(rpr, part) -> str | None:
    click = rpr.find(q(A, "hlinkClick")) if rpr is not None else None
    if click is None:
        return None
    rid = click.get(q(R, "id"))
    if rid and rid in part.rels and part.rels[rid].is_external:
        return part.rels[rid].target_ref
    return ""


def read(p, part) -> tuple[list[Piece], object, object]:
    """(pieces, a:pPr, a:endParaRPr) of a paragraph."""
    pieces: list[Piece] = []
    ppr = end = None
    for el in p:
        tag = local(el)
        if tag == "pPr":
            ppr = el
        elif tag == "endParaRPr":
            end = el
        elif tag == "r":
            rpr = el.find(q(A, "rPr"))
            t = el.find(q(A, "t"))
            pieces.append(Piece(text=t.text or "" if t is not None else "", style=_rpr_key(rpr),
                                bold=rpr is not None and rpr.get("b") == "1", italic=rpr is not None and rpr.get("i") == "1",
                                link=_link(rpr, part), payload=el))
        elif tag == "br":
            # A line break: text of the run before it (so it never splits a stretch).
            prev = next((x for x in reversed(pieces) if not x.is_object), None)
            if prev is not None and pieces[-1] is prev:
                prev.text += "\n"
            else:
                pieces.append(Piece(text="\n", style=_rpr_key(el.find(q(A, "rPr"))), payload=el))
        elif isinstance(el.tag, str):
            pieces.append(Piece(obj=[el]))  # a:fld (slide number, date…)
    return pieces, ppr, end


def _english(rpr) -> None:
    rpr.set("lang", LANG)
    rpr.attrib.pop("altLang", None)
    rpr.attrib.pop("err", None)
    rpr.attrib.pop("dirty", None)


def _runs(text: str, like) -> list:
    """a:r elements (and a:br for line breaks) with the formatting of `like` (an a:r or a:br)."""
    rpr = like.find(q(A, "rPr")) if like is not None else None
    out = []
    for i, line in enumerate(text.split("\n")):
        if i:
            br = etree.Element(q(A, "br"))
            if rpr is not None:
                br.append(copy.deepcopy(rpr))
            out.append(br)
        if line:
            r = etree.Element(q(A, "r"))
            new = copy.deepcopy(rpr) if rpr is not None else etree.Element(q(A, "rPr"))
            new.tag = q(A, "rPr")
            _english(new)
            r.append(new)
            t = etree.SubElement(r, q(A, "t"))
            t.text = line
            out.append(r)
    return out


def rebuild(p, ppr, end, enc: markup.Encoded, dec: markup.Decoded) -> None:
    for child in list(p):
        p.remove(child)
    if ppr is not None:
        p.append(ppr)
    for piece in enc.lead:
        for el in piece.obj:
            p.append(el)
    for out in dec.out:
        if out.obj is not None:
            for el in out.obj.obj:
                p.append(el)
        elif out.text:
            like = out.like.payload if out.like is not None else None
            for el in _runs(out.text, like):
                p.append(el)
    for piece in [*dec.moved, *enc.tail]:
        for el in piece.obj:
            p.append(el)
    if end is not None:
        p.append(end)


# ---- walking a presentation --------------------------------------------------- #


def _shapes(shapes):
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _shapes(shape.shapes)
        else:
            yield shape


def text_frames(prs) -> list[tuple[int, str, object, list[tuple[object, str, object, dict | None]]]]:
    """[(slide number, part name, part, [(txBody, where, shape or None, cell or None)])] in reading order: shapes,
    tables, then the notes (a shape is given for text that may need to shrink: not table cells or notes; a table
    cell's place: {table, row, col, rows, cols}, for showing the table as a table)."""
    out = []
    for number, slide in enumerate(prs.slides, start=1):
        bodies = []
        for shape in _shapes(slide.shapes):
            name = shape.name or "Shape"
            if shape.is_placeholder and shape.placeholder_format.type in _TITLES:
                name = "Title"
            if shape.has_text_frame:
                bodies.append((shape.text_frame._txBody, f"Slide {number} · {name}", shape, None))
            if getattr(shape, "has_table", False) and shape.has_table:
                table = f"{slide.part.partname}#t{shape.shape_id}"
                for r, row in enumerate(shape.table.rows, start=1):
                    for c, cell in enumerate(row.cells, start=1):
                        if not cell.is_spanned:
                            place = {"table": table, "row": r, "col": c, "rows": cell.span_height, "cols": cell.span_width}
                            bodies.append((cell.text_frame._txBody, f"Slide {number} · Table R{r}C{c}", None, place))
        out.append((number, str(slide.part.partname), slide.part, bodies))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide
            out.append((number, str(notes.part.partname), notes.part,
                        [(notes.notes_text_frame._txBody, f"Slide {number} · Notes", None, None)]))
    return out


def _skipped(prs) -> dict[str, int]:
    found: dict[str, int] = {}
    for slide in prs.slides:
        for shape in _shapes(slide.shapes):
            if getattr(shape, "has_chart", False) and shape.has_chart:
                found["chart text"] = found.get("chart text", 0) + 1
            el = shape._element
            if local(el) == "graphicFrame" and el.find(f".//{q(A, 'graphicData')}") is not None and \
                    "diagram" in (el.find(f".//{q(A, 'graphicData')}").get("uri") or ""):
                found["SmartArt"] = found.get("SmartArt", 0) + 1
    return found


def slide_pictures(slide) -> list:
    """The pictures on a slide (in groups too), in shape order."""
    return [shape for shape in _shapes(slide.shapes) if isinstance(shape, Picture)]


def _picture_loc(slide, shape) -> str:
    return f"{slide.part.partname}#pic{shape.shape_id}"


def _image(shape) -> tuple[bytes | None, str, bool]:
    """(bytes, content type, linked) of a picture shape's image."""
    rid, linked = pictures.blip_rid(shape._element)
    if linked or not rid:
        return None, "", linked
    try:
        return shape.image.blob, shape.image.content_type, False
    except Exception:  # noqa: BLE001 — a broken or missing image
        return None, "", False


def _cnvpr(shape):
    return shape._element.find(f"{q(_P, 'nvPicPr')}/{q(_P, 'cNvPr')}")


def extract(data: bytes, finder: pictures.Finder | None = None) -> tuple[list[Unit], dict]:
    prs = open_presentation(data)
    slides = {str(slide.part.partname): slide for slide in prs.slides}
    units: dict[int, Unit] = {}
    for number, partname, part, bodies in text_frames(prs):
        unit = units.setdefault(number, Unit(f"Slide {number}"))
        index = 0
        for body, where, _shape, cell in bodies:
            for p in body.iter(q(A, "p")):
                pieces, _, _ = read(p, part)
                enc = markup.encode(pieces)
                if enc.text.strip():
                    kind = "note" if where.endswith("Notes") else "heading" if "· Title" in where else "paragraph"
                    source = prefix(kind) + enc.text
                    seg = segment(0, 0, kind, source, markup.plain(pieces), where, f"{partname}#{index}")
                    if cell:
                        seg["cell"] = cell
                    unit.segments.append(seg)
                index += 1
        if finder is not None and (slide := slides.get(partname)) is not None:  # the slide's pictures, before its notes
            for k, shape in enumerate(slide_pictures(slide), start=1):
                blob, content_type, linked = _image(shape)
                size = (int(shape.width or 0), int(shape.height or 0))
                cnvpr = _cnvpr(shape)
                unit.segments.extend(finder.add(_picture_loc(slide, shape), f"Slide {number} · picture {k}", blob, content_type,
                                                size, cnvpr, linked=linked, descr=cnvpr.get("descr") if cnvpr is not None else None))
    ordered = [units[n] for n in sorted(units)]
    return ordered, {"format": "pptx", "not_translated": _skipped(prs)}


def _write_pictures(prs, segments: list[dict], report: Report) -> None:
    """A picture's alt text (translated, with the English of the text in it), and that English under "Text in
    pictures (English)" in the slide's notes (created if the slide has none)."""
    figures, alts = pictures.by_place(segments)
    if not figures and not alts:
        return
    for slide in prs.slides:
        lines = []
        for k, shape in enumerate(slide_pictures(slide), start=1):
            loc = _picture_loc(slide, shape)
            figure, alt = figures.get(loc), alts.get(loc)
            if figure is None and alt is None:
                continue
            if figure is not None:
                blob, _, _ = _image(shape)
                if blob is None or pictures.digest(blob) != figure.get("sha1"):
                    if figure["id"] not in report.mismatch:
                        report.mismatch.append(figure["id"])
                    figure = None
            cnvpr = _cnvpr(shape)
            descr = pictures.new_alt_text(cnvpr.get("descr") if cnvpr is not None else None, figure, alt, report)
            if descr is not None and cnvpr is not None:
                pictures.describe(cnvpr, descr)
                report.pictures["alt_text"] += 1
            text = pictures.plain_lines(figure.get("target") or "") if figure is not None and figure.get("translatable", True) else ""
            if text:
                lines.append(f"Picture {k}: {text}")
        if lines and _add_notes(slide, lines):
            report.pictures["notes"] += len(lines)


def _add_notes(slide, lines: list[str]) -> bool:
    frame = slide.notes_slide.notes_text_frame
    if frame is None:  # a notes page without a body placeholder
        return False
    first = frame.paragraphs[0] if len(frame.paragraphs) == 1 and not frame.text.strip() else None
    if first is None and frame.text.strip():
        frame.add_paragraph()  # a blank line after the speaker's own notes
    for i, line in enumerate(["Text in pictures (English):", *lines]):
        para = first if (i == 0 and first is not None) else frame.add_paragraph()
        para.text = line
        for run in para.runs:
            run.font.language_id = MSO_LANGUAGE_ID.ENGLISH_UK
            if i == 0:
                run.font.bold = True
    return True


def write(data: bytes, segments: list[dict], marks: bool = False) -> tuple[bytes, Report]:
    prs = open_presentation(data)
    by_loc = {s["loc"]: s for s in segments if s.get("loc") and s.get("kind") not in ("figure", "alt")}
    report = Report()
    for _number, partname, part, bodies in text_frames(prs):
        index = 0
        for body, where, shape, _cell in bodies:
            grew = False
            room = _room(body, shape, where.endswith("· Title")) if shape is not None else None
            for p in body.iter(q(A, "p")):
                seg = by_loc.get(f"{partname}#{index}")
                index += 1
                if seg is None:
                    continue
                pieces, ppr, end = read(p, part)
                enc = markup.encode(pieces)
                if enc.text != without_prefix(seg["source"], seg["kind"]):
                    report.mismatch.append(seg["id"])
                    continue
                target = seg.get("target")
                if not seg.get("translatable", True) or not target:
                    report.unchanged += 1
                    continue
                dec = markup.decode(without_prefix(target, seg["kind"]), enc)
                grew = grew or _width("".join(o.text for o in dec.out)) > _width(markup.plain(pieces))
                if dec.simplified or enc.simplified:
                    report.formatting_simplified.append(seg["id"])
                if dec.moved:
                    report.anchors_moved.append(seg["id"])
                rebuild(p, ppr, end, enc, dec)
                report.written += 1
            if grew and room is not None and (scale := _shrink(body, room)):
                report.autofit.append({"where": where, "scale": round(scale, 2)})
    _write_pictures(prs, segments, report)
    pictures.count_figures(segments, report)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue(), report


_WIDE = re.compile(r"[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6]")


def _width(text: str) -> float:
    """Text width in ems, roughly: a CJK (full-width) character is one em, anything else about half."""
    return sum(1.0 if _WIDE.match(ch) else 0.48 for ch in text)


_P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _lvl1_size(el) -> float | None:
    """The first-level default font size an element's list style sets (pt), if any."""
    if el is None:
        return None
    d = el.find(f".//{q(A, 'lvl1pPr')}/{q(A, 'defRPr')}")
    return int(d.get("sz")) / 100 if d is not None and d.get("sz") else None


def _inherited_size(shape, title: bool) -> float:
    """The font size a shape's text gets when its runs don't set one: its own list style, then (a placeholder) the
    layout's and the master's placeholder, then the master's title or body text style. python-pptx doesn't resolve
    this; 18 pt if nothing says."""
    chain, el = [], shape
    for _ in range(3):
        if el is None:
            break
        chain.append(el)
        el = getattr(el, "_base_placeholder", None) if getattr(el, "is_placeholder", False) else None
    for el in chain:
        body = el._element.find(f".//{q(_P, 'txBody')}")
        if (size := _lvl1_size(body.find(q(A, "lstStyle")) if body is not None else None)) is not None:
            return size
    try:
        master = shape.part.slide_layout.slide_master.element
    except Exception:  # noqa: BLE001 — not on a slide
        return 18.0
    styles = master.find(q(_P, "txStyles"))
    if styles is not None and getattr(shape, "is_placeholder", False):
        style = styles.find(q(_P, "titleStyle" if title else "bodyStyle"))
        if (size := _lvl1_size(style)) is not None:
            return size
    return 18.0


def _room(body, shape, title: bool) -> tuple[float, float, float, float] | None:
    """(text width, height available, height the original text needs, default font size) in points, before the
    translation is written:
    a box the original already overflows (templates often do) isn't held against the translation."""
    body_pr = body.find(q(A, "bodyPr"))
    if body_pr is None or body_pr.find(q(A, "spAutoFit")) is not None:
        return None
    try:
        width, height = int(shape.width or 0), int(shape.height or 0)
    except Exception:  # noqa: BLE001 — a shape without a size of its own
        return None
    emu_pt = 12700
    w = (width - int(body_pr.get("lIns", 91440)) - int(body_pr.get("rIns", 91440))) / emu_pt
    h = (height - int(body_pr.get("tIns", 45720)) - int(body_pr.get("bIns", 45720))) / emu_pt
    if w <= 0 or h <= 0:
        return None
    default = _inherited_size(shape, title)
    return w, h, _needed(body, w, default), default


def _needed(body, w: float, default: float) -> float:
    """Height the text needs at 100% (pt): lines from its width in ems at its font size, 1.2 line spacing."""
    needed = 0.0
    for p in body.iter(q(A, "p")):
        rpr = next((r for r in p.iter(q(A, "rPr"), q(A, "endParaRPr")) if r.get("sz")), None)
        size = int(rpr.get("sz")) / 100 if rpr is not None else default
        text = "".join(t.text or "" for t in p.iter(q(A, "t")))
        needed += max(1, math.ceil(_width(text) * size / w)) * size * 1.2
    return needed


def _shrink(body, room) -> float | None:
    """If the translation overflows the room its shape has (see _room), let it shrink to fit (`normAutofit` with the
    font scale PowerPoint would choose: lines and line height both shrink, so √ of the height ratio) → the scale."""
    w, h, before, default = room
    needed = _needed(body, w, default)
    capacity = max(h, before)
    if needed <= capacity:
        return None
    scale = max(0.6, min(1.0, math.sqrt(capacity / needed)))
    from pptx.text.text import TextFrame

    TextFrame(body, None).auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    fit = body.find(q(A, "bodyPr")).find(q(A, "normAutofit"))
    fit.set("fontScale", str(int(scale * 100000)))
    if scale < 0.9:
        fit.set("lnSpcReduction", "10000")
    return scale

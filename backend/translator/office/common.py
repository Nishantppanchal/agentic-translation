"""What the Word, PowerPoint and Excel readers share: namespaces, segments, and the structure markers (a heading's
`#`, a list item's `- `) that make a segment read like the rest of the app's markdown but aren't written back."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
LANG = "en-GB"  # what the written text is marked as (spell check, hyphenation)

_LETTER = re.compile(r"[^\W\d_]")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_LIST = re.compile(r"^\s{0,3}(?:[-*+]|\d{1,3}[.)])\s+")


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def in_fallback(el) -> bool:
    """Inside mc:Fallback: the copy of an mc:Choice kept for older readers (text boxes are stored twice)."""
    parent = el.getparent()
    while parent is not None:
        if parent.tag == q(MC, "Fallback"):
            return True
        parent = parent.getparent()
    return False


def fallback_twins(root, para_tag: str) -> dict:
    """mc:Choice paragraph → its copy in mc:Fallback (written with the same translation)."""
    twins = {}
    for ac in root.iter(q(MC, "AlternateContent")):
        choice, fallback = ac.find(q(MC, "Choice")), ac.find(q(MC, "Fallback"))
        if choice is None or fallback is None:
            continue
        a, b = list(choice.iter(para_tag)), list(fallback.iter(para_tag))
        if len(a) == len(b):
            twins.update(zip(a, b, strict=True))
    return twins


def prefix(kind: str, level: int = 1) -> str:
    """The markdown a heading or list item is shown with (only in the segment, not in the file)."""
    return "#" * max(1, min(level, 6)) + " " if kind == "heading" else "- " if kind == "list" else ""


def without_prefix(text: str, kind: str) -> str:
    if kind == "heading":
        return _HEADING.sub("", text, count=1)
    if kind == "list":
        return _LIST.sub("", text, count=1)
    return text


def has_letters(text: str) -> bool:
    return bool(_LETTER.search(text))


@dataclass
class Unit:
    """A "page" for translating with context: a part of a Word document, a slide, a sheet."""

    label: str
    segments: list[dict] = field(default_factory=list)


def segment(page: int, n: int, kind: str, source: str, plain_text: str, where: str, loc: str) -> dict:
    """A segment in the app's shape, plus where it is in the file (`loc`, for writing back) and for people (`where`).
    Text without letters (a page number, an amount) is copied, not translated."""
    translatable = has_letters(plain_text)
    return {"id": f"p{page}.{n}", "page": page, "kind": kind, "source": source, "target": None if translatable else source,
            "translatable": translatable, "where": where, "loc": loc}


_WHERE_CELL = re.compile(r"^(?:Slide (\d+) · )?Table (?:(\d+) · )?R(\d+)C(\d+)$")


def table_cell(seg: dict) -> dict | None:
    """Where a Word or PowerPoint table cell sits ({table, row, col, rows, cols}): recorded when the file is read;
    for documents read before that, from where it says it is (no merged cells then)."""
    if seg.get("cell"):
        return seg["cell"]
    m = _WHERE_CELL.match(seg.get("where") or "")
    if not m:
        return None
    slide, table, row, col = m.groups()
    return {"table": f"s{slide}" if slide else f"t{table}", "row": int(row), "col": int(col), "rows": 1, "cols": 1}


def number(units: list[Unit]) -> list[dict]:
    """Give the units' segments their page and id (p<unit>.<n>)."""
    out = []
    for page, unit in enumerate(units, start=1):
        for n, seg in enumerate(unit.segments, start=1):
            out.append({**seg, "id": f"p{page}.{n}", "page": page})
    return out


@dataclass
class Report:
    """What writing the translation back did, for the person to check."""

    written: int = 0
    unchanged: int = 0  # no translation (yet), or copied text
    mismatch: list[str] = field(default_factory=list)  # the file no longer reads like the segment: left as it was
    formatting_simplified: list[str] = field(default_factory=list)
    anchors_moved: list[str] = field(default_factory=list)  # a footnote mark / picture the translation lost: put back
    autofit: list[dict] = field(default_factory=list)  # PowerPoint text that grew: shrunk to fit
    formulas_updated: int = 0
    notes: list[str] = field(default_factory=list)
    # a picture's translated text: as its alt text, a caption under it (Word), a line in the slide's notes (PowerPoint)
    pictures: dict = field(default_factory=lambda: {"alt_text": 0, "alt_translated": 0, "captions": 0, "notes": 0})

    def as_dict(self) -> dict:
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in self.__dict__.items()}

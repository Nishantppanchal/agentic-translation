"""Map segments (from OCR markdown) back to the PDF's own text lines (or OCR'd lines on scanned pages).

The PDF text layer is read as lines with positions and styles. All lines form one normalised
stream (letters/digits only, case-folded), so differences in hyphenation, spacing, markdown
syntax or punctuation don't matter, and a paragraph that continues on the next page aligns too.

- Running headers and footers are matched first, on their own page, so a paragraph that continues
  across a page break can't swallow the footer and header lines in between.
- Paragraph-like segments are aligned in document order with a fuzzy partial match: first within
  their own page(s) (the PDF's text order on a page needn't be reading order, and the same sentence
  may be printed on two pages), then after a moving cursor, then anywhere. Lines already taken by
  another segment are skipped, so a repeated sentence finds its next copy.
- Table segments are aligned cell by cell: each source cell is matched to a line (cells in PDFs
  are separate lines, ruled or not), so the translation can be written cell by cell.
- Segments that still don't align (e.g. OCR misread a line badly) are placed by position: the
  unclaimed lines between the previous and the next aligned segment, in reading order.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import pymupdf
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

MIN_SCORE = 85
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
_TABLE_SEP = re.compile(r"^:?-{2,}:?$")


def norm(text: str) -> str:
    return _NON_WORD.sub("", unicodedata.normalize("NFKC", text or "").casefold())


@dataclass
class Line:
    page: int  # 1-based
    index: int  # position in the document's line list
    rect: pymupdf.Rect
    text: str
    size: float
    color: int
    bold: bool
    italic: bool
    block: int  # PyMuPDF block number on its page
    key: str = ""  # normalised text
    words: list[tuple[pymupdf.Rect, str]] = field(default_factory=list)
    fill: tuple[float, float, float] | None = None  # scanned page: paper colour to paint the source out with


@dataclass
class Unit:
    """Something to rewrite: a segment's lines (or one table cell) and its translated text."""

    segment_id: str
    lines: list[Line]
    target: str
    cell: tuple[int, int] | None = None  # (row, col) for table cells
    rects: list[pymupdf.Rect] | None = None  # only these word boxes (a cell sharing its line with others)
    positional: bool = False  # placed by position between aligned neighbours, not by matching text
    kind: str = ""  # the segment's kind (heading, paragraph…)


@dataclass
class Alignment:
    units: list[Unit] = field(default_factory=list)
    unaligned: list[str] = field(default_factory=list)  # segment ids we couldn't place
    lines: list[Line] = field(default_factory=list)


def read_lines(doc: pymupdf.Document) -> list[Line]:
    lines: list[Line] = []
    for pno, page in enumerate(doc, start=1):
        words: dict[tuple[int, int], list[tuple[pymupdf.Rect, str]]] = {}
        for x0, y0, x1, y1, w, bno, lno, _ in page.get_text("words"):
            words.setdefault((bno, lno), []).append((pymupdf.Rect(x0, y0, x1, y1), w))
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for lno, ln in enumerate(b["lines"]):
                spans = [s for s in ln["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = "".join(s["text"] for s in ln["spans"])
                # The dominant span (most characters) defines the style.
                main = max(spans, key=lambda s: len(s["text"]))
                lines.append(
                    Line(
                        page=pno,
                        index=len(lines),
                        rect=pymupdf.Rect(ln["bbox"]),
                        text=text,
                        size=main["size"],
                        color=main["color"],
                        bold=bool(main["flags"] & 16) or "bold" in main["font"].lower(),
                        italic=bool(main["flags"] & 2) or "italic" in main["font"].lower(),
                        block=b["number"],
                        key=norm(text),
                        words=words.get((b["number"], lno), []),
                    )
                )
    return lines


def markdown_grid(text: str) -> list[list[str]]:
    rows = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if not raw.startswith("|"):
            continue
        cells = [c.strip() for c in raw.strip("|").split("|")]
        if all(_TABLE_SEP.match(c.replace(" ", "")) for c in cells if c):
            continue
        rows.append(cells)
    return rows


class _Stream:
    """Concatenated normalised text of all lines, with a char → line map."""

    def __init__(self, lines: list[Line]):
        self.lines = lines
        parts, owner = [], []
        self.pages: dict[int, tuple[int, int]] = {}  # page → (first char, end char) in the stream
        pos = 0
        for ln in lines:
            parts.append(ln.key)
            owner.extend([ln.index] * len(ln.key))
            a, b = self.pages.get(ln.page, (pos, pos))
            self.pages[ln.page] = (min(a, pos), pos + len(ln.key))
            pos += len(ln.key)
        self.text = "".join(parts)
        self.owner = owner
        self.claimed: set[int] = set()

    def page_span(self, pages: list[int]) -> tuple[int, int] | None:
        spans = [self.pages[p] for p in pages if p in self.pages]
        return (min(a for a, _ in spans), max(b for _, b in spans)) if spans else None

    def find_free(self, key: str, start: int, end: int | None = None) -> tuple[tuple[int, int], list[Line]] | None:
        """Like `find`, skipping occurrences whose lines another segment already took."""
        for _ in range(8):
            hit = self.find(key, start, end)
            if hit is None:
                return None
            found = self.lines_in(*hit)
            if found:
                return hit, found
            start = hit[1]
        return None

    def find(self, key: str, start: int, end: int | None = None) -> tuple[int, int] | None:
        """Best fuzzy occurrence of key in text[start:end] → (abs_start, abs_end) or None. Lines another
        segment already took are left out of the text searched, so a paragraph reads on across a footer
        and the next page's header, and a repeated sentence finds its next copy."""
        end = len(self.text) if end is None else min(end, len(self.text))
        pos = [i for i in range(start, end) if self.owner[i] not in self.claimed]
        hay = "".join(self.text[i] for i in pos)
        if not key or not hay:
            return None
        if len(key) < 8:  # too short for fuzzy matching: exact only
            i = hay.find(key)
            return (pos[i], pos[i + len(key) - 1] + 1) if i >= 0 else None
        if len(key) > len(hay):
            return None
        res = fuzz.partial_ratio_alignment(key, hay, score_cutoff=MIN_SCORE)
        if res is None or res.dest_end <= res.dest_start:
            return None
        a, b = _trim(key, hay, res.dest_start, res.dest_end)
        return pos[a], pos[b - 1] + 1

    def lines_in(self, a: int, b: int) -> list[Line]:
        """Lines with most of their characters inside [a, b)."""
        counts: dict[int, int] = {}
        for i in range(a, min(b, len(self.owner))):
            counts[self.owner[i]] = counts.get(self.owner[i], 0) + 1
        return [
            self.lines[i]
            for i, n in sorted(counts.items())
            if n >= max(1, len(self.lines[i].key) // 2) and i not in self.claimed
        ]


def _trim(key: str, hay: str, a: int, b: int) -> tuple[int, int]:
    """The fuzzy window has the key's length, so when the text differs a little (OCR dropped a character)
    it slides over the neighbouring text — a table cell's "3" just before a paragraph. Drop window
    characters at either end that the key doesn't account for."""
    ops = Levenshtein.opcodes(key, hay[a:b])
    start, end = 0, b - a
    if len(ops) and ops[0].tag == "insert":
        start = ops[0].dest_end
    if len(ops) and ops[-1].tag == "insert":
        end = ops[-1].dest_start
    return (a + start, a + end) if end > start else (a, b)


def _plain(markdown: str, kind: str | None) -> str:
    """Segment source as plain text for matching. Symbols vanish in `norm` anyway; only list
    numbering must go (a numbered heading like "1. Gegenstand" keeps its number — it's printed)."""
    if kind == "list":
        return re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", markdown or "", flags=re.M)
    return markdown or ""


def align(doc: pymupdf.Document, segments: list[dict], targets: dict[str, str],
          scanned: dict[int, list[Line]] | None = None) -> Alignment:
    """`scanned`: OCR'd lines for pages without a text layer (page number → lines)."""
    lines = read_lines(doc)
    if scanned:
        lines = sorted([ln for ln in lines if ln.page not in scanned] + [ln for p in scanned.values() for ln in p],
                       key=lambda ln: ln.page)
        for i, ln in enumerate(lines):
            ln.index = i
    stream = _Stream(lines)
    out = Alignment(lines=lines)
    cursor = 0
    placed: dict[str, list[Line]] = {}
    order: list[dict] = []
    wanted = [
        s for s in segments
        if s.get("kind") != "figure" and s.get("translatable", True) and targets.get(s["id"]) and targets[s["id"]] != s["source"]
    ]

    # Page furniture first, on its own page.
    for seg in wanted:
        if seg.get("kind") in ("header", "footer") and (span := stream.page_span(_pages(seg))):
            if r := stream.find_free(norm(seg["source"]), *span):
                stream.claimed.update(ln.index for ln in r[1])
                out.units.append(Unit(seg["id"], r[1], targets[seg["id"]], kind=seg["kind"]))
                placed[seg["id"]] = r[1]

    for seg in wanted:
        sid, kind = seg["id"], seg.get("kind")
        target = targets[sid]
        order.append(seg)
        if sid in placed:
            continue

        if kind == "table":
            cells = _align_table(stream, seg["source"], target, sid)
            if cells:
                out.units.extend(cells)
                for u in cells:
                    stream.claimed.update(ln.index for ln in u.lines)
                placed[sid] = [ln for u in cells for ln in u.lines]
            else:
                out.unaligned.append(sid)
            continue

        key = norm(_plain(seg["source"], kind))
        window_end = cursor + max(len(key) * 3, len(key) + 400)
        attempts: list[tuple[int, int | None]] = []
        if span := stream.page_span(_pages(seg)):
            attempts += [(max(cursor, span[0]), span[1]), span]
        attempts += [(cursor, window_end), (0, None)]
        result = next((r for a, b in attempts if a < (b if b is not None else len(stream.text)) and (r := stream.find_free(key, a, b))), None)
        if result is None:
            out.unaligned.append(sid)
            continue
        hit, found = result
        stream.claimed.update(ln.index for ln in found)
        out.units.append(Unit(sid, found, target, kind=kind or ""))
        placed[sid] = found
        cursor = max(cursor, hit[1])
    _place_by_position(order, placed, stream, out, targets)
    return out


def _pages(seg: dict) -> list[int]:
    """The page(s) a segment is printed on (a paragraph continued on the next page has both)."""
    return list(seg.get("pages") or ([seg["page"]] if seg.get("page") else []))


def _place_by_position(order: list[dict], placed: dict[str, list[Line]], stream: _Stream, out: Alignment,
                       targets: dict[str, str]) -> None:
    """Unaligned paragraph segments take the unclaimed lines between their aligned neighbours.

    Conservative: only between two aligned segments (never at the start or end, where the gap could be
    anything), and only when the gap holds about as much text as the segments' source."""
    i = 0
    while i < len(order):
        if order[i]["id"] in placed:
            i += 1
            continue
        j = i
        while j < len(order) and order[j]["id"] not in placed:
            j += 1
        if i == 0 or j == len(order):
            i = j
            continue
        run = [s for s in order[i:j] if s.get("kind") != "table"]
        lo = max(ln.index for ln in placed[order[i - 1]["id"]])
        hi = min(ln.index for ln in placed[order[j]["id"]])
        gap = [ln for ln in stream.lines[lo + 1 : hi] if ln.index not in stream.claimed and ln.key]
        want = sum(len(norm(_plain(x["source"], x.get("kind")))) for x in run)
        have = sum(len(ln.key) for ln in gap)
        if run and gap and len(gap) >= len(run) and 0.6 <= have / max(1, want) <= 1.6:
            weights = [max(1, len(norm(s["source"]))) for s in run]
            total, start = sum(weights), 0
            for k, seg in enumerate(run):
                n = len(gap) - start if k == len(run) - 1 else max(1, round(len(gap) * weights[k] / total))
                n = min(n, len(gap) - start - (len(run) - k - 1))
                lines = gap[start : start + n]
                start += n
                stream.claimed.update(ln.index for ln in lines)
                out.units.append(Unit(seg["id"], lines, targets[seg["id"]], positional=True, kind=seg.get("kind") or ""))
                out.unaligned.remove(seg["id"])
        i = j


def _align_table(stream: _Stream, source: str, target: str, sid: str) -> list[Unit]:
    src, tgt = markdown_grid(source), markdown_grid(target)
    if not src:
        return []
    same_shape = len(src) == len(tgt) and all(len(a) == len(b) for a, b in zip(src, tgt))
    units: list[Unit] = []
    taken: set[int] = set()
    for r, row in enumerate(src):
        row_y: float | None = None
        for c, cell in enumerate(row):
            if not same_shape or not re.search(r"[^\W\d_]", cell):  # no letters (numbers, dates): keep as printed
                continue
            new = tgt[r][c]
            if norm(new) == norm(cell):
                continue
            key = norm(cell)
            best, best_score = None, 0.0
            for ln in stream.lines:
                if ln.index in stream.claimed or ln.index in taken or not ln.key:
                    continue
                # A PDF line can hold several cells (columns set close together): match the cell inside it.
                score = fuzz.partial_ratio(key, ln.key) - 3 if len(ln.key) > len(key) * 1.2 else fuzz.ratio(key, ln.key)
                if row_y is not None:
                    score -= min(20.0, abs(ln.rect.y0 - row_y) / 2)  # prefer the same table row
                if score > best_score:
                    best, best_score = ln, score
            if best is not None and best_score >= MIN_SCORE:
                taken.add(best.index)
                row_y = best.rect.y0 if row_y is None else row_y
                units.append(Unit(sid, [best], new, cell=(r, c), rects=_word_subset(best, key)))
    return units


def _word_subset(line: Line, key: str) -> list[pymupdf.Rect] | None:
    """Word boxes of `line` covered by `key`, or None if the cell is the whole line."""
    if len(line.key) - len(key) <= 2 or not line.words:  # anything more is another cell's text (a date…)
        return None
    hit = fuzz.partial_ratio_alignment(key, line.key)
    spans, pos = [], 0
    for rect, word in line.words:
        k = norm(word)
        spans.append((pos, pos + len(k), rect))
        pos += len(k)
    picked = [
        rect
        for a, b, rect in spans
        if b > a and min(b, hit.dest_end) - max(a, hit.dest_start) >= (b - a) / 2
    ]
    return picked or None

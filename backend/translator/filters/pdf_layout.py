"""Layout-preserving translated PDF: erase the source text, typeset the translation in its place.

Only text is removed (images, vector graphics, shading and table rules stay). Each block is
re-typeset with the original size, weight and colour, shrinking if the translation is longer.
A block is erased only if its translation fits (tested on a scratch page first) — otherwise the
source text stays and the report says `overflow`, so nothing is ever silently lost.

Scanned pages (no text layer) come with OCR'd lines (`filters/scan.py`): the source is painted out
with the paper colour sampled around each line, then the translation is typeset on top.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

import pymupdf
from markdown_it import MarkdownIt

from .align import Line, Unit, align

RENDER_VERSION = 9  # bump to invalidate cached renders
FIT_STEPS = (0.55, 0.4)  # minimum scale factors tried, in order
_PAGE_MARGIN = 36
_md = MarkdownIt("commonmark")
_SEVERITY = {"fit": 0, "shrunk": 1, "overflow": 2, "unaligned": 3}


def _fonts() -> tuple[str, pymupdf.Archive]:
    archive = pymupdf.Archive()
    css = pymupdf.css_for_pymupdf_font("notos", CSS=None, archive=archive, name="sans-serif")
    return css + "* {font-family: sans-serif; margin: 0; padding: 0; line-height: 1.18;}", archive


def _style(lines: list[Line]) -> tuple[float, bool, bool, str]:
    weights = [max(1, len(ln.key)) for ln in lines]
    size = statistics.median([ln.size for ln in lines])
    bold = sum(w for ln, w in zip(lines, weights) if ln.bold) * 2 > sum(weights)
    italic = sum(w for ln, w in zip(lines, weights) if ln.italic) * 2 > sum(weights)
    color = Counter(ln.color for ln in lines).most_common(1)[0][0]
    return size, bold, italic, f"#{color:06x}"


def _html(text: str, lines: list[Line], heading: bool = False) -> str:
    size, bold, italic, color = _style(lines)
    if heading and any(ln.fill for ln in lines):
        bold = True  # scans: OCR doesn't report weight, and a heading the reader saw as one is set bold
    rows = []
    for raw in text.splitlines() or [""]:
        raw = raw.strip()
        raw = raw.lstrip("#").strip() if raw.startswith("#") else raw
        rows.append(_md.renderInline(raw))
    style = f"font-size:{size:.1f}pt;color:{color};font-weight:{'bold' if bold else 'normal'};font-style:{'italic' if italic else 'normal'}"
    return f'<div style="{style}">{"<br/>".join(rows)}</div>'


def _split(text: str, weights: list[int]) -> list[str]:
    """Split a translation across pages in proportion to the source on each page, at a word boundary."""
    if len(weights) == 1:
        return [text]
    words = text.split(" ")
    total, parts, start = sum(weights), [], 0
    for w in weights[:-1]:
        n = max(1, round(len(words) * w / total))
        parts.append(" ".join(words[start : start + n]))
        start += n
    parts.append(" ".join(words[start:]))
    return parts


def _obstacles(page: pymupdf.Page) -> list[pymupdf.Rect]:
    rects = [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
    rects += [d["rect"] for d in page.get_drawings() if d["rect"].width > 2 and d["rect"].height > 2]
    return rects


def _erase_rects(unit: Unit, group: list[Line]) -> list[pymupdf.Rect]:
    return list(unit.rects) if unit.rects else [ln.rect for ln in group]


def _box(group: list[Line], unit: Unit, page: pymupdf.Page, page_lines: list[Line], obstacles: list[pymupdf.Rect]) -> pymupdf.Rect:
    parts = _erase_rects(unit, group)
    rect = pymupdf.Rect(parts[0])
    for r in parts[1:]:
        rect |= r
    mine = {ln.index for ln in group}
    others = [ln for ln in page_lines if ln.index not in mine]
    if unit.cell is not None:
        # A table cell may grow right up to the next thing in its row: another line, or the rest of its own line.
        same_row = lambda r: min(r.y1, rect.y1) - max(r.y0, rect.y0) > 2  # noqa: E731
        kept_words = [w for ln in group for w, _ in ln.words if unit.rects and all(w != r for r in unit.rects)]
        right = [r.x0 for r in [ln.rect for ln in others] + kept_words if r.x0 >= rect.x1 - 1 and same_row(r)]
        rect.x1 = min(right) - 4 if right else page.rect.width - _PAGE_MARGIN
        return rect
    # A text block may grow right until the first thing sharing its vertical band (a word or line
    # next to it, another column, an image) — never past the page's text area — then down to the
    # next thing below it.
    text_right = min(page.rect.width - _PAGE_MARGIN, max(ln.rect.x1 for ln in page_lines))
    beside = [
        r.x0
        for r in [ln.rect for ln in others] + obstacles
        if r.x0 >= rect.x1 - 1 and min(r.y1, rect.y1) - max(r.y0, rect.y0) > 1
    ]
    rect.x1 = max(rect.x1, min([text_right] + [x - 6 for x in beside]))
    below = [
        r.y0
        for r in [ln.rect for ln in others] + obstacles
        if r.y0 >= rect.y1 - 1 and min(r.x1, rect.x1) - max(r.x0, rect.x0) > 4
    ]
    # Never above the block's own last line: a footer printed inside the bottom margin keeps its box.
    rect.y1 = max(rect.y1, min(below) - 2 if below else page.rect.height - _PAGE_MARGIN)
    return rect


def render(pdf: bytes, segments: list[dict], targets: dict[str, str], scanned: dict | None = None) -> tuple[bytes, dict]:
    """Translated PDF + report {segments: {id: {status, scale, boxes, matched}}, summary}.
    `scanned`: page number → `scan.ScanPage` (OCR'd lines and figures) for pages without a text layer."""
    scanned = scanned or {}
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    alignment = align(doc, segments, targets, {p: sp.lines for p, sp in scanned.items()})
    css, archive = _fonts()
    scratch = pymupdf.open()

    by_page: dict[int, list[tuple[Unit, list[Line], str]]] = defaultdict(list)
    for unit in alignment.units:
        pages: dict[int, list[Line]] = defaultdict(list)
        for ln in unit.lines:
            pages[ln.page].append(ln)
        groups = list(pages.items())
        parts = _split(unit.target, [sum(len(ln.key) for ln in g) for _, g in groups])
        for (pno, g), part in zip(groups, parts):
            by_page[pno].append((unit, g, part))

    report: dict[str, dict] = {sid: {"status": "unaligned", "scale": None, "boxes": []} for sid in alignment.unaligned}
    for pno, items in sorted(by_page.items()):
        page = doc[pno - 1]
        page_lines = [ln for ln in alignment.lines if ln.page == pno]
        scan_page = scanned.get(pno)
        # On a scan the page image is the whole page: its figures (from layout detection) are the obstacles.
        obstacles = list(scan_page.figures) if scan_page else _obstacles(page)
        sp = scratch.new_page(width=page.rect.width, height=page.rect.height)
        planned = []
        for unit, group, text in items:
            rect = _box(group, unit, page, page_lines, obstacles)
            markup = _html(text, group, unit.kind == "heading")
            status, used, shown = "overflow", None, rect
            for low in FIT_STEPS:
                spare, scale = sp.insert_htmlbox(rect, markup, css=css, archive=archive, scale_low=low)
                if spare >= 0:
                    status, used = ("fit" if scale >= 0.999 else "shrunk"), (low, scale)
                    # Report the area the text actually occupies, not all the room it was allowed.
                    shown = pymupdf.Rect(rect.x0, rect.y0, rect.x1, max(rect.y0 + 4, rect.y1 - spare))
                    break
            entry = report.setdefault(unit.segment_id, {"status": "fit", "scale": 1.0, "boxes": []})
            if unit.positional:
                entry["matched"] = "position"  # placed between its neighbours, not by matching text
            if _SEVERITY[status] > _SEVERITY[entry["status"]]:
                entry["status"] = status
            if used:
                entry["scale"] = min(entry["scale"] or 1.0, round(used[1], 3))
                fill = next((ln.fill for ln in group if ln.fill), None)
                erase = _erase_rects(unit, group)
                if fill and unit.rects:  # scan: paint the cell's words as one span (no glyph remnants between)
                    span = pymupdf.Rect(erase[0])
                    for r in erase[1:]:
                        span |= r
                    erase = [span]
                planned.append((rect, markup, used[0], erase, fill))
            entry["boxes"].append(
                {"page": pno, "rect": [round(v, 1) for v in shown], "width": page.rect.width, "height": page.rect.height, "status": status}
            )
        if scan_page:
            # Paint the printed source out with the paper colour around it (the scan stays underneath).
            for _, _, _, erase, fill in planned:
                for r in erase:
                    r = pymupdf.Rect(r)
                    page.draw_rect(pymupdf.Rect(r.x0 - 2.5, r.y0 - 1, r.x1 + 2.5, r.y1 + 1), color=None, fill=fill or (1, 1, 1), overlay=True)
        else:
            for _, _, _, erase, _ in planned:
                for r in erase:
                    r = pymupdf.Rect(r)
                    pad = r.height * 0.2  # keep clear of neighbouring lines' ascenders/descenders
                    page.add_redact_annot(pymupdf.Rect(r.x0, r.y0 + pad, r.x1, r.y1 - pad), fill=False)
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_NONE,
                graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )
        for rect, markup, low, _, _ in planned:
            page.insert_htmlbox(rect, markup, css=css, archive=archive, scale_low=low)

    counts = Counter(v["status"] for v in report.values())
    summary = {k: counts.get(k, 0) for k in _SEVERITY}
    summary["scanned_pages"] = len(scanned)
    summary["by_position"] = sum(1 for v in report.values() if v.get("matched") == "position")
    # Each typeset block embeds full fonts (Noto Sans, a CJK fallback): subset them to the glyphs
    # used and de-duplicate objects — a 2-page document goes from ~4 MB to ~50 KB.
    doc.subset_fonts()
    out = doc.tobytes(garbage=4, deflate=True, use_objstms=1)
    return out, {"render_version": RENDER_VERSION, "pages": doc.page_count, "segments": report, "summary": summary}

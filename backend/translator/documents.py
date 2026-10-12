"""Document loading (PDF / image / text → pages) and markdown segmentation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

# Scripts written without spaces between words: Thai, Lao, Myanmar, Khmer, kana, CJK, Hangul.
NO_SPACE_CHARS = "\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff"
_NO_SPACE = re.compile(f"[{NO_SPACE_CHARS}]")

IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
TEXT_EXTS = {".txt", ".md", ".markdown"}
# Read directly (no OCR), formatting kept as inline codes: see filters/office.py and filters/xliff.py.
OFFICE_EXTS = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlf": "application/xliff+xml",
    ".xliff": "application/xliff+xml",
}
SUPPORTED_EXTS = {".pdf", *IMAGE_EXTS, *TEXT_EXTS, *OFFICE_EXTS}


@dataclass
class Figure:
    box: tuple[float, float, float, float]  # pixel box on the rendered page image (left, top, right, bottom)
    png: bytes  # cropped figure
    anchor: str | None = None  # PDFs: start of the first text block below the figure (for exact placement)


@dataclass
class Page:
    number: int  # 1-based
    image: bytes | None  # rendered page image, None for plain-text input
    image_mime: str
    text_layer: str  # embedded PDF text (or the raw text for .txt/.md)
    figures: list[Figure] = field(default_factory=list)  # embedded images found in the PDF
    full_page_image: bool = False  # the page is (mostly) one big picture, i.e. a scan
    text_blocks: list[tuple[float, float, float, float, str]] = field(default_factory=list)  # PDF text, pixel boxes

    def anchor_below(self, box: tuple[float, float, float, float]) -> str | None:
        """Start of the first PDF text block below a box, used to place a figure exactly in reading order."""
        below = next((b for b in self.text_blocks if b[1] >= box[3] - 3), None)
        return " ".join(below[4].split())[:60] if below else None

    @property
    def has_text_layer(self) -> bool:
        # Dense scripts (Chinese, Japanese, ...) carry about twice the text per character.
        chars = len(re.sub(r"\s", "", self.text_layer)) + len(_NO_SPACE.findall(self.text_layer))
        return chars >= 40

    @property
    def is_scan(self) -> bool:
        """No usable PDF structure: figures must be located visually."""
        return self.image is not None and (not self.has_text_layer or self.full_page_image)


def guess_mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext in IMAGE_EXTS:
        return IMAGE_EXTS[ext]
    if ext in TEXT_EXTS:
        return "text/markdown"
    return OFFICE_EXTS.get(ext, "application/octet-stream")


MIN_FIGURE_SIDE = 0.06  # of page width/height — skips bullets, rules, small icons
MAX_FIGURE_AREA = 0.85  # bigger than this = a scanned page, not a figure


def _text_blocks(page: pymupdf.Page, dpi: int) -> list[tuple[float, float, float, float, str]]:
    scale = dpi / 72
    blocks = [
        (b[0] * scale, b[1] * scale, b[2] * scale, b[3] * scale, b[4])
        for b in page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, type) — type 0 = text
        if b[6] == 0 and b[4].strip()
    ]
    return sorted(blocks, key=lambda b: (b[1], b[0]))


def _pdf_figures(page: pymupdf.Page, dpi: int, text_blocks: list) -> tuple[list[Figure], bool]:
    """Embedded raster images on a PDF page → (figures, page_is_one_big_image)."""
    pw, ph = page.rect.width, page.rect.height
    scale = dpi / 72
    rects: list[pymupdf.Rect] = []
    full_page = False
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        if r.is_empty:
            continue
        if r.width * r.height > MAX_FIGURE_AREA * pw * ph:
            full_page = True
            continue
        if r.width < MIN_FIGURE_SIDE * pw or r.height < MIN_FIGURE_SIDE * ph:
            continue
        for i, other in enumerate(rects):  # merge overlapping pieces of one picture
            if r.intersects(other):
                rects[i] = other | r
                break
        else:
            rects.append(r)
    rects.sort(key=lambda r: (round(r.y0), r.x0))
    probe = Page(0, None, "", "", text_blocks=text_blocks)
    figures = []
    for r in rects:
        box = (r.x0 * scale, r.y0 * scale, r.x1 * scale, r.y1 * scale)
        png = page.get_pixmap(dpi=max(dpi, 150), clip=r).tobytes("png")
        figures.append(Figure(box=box, png=png, anchor=probe.anchor_below(box)))
    return figures, full_page


def load_pages(data: bytes, filename: str, dpi: int = 150) -> list[Page]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        pages = []
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=dpi)
                blocks = _text_blocks(page, dpi)
                figures, full_page = _pdf_figures(page, dpi, blocks)
                pages.append(
                    Page(i + 1, pix.tobytes("png"), "image/png", page.get_text("text"), figures, full_page, blocks)
                )
        return pages
    if ext in IMAGE_EXTS:
        return [Page(1, data, IMAGE_EXTS[ext], "")]
    if ext in TEXT_EXTS:
        return [Page(1, None, "", data.decode("utf-8", errors="replace"))]
    raise ValueError(f"Unsupported file type: {ext or filename}")


def render_page(data: bytes, filename: str, number: int, dpi: int = 150) -> bytes | None:
    """PNG of one page (1-based) of a PDF or image upload; None for text documents / out of range."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return data if number == 1 else None
    if ext != ".pdf":
        return None
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if not 1 <= number <= doc.page_count:
            return None
        return doc[number - 1].get_pixmap(dpi=dpi).tobytes("png")


def _image_page(png: bytes) -> tuple[pymupdf.Document, pymupdf.Page]:
    """A one-page PDF whose coordinates are the image's pixels (for drawing / cropping)."""
    pix = pymupdf.Pixmap(png)
    doc = pymupdf.open()
    page = doc.new_page(width=pix.width, height=pix.height)
    page.insert_image(page.rect, stream=png)
    return doc, page


def crop_png(png: bytes, box: tuple[float, float, float, float]) -> bytes:
    doc, page = _image_page(png)
    with doc:
        return page.get_pixmap(clip=pymupdf.Rect(box) & page.rect).tobytes("png")


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text).casefold()


def mark_figures(png: bytes, boxes: list[tuple[float, float, float, float]]) -> bytes:
    """Outline figures in red and label them FIGURE 1…n, so the vision engine can place `[[FIGURE n]]` markers."""
    doc, page = _image_page(png)
    with doc:
        size = max(14.0, page.rect.width / 60)
        for n, box in enumerate(boxes, start=1):
            r = pymupdf.Rect(box)
            page.draw_rect(r, color=(0.85, 0, 0), width=max(2.0, size / 6))
            label = f"FIGURE {n}"
            tag = pymupdf.Rect(r.x0, r.y0, r.x0 + size * 0.62 * len(label) + size * 0.6, r.y0 + size * 1.5)
            page.draw_rect(tag, color=(0.85, 0, 0), fill=(0.85, 0, 0))
            page.insert_text((tag.x0 + size * 0.3, tag.y1 - size * 0.4), label, fontsize=size, color=(1, 1, 1))
        return page.get_pixmap().tobytes("png")


def place_figure_marker(markdown: str, n: int, anchor: str | None) -> str:
    """Ensure `[[FIGURE n]]` is present; with an anchor, move it right before the block that starts with it.

    The anchor is the text that follows the figure on the PDF page, so this is exact when it can be
    matched; otherwise the model's own placement is kept (or the marker is appended).
    """
    marker = f"[[FIGURE {n}]]"
    pattern = re.compile(rf"^\s*\[\[\s*FIGURE\s+{n}\s*\]\]\s*$", re.IGNORECASE | re.MULTILINE)
    present = bool(pattern.search(markdown))
    key = _norm(anchor or "")[:25]
    if len(key) >= 8:
        blocks = [b for b in re.split(r"\n\s*\n", pattern.sub("", markdown)) if b.strip()]
        for i, block in enumerate(blocks):
            if key in _norm(block)[: len(key) + 12]:
                return "\n\n".join([*blocks[:i], marker, *blocks[i:]])
    return markdown if present else f"{markdown}\n\n{marker}"


# --------------------------------------------------------------------------- #
# Segmentation
# --------------------------------------------------------------------------- #

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_LIST = re.compile(r"^\s*([-*+]|\d+[.)])\s")
_TABLE = re.compile(r"^\s*\|")
_FENCE = re.compile(r"^\s*(```|~~~)")
_NO_LETTERS = re.compile(r"^[\W\d_]*$", re.UNICODE)
FIGURE_MARKER = re.compile(r"^\s*\[\[\s*FIGURE\s+(\d+)\s*\]\]\s*$", re.IGNORECASE)
PAGE_FURNITURE = re.compile(r"^\s*\[\[\s*(HEADER|FOOTER)\s*\]\]\s*(.*)$", re.IGNORECASE)
FURNITURE = ("header", "footer")


@dataclass
class Block:
    kind: str  # heading | paragraph | list | table | code | figure
    text: str
    pages: tuple[int, ...] | None = None  # set when a paragraph runs across a page break

    @property
    def translatable(self) -> bool:
        return self.kind != "code" and not _NO_LETTERS.match(self.text)


def _kind(line: str) -> str:
    if _HEADING.match(line):
        return "heading"
    if _TABLE.match(line):
        return "table"
    if _LIST.match(line):
        return "list"
    return "paragraph"


def split_blocks(markdown: str) -> list[Block]:
    """Split markdown into translation units: headings, paragraphs, lists, tables, code."""
    blocks: list[Block] = []
    buf: list[str] = []
    buf_kind = "paragraph"
    in_fence = False

    def flush() -> None:
        nonlocal buf, buf_kind
        text = "\n".join(buf).strip("\n")
        if text.strip():
            blocks.append(Block(buf_kind, text))
        buf, buf_kind = [], "paragraph"

    for line in markdown.splitlines():
        if in_fence:
            buf.append(line)
            if _FENCE.match(line):
                in_fence = False
                flush()
            continue
        if _FENCE.match(line):
            flush()
            buf, buf_kind, in_fence = [line], "code", True
            continue
        if not line.strip():
            flush()
            continue
        if m := PAGE_FURNITURE.match(line):  # running header / footer / page number: its own segment
            flush()
            if m.group(2).strip():
                buf, buf_kind = [m.group(2).strip()], m.group(1).lower()
                flush()
            continue
        if FIGURE_MARKER.match(line):
            flush()
            buf, buf_kind = [line.strip()], "figure"
            flush()
            continue
        kind = _kind(line)
        if kind == "heading":
            flush()
            buf, buf_kind = [line], "heading"
            flush()
            continue
        # A change between table / list / paragraph starts a new block (list
        # continuation lines are kept with their list).
        if buf and kind != buf_kind and not (buf_kind == "list" and kind == "paragraph" and line.startswith(" ")):
            flush()
        if not buf:
            buf_kind = kind
        buf.append(line)
    flush()
    return blocks


# A paragraph is finished when it ends with sentence punctuation (optionally followed by closing quotes/brackets).
_SENTENCE_END = re.compile(r"[.!?…:;。！？；：][\"'’”»)\]）」』]*\s*$")
_CONTINUATION_MIN_CHARS = 40  # shorter lines (captions, signatures) are not treated as running text


def _continues(prev: str, nxt: str) -> bool:
    """Does `prev` (end of a page) run on into `nxt` (start of the next page)?"""
    prev, nxt = prev.rstrip(), nxt.lstrip()
    if not prev or not nxt or _SENTENCE_END.search(prev):
        return False
    weight = len(prev) + len(_NO_SPACE.findall(prev))  # Chinese etc. count double
    if weight < _CONTINUATION_MIN_CHARS:
        return False
    if prev.endswith(("-", ",")) or nxt[0].islower():
        return True
    if _NO_SPACE.match(nxt[0]) or _NO_SPACE.search(prev[-1]):
        return True  # no case to go by: missing end punctuation is the signal
    # Next starts with a capital: only for long running text that stops on a lowercase letter
    # (German nouns are capitalised, so "... mit dem Tag der" + "Abnahme." must still join).
    return prev[-1].islower() and weight >= 60


def _join(prev: str, nxt: str) -> str:
    prev, nxt = prev.rstrip(), nxt.lstrip()
    if prev.endswith("-") and len(prev) > 1 and prev[-2].isalpha() and nxt[:1].islower():
        return prev[:-1] + nxt  # hyphenated word split by the page break: "Gewähr-" + "leistungsfrist"
    if _NO_SPACE.search(prev[-1]) or _NO_SPACE.match(nxt[0]):
        return prev + nxt
    return f"{prev} {nxt}"


def join_page_breaks(pages: list[tuple[int, list[Block]]]) -> list[tuple[int, list[Block]]]:
    """Merge a paragraph that runs across a page break into one block (kept on the first page).

    Footers / trailing page numbers at the bottom of one page and headers at the top of the next are
    skipped over when looking for the two halves.
    """
    for (page_no, blocks), (next_no, following) in zip(pages, pages[1:]):
        j = len(blocks) - 1
        # Skip footers and page-number-like blocks ("2", "- 2 -"…; "- 2 -" even parses as a list).
        while j >= 0 and (blocks[j].kind == "footer" or (not blocks[j].translatable and len(blocks[j].text) <= 12)):
            j -= 1
        k = 0
        while k < len(following) and following[k].kind == "header":
            k += 1
        if j < 0 or k >= len(following):
            continue
        last, first = blocks[j], following[k]
        if last.kind != "paragraph" or first.kind != "paragraph" or not _continues(last.text, first.text):
            continue
        blocks[j] = Block("paragraph", _join(last.text, first.text), (*(last.pages or (page_no,)), next_no))
        following.pop(k)
    return pages


def segments_from_pages(
    page_markdown: list[tuple[int, str]], figures: dict[tuple[int, int], dict] | None = None
) -> list[dict]:
    """Turn per-page markdown into segment dicts with stable ids like `p3.2`.

    `[[FIGURE n]]` blocks become figure segments; `figures[(page, n)]` = {"image", "text"}
    supplies the cropped image's artifact name and the text found inside the figure
    (the translatable "legend"). Markers without a known figure are dropped.
    """
    figures = figures or {}
    segments = []
    for page_no, blocks in join_page_breaks([(n, split_blocks(md)) for n, md in page_markdown]):
        i = 0
        for block in blocks:
            if block.kind == "figure":
                n = int(FIGURE_MARKER.match(block.text).group(1))
                meta = figures.get((page_no, n))
                if not meta:
                    continue
                i += 1
                text = (meta.get("text") or "").strip()
                translatable = bool(text) and not _NO_LETTERS.match(text)
                segments.append(
                    {
                        "id": f"p{page_no}.{i}",
                        "page": page_no,
                        "kind": "figure",
                        "source": text,
                        "target": None if translatable else text,
                        "translatable": translatable,
                        "image": meta["image"],
                        "figure": n,
                    }
                )
                continue
            i += 1
            seg = {
                "id": f"p{page_no}.{i}",
                "page": page_no,
                "kind": block.kind,
                "source": block.text,
                "target": None if block.translatable else block.text,
                "translatable": block.translatable,
            }
            if block.pages:
                seg["pages"] = list(block.pages)  # paragraph continues onto the following page(s)
            segments.append(seg)
    return segments


def batch_segments(segments: list[dict], max_chars: int) -> list[list[dict]]:
    """Greedy batching of translatable segments by source length."""
    batches: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for seg in segments:
        if not seg["translatable"]:
            continue
        n = len(seg["source"])
        if cur and size + n > max_chars:
            batches.append(cur)
            cur, size = [], 0
        cur.append(seg)
        size += n
    if cur:
        batches.append(cur)
    return batches


def page_batches(segments: list[dict], max_chars: int) -> list[list[dict]]:
    """One batch per page (translatable segments only), in document order.

    A page longer than `max_chars` is split at segment boundaries, so the parts
    still run in order and carry context into each other.
    """
    by_page: dict[int, list[dict]] = {}
    for seg in segments:
        if seg["translatable"]:
            by_page.setdefault(seg["page"], []).append(seg)
    batches: list[list[dict]] = []
    for page in sorted(by_page):
        batches.extend(batch_segments(by_page[page], max_chars))
    return batches


def assemble_markdown(segments: list[dict], field: str = "target", page_breaks: bool = True) -> str:
    out: list[str] = []
    page = None
    for seg in segments:
        if page_breaks and seg["page"] != page and page is not None:
            out.append(f"<!-- page {seg['page']} -->")
        page = seg["page"]
        if seg.get("kind") in FURNITURE:
            out.append(f"<!-- {seg['kind']}: {seg.get(field) or seg['source']} -->")
            continue
        if seg.get("kind") == "figure":
            text = seg.get(field) or seg["source"]
            legend = "\n".join(f"> {line}" for line in text.splitlines() if line.strip())
            out.append(f"![Figure {seg.get('figure', '')}](figures/{seg['image']})" + (f"\n\n{legend}" if legend else ""))
            continue
        out.append(seg.get(field) or seg["source"])
    return "\n\n".join(out) + "\n"

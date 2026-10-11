"""Scanned pages: text lines come from OCR (PP-OCRv5 through the layout server) instead of a text layer.

For each page without real text, the page is rendered at `SCAN_DPI` and sent to the layout server:
`ocr_lines` gives line boxes, recognised text and word boxes; `detect_layout` gives the figures.
Lines become `align.Line`s in PDF coordinates, with
- a font size estimated from the line height,
- the text colour (darkest pixels in the box) and the background colour (around the box), so the
  renderer can paint the source out with the paper colour and typeset the translation on top.
Lines inside figures are left out: text in pictures stays as printed (its translation is the
figure's legend), as for PDFs with a text layer.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import pymupdf

from .align import Line, norm

SCAN_DPI = 150
SIZE_PER_HEIGHT = 0.72  # font size ≈ 0.72 × the detected line height (boxes include some padding)
BOLD_INK = 1.3  # a line with 30% more ink coverage than the page's typical line reads as bold
_SCRIPTS = {"zh": "cjk", "ja": "cjk", "ko": "korean", "ru": "cyrillic", "uk": "cyrillic", "bg": "cyrillic", "sr": "cyrillic"}


def script_for(code: str | None) -> str:
    """PP-OCRv5 recognition model for a source language code (de → latin, zh-Hans → cjk…)."""
    return _SCRIPTS.get((code or "").split("-")[0].lower(), "latin")


def is_scan(page: pymupdf.Page) -> bool:
    return len(page.get_text().strip()) < 20 and bool(page.get_images())


def render(page: pymupdf.Page) -> pymupdf.Pixmap:
    return page.get_pixmap(dpi=SCAN_DPI, alpha=False)


@dataclass
class ScanPage:
    lines: list[Line] = field(default_factory=list)
    figures: list[pymupdf.Rect] = field(default_factory=list)  # obstacles text must not grow into


def _clamp(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, v)))


def _pixels(pix: pymupdf.Pixmap, box: tuple[float, float, float, float], nx: int, ny: int) -> list[tuple[int, int, int]]:
    x0, y0, x1, y1 = box
    out = []
    for i in range(nx):
        for j in range(ny):
            x = _clamp(x0 + (x1 - x0) * (i + 0.5) / nx, 0, pix.width - 1)
            y = _clamp(y0 + (y1 - y0) * (j + 0.5) / ny, 0, pix.height - 1)
            out.append(pix.pixel(x, y)[:3])
    return out


def _median(colors: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    return tuple(int(statistics.median(c[k] for c in colors)) for k in range(3))  # type: ignore[return-value]


def colors(pix: pymupdf.Pixmap, box: tuple[float, float, float, float]) -> tuple[tuple[int, int, int], tuple[int, int, int], float]:
    """(text colour, background colour, ink coverage) of a line box in the page image.

    Inside a text line most pixels are paper, so the background is the median of the brightest quarter
    (this also gets a shaded table header right, where the colour around the box would not).
    """
    inside = sorted(_pixels(pix, box, 64, 10), key=sum)
    bg = _median(inside[3 * len(inside) // 4 :])  # the brightest quarter: paper, without anti-aliased glyph edges
    ink = inside[: max(3, len(inside) // 12)]  # the darkest pixels are the glyphs
    text = _median(ink) if sum(bg) - sum(_median(ink)) > 120 else (0, 0, 0)
    cutoff = (sum(bg) + sum(text)) / 2
    coverage = sum(1 for p in inside if sum(p) < cutoff) / len(inside)
    return text, bg, coverage


def lines_from_ocr(result: dict, page: pymupdf.Page, pix: pymupdf.Pixmap, page_no: int,
                   figures_px: list[tuple[float, float, float, float]]) -> ScanPage:
    """OCR result (pixel coordinates of the image that was sent) → lines in PDF coordinates."""
    sx, sy = page.rect.width / result["width"], page.rect.height / result["height"]
    to_pdf = lambda b: pymupdf.Rect(b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy)  # noqa: E731
    figures = [to_pdf(f) for f in figures_px]
    scan = ScanPage(figures=figures)
    kept = []
    for ln in result["lines"]:
        rect = to_pdf(ln["box"])
        if any(f.contains(rect) or (f & rect).get_area() > rect.get_area() * 0.6 for f in figures):
            continue  # text inside a picture stays as printed
        kept.append((ln, rect, *colors(pix, tuple(ln["box"]))))
    # Bold text has more ink per line height: compare each line with the page's typical coverage.
    typical = statistics.median([c for *_, c in kept]) if kept else 0
    for ln, rect, text_rgb, bg_rgb, coverage in kept:
        scan.lines.append(
            Line(
                page=page_no,
                index=0,  # set when merged with the other pages
                rect=rect,
                text=ln["text"],
                size=round(rect.height * SIZE_PER_HEIGHT, 1),
                color=(text_rgb[0] << 16) | (text_rgb[1] << 8) | text_rgb[2],
                bold=bool(typical) and coverage > typical * BOLD_INK,
                italic=False,
                block=0,
                key=norm(ln["text"]),
                words=[(to_pdf(w["box"]), w["text"]) for w in ln.get("words") or []],
                fill=tuple(c / 255 for c in bg_rgb),
            )
        )
    return scan

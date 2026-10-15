"""Which regions of a page are really pictures.

PP-DocLayoutV3 sometimes labels a block of plain text as `image`, or a whole photographed page. A region taken
for a picture is outlined in red and the OCR is told not to transcribe it, so a mistake there loses text. Before
a region becomes a figure it must pass these checks, all without a model:
- size: not a speck, and not (nearly) the whole page;
- the same detection: the layout model didn't also find text there (a text twin, or text regions covering it);
- the PDF's own text layer (born-digital pages): there isn't a paragraph's worth of real text inside it.
Then the vision model looks at each remaining crop and says picture or text (read.py, prompts.FIGURE_CHECK).
"""

from __future__ import annotations

from dataclasses import dataclass

Box = tuple[float, float, float, float]  # left, top, right, bottom (pixels of the page image)

FIGURE_LABELS = frozenset({"image", "chart", "seal"})
# Layout labels that mean "printed text": a figure overlapping these is likely text taken for a picture.
TEXT_LABELS = frozenset({
    "text", "paragraph_title", "doc_title", "abstract", "content", "reference", "reference_content", "footnote",
    "vertical_text", "aside_text", "algorithm", "table", "figure_title",
})


@dataclass(frozen=True)
class Guard:
    min_side: float = 0.06  # of the page's width / height: smaller is a bullet, a rule, an icon
    min_side_seal: float = 0.03  # a small stamp still matters
    max_area: float = 0.85  # of the page: bigger is the page itself (a scan), not a picture on it
    twin_iou: float = 0.7  # a text region this similar to the figure box is the same block, read as text
    twin_margin: float = 0.05  # …if the text reading is at most this much less confident
    text_cover: float = 0.6  # confident text regions covering this much of the box: it's text
    text_min_score: float = 0.5  # weaker text readings don't count against a picture (the vision check decides)
    text_cover_chart: float = 0.8  # a chart's labels are text regions too, so a chart needs more
    layer_cover: float = 0.5  # PDF text blocks covering this much of the box…
    layer_chars: int = 60  # …holding at least this many characters…
    layer_chars_per_block: float = 20  # …in blocks this long on average (a chart's labels are short)


def area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: Box, b: Box) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def iou(a: Box, b: Box) -> float:
    inter = intersection(a, b)
    union = area(a) + area(b) - inter
    return inter / union if union else 0.0


def _covered(box: Box, others: list[Box]) -> float:
    """How much of `box` the other boxes cover (overlaps between them counted once, on a coarse grid)."""
    if not others or area(box) == 0:
        return 0.0
    n = 40
    w, h = (box[2] - box[0]) / n, (box[3] - box[1]) / n
    hit = 0
    for i in range(n):
        for j in range(n):
            x, y = box[0] + (i + 0.5) * w, box[1] + (j + 0.5) * h
            hit += any(o[0] <= x <= o[2] and o[1] <= y <= o[3] for o in others)
    return hit / (n * n)


def judge(
    box: Box,
    label: str,
    score: float,
    page_size: tuple[float, float],
    regions: list[dict],
    text_blocks: list[tuple[float, float, float, float, str]],
    from_layout: bool = True,
    guard: Guard = Guard(),
) -> str | None:
    """Why this region is not a picture ("size", "layout-text", "text-layer"), or None if it may be one.
    `regions`: everything the layout model found on the page; `text_blocks`: the PDF's text, in pixels (born-digital
    pages only — pass [] for a scan). PDF-embedded images (`from_layout=False`) are checked against the text layer only."""
    pw, ph = page_size
    if from_layout:
        side = guard.min_side_seal if label == "seal" else guard.min_side
        if (box[2] - box[0]) < side * pw or (box[3] - box[1]) < side * ph:
            return "size"
        if area(box) > guard.max_area * pw * ph:
            return "size"
        if label != "seal":
            texts = [r for r in regions if r.get("label") in TEXT_LABELS]
            for r in texts:
                if iou(box, tuple(r["box"])) >= guard.twin_iou and float(r.get("score", 0)) >= score - guard.twin_margin:
                    return "layout-text"
            cover = guard.text_cover_chart if label == "chart" else guard.text_cover
            sure = [tuple(r["box"]) for r in texts if float(r.get("score", 0)) >= guard.text_min_score]
            if _covered(box, sure) >= cover:
                return "layout-text"
    inside = [b for b in text_blocks if area(b[:4]) and intersection(box, b[:4]) >= 0.5 * area(b[:4])]
    if inside:
        chars = sum(len("".join(b[4].split())) for b in inside)
        if (_covered(box, [b[:4] for b in inside]) >= guard.layer_cover and chars >= guard.layer_chars
                and chars / len(inside) >= guard.layer_chars_per_block):
            return "text-layer"
    return None

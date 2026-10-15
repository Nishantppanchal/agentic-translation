"""Reading the source: vision OCR per page (with figures and the OCR check), and the source check pause."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from typing import Any

from google.adk import Context, Event
from google.adk.events import RequestInput
from google.adk.workflow import node
from google.genai import types
from rapidfuzz import fuzz

from ...config import get_settings
from ...document import source_check
from ...document import state as st
from ...document.pages import (
    Figure,
    Page,
    crop_png,
    load_pages,
    mark_figures,
    place_figure_marker,
    segments_from_pages,
)
from ...models import routing
from ...models.replies import (
    clean,
    parse_figure_reply,
    parse_ocr_check,
)
from ...ocr import layout
from ...ocr.figures import FIGURE_LABELS, Guard, judge
from ...ocr.guard import guard
from .. import prompts
from ..common import progress_state, reply_text, run_bounded, say, user_message
from ..workers import figure_reader, ocr_checker, ocr_reader

SOURCE_INTERRUPT = "source_check"


OCR_CACHE_VERSION = 4  # 4: figures checked (size, layout text, text layer, picture-or-text) before the reading


def _overlap(a: tuple, b: tuple) -> float:
    """Intersection over the smaller box."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / smaller


# Markdown syntax (not content): figure/header markers, heading hashes, bullets, table rules and pipes,
# emphasis. Numbers stay — "1." in a heading is text in both the transcription and the layer.
_MD_NOISE = re.compile(r"\[\[(?:FIGURE \d+|HEADER|FOOTER)\]\]|^\s*#+|^\s*[-*+]\s|:?-{3,}:?|[|*_`>]", re.M)


# A hyphen between letters, also across a line break: "USV-\nAnlage", "besei-\ntigen", "USV-Anlage" all
# compare equal (line-end hyphenation is ambiguous); minus signs and number ranges still count.
_WORD_HYPHEN = re.compile(r"(?<=[^\W\d_])-\s*(?=[^\W\d_])")


def layer_agreement(markdown: str, text_layer: str) -> float:
    """How closely a vision transcription matches the PDF's own text layer (0–100), ignoring markdown,
    line breaks, hyphenation at line ends, spacing and character variants (ligatures, full-width forms).
    A single misread word already costs a point or two, so only 100 means "the same text"; a messy
    layer (broken character maps, odd reading order, text inside images) never gets there."""

    def plain(s: str) -> str:
        s = _MD_NOISE.sub(" ", unicodedata.normalize("NFKC", s))
        return re.sub(r"\s+", "", _WORD_HYPHEN.sub("", s))

    a, b = plain(markdown), plain(text_layer)
    return fuzz.ratio(a, b) if a and b else 0.0


def _ocr_signature(page: Page, state=None) -> str:
    """What a cached page result depends on: the page itself, the reading models the document uses (and their
    reasoning level), the OCR settings and prompts."""
    s = get_settings()
    ocr, check = routing.resolve("ocr", state), routing.resolve("ocr_check", state)
    h = hashlib.sha1(page.image or b"")
    for part in (page.text_layer, f"{ocr.model_name}/{ocr.effort}", s.layout_model, f"{check.model_name}/{check.effort}",
                 s.ocr_check_enabled, s.ocr_check, s.figure_detection, s.figure_text, s.figure_check,
                 json.dumps(layout.thresholds(), sort_keys=True), _guard(), OCR_CACHE_VERSION,
                 prompts.VISION_OCR, prompts.VISION_OCR_TEXT_LAYER, prompts.VISION_OCR_FIGURES, prompts.OCR_CHECK,
                 prompts.FIGURE_CHECK):  # a better prompt reads the page again
        h.update(str(part).encode())
    return h.hexdigest()


async def _cached_ocr(ctx: Context, page: Page, sig: str) -> tuple[str, dict, dict[tuple[int, int], dict]] | None:
    part = await ctx.load_artifact(f"ocr-p{page.number}.json")
    if part is None or not part.text:
        return None
    try:
        data = json.loads(part.text)
    except ValueError:
        return None
    if data.get("sig") != sig:
        return None
    meta = {(page.number, int(n)): v for n, v in data["meta"].items()}
    return data["markdown"], {**data["report"], "cached": True}, meta


async def _ocr_page(ctx: Context, page: Page) -> tuple[str, dict, dict[tuple[int, int], dict]]:
    """Vision OCR + verification for one page → (markdown, report, figure metadata).
    Cached per page (an artifact), so retrying an interrupted document doesn't read pages again."""
    if page.image is None:  # plain text input: nothing to OCR
        report = {"page": page.number, "ok": True, "issues": [], "used_text_layer": False, "figures": 0}
        return page.text_layer, report, {}
    sig = _ocr_signature(page, ctx.state)
    if cached := await _cached_ocr(ctx, page, sig):
        return cached
    markdown, report, meta = await _read_page(ctx, page)
    data = {"sig": sig, "markdown": markdown, "report": report, "meta": {str(n): v for (_, n), v in meta.items()}}
    await ctx.save_artifact(f"ocr-p{page.number}.json", types.Part(text=json.dumps(data, ensure_ascii=False)))
    return markdown, report, meta


def _guard() -> Guard:
    return Guard(text_cover=get_settings().figure_text_cover)


def _image_size(png: bytes) -> tuple[int, int]:
    import pymupdf

    pix = pymupdf.Pixmap(png)
    return pix.width, pix.height


async def _vision_figures(page: Page) -> tuple[list[Figure], list[dict]]:
    """Picture candidates that pass the checks in ocr/figures.py → (figures, regions turned down as pictures).
    Candidates: the PDF's embedded images, plus the pictures, charts and seals PP-DocLayoutV3 finds (the layout
    server, if it is running) on scans and in vector drawings."""
    if get_settings().figure_detection == "off":
        return [], []
    guard_ = _guard()
    size = _image_size(page.image)
    text_blocks = page.text_blocks if page.has_text_layer else []
    figures: list[Figure] = []
    dropped: list[dict] = []
    for f in page.figures:  # an image embedded in a PDF: a picture unless the PDF's own text covers it
        if reason := judge(f.box, "image", 1.0, size, [], text_blocks, from_layout=False, guard=guard_):
            dropped.append({"label": "image", "reason": reason})
        else:
            figures.append(f)
    found = await layout.detect_layout(page.image) if layout.available() else None
    regions = (found or {}).get("regions") or []
    for r in regions:
        box = tuple(r["box"])
        if r["label"] not in FIGURE_LABELS or any(_overlap(box, f.box) > 0.5 for f in page.figures):
            continue
        if reason := judge(box, r["label"], float(r.get("score", 1.0)), size, regions, text_blocks, guard=guard_):
            dropped.append({"label": r["label"], "reason": reason})
            continue
        figures.append(Figure(box=box, png=crop_png(page.image, box), anchor=page.anchor_below(box), kind=r["label"],
                              source="layout"))
    figures.sort(key=lambda f: (round(f.box[1]), f.box[0]))
    return figures, dropped


async def _check_figures(ctx: Context, page: Page, figures: list[Figure]) -> tuple[list[Figure], list[str], list[dict]]:
    """The OCR model looks at each picture candidate: a picture keeps the text read in it as its legend; plain text
    is dropped as a figure (seals never are), so the page reading transcribes it like any other text.
    → (pictures, their legends, the regions read as text)."""
    settings = get_settings()
    if not figures or (settings.figure_check == "off" and not settings.figure_text):
        return figures, [""] * len(figures), []

    async def look(k: int, figure: Figure) -> tuple[str, str]:
        crop = types.Part.from_bytes(data=figure.png, mime_type="image/png")
        out = await ctx.run_node(figure_reader, node_input=user_message(crop, prompts.FIGURE_CHECK.format(label=figure.kind)),
                                 run_id=f"figcheck-p{page.number}-{k}")
        return parse_figure_reply(reply_text(out))

    replies: dict[int, tuple[str, str]] = {}
    async for i, res in run_bounded([lambda k=k, f=f: look(k, f) for k, f in enumerate(figures, start=1)],
                                    settings.max_concurrency):
        replies[i] = res
    kept, legends, as_text = [], [], []
    for i, figure in enumerate(figures):
        kind, text = replies[i]
        if settings.figure_check == "auto" and kind == "text" and figure.kind != "seal":
            as_text.append({"label": figure.kind, "reason": "vision"})
            continue
        kept.append(figure)
        legends.append(text if settings.figure_text else "")
    return kept, legends, as_text


async def _read_page(ctx: Context, page: Page) -> tuple[str, dict, dict[tuple[int, int], dict]]:
    """A vision LLM transcribes the whole page (any script), with the pictures outlined and numbered so it writes
    `[[FIGURE n]]` in their place; then the OCR check, whose corrections are applied only where safe."""
    report = _new_report(page)
    figures, dropped = await _vision_figures(page)
    figures, legends, as_text = await _check_figures(ctx, page, figures)
    sources = {f.source for f in figures}
    report.update(figures=len(figures), figure_source="+".join(x for x in ("pdf", "layout") if x in sources),
                  seals=sum(f.kind == "seal" for f in figures))
    if dropped or as_text:
        report["figures_as_text"] = dropped + as_text
    boxes = [f.box for f in figures]
    page_png = mark_figures(page.image, boxes) if figures else page.image
    image = types.Part.from_bytes(data=page_png, mime_type="image/png" if figures else page.image_mime)
    # The OCR leaves the text inside the red boxes out, so the text layer it is compared with does too.
    text_layer = page.text_layer_outside(boxes) if page.has_text_layer else ""
    hint = prompts.VISION_OCR_TEXT_LAYER.format(
        text_layer=text_layer.strip(), outside_figures=" (the text inside the red boxes is left out of it)" if figures else ""
    ) if text_layer.strip() else ""
    fig_hint = prompts.VISION_OCR_FIGURES.format(n=len(figures)) if figures else ""
    out = await ctx.run_node(ocr_reader, node_input=user_message(image, f"Transcribe page {page.number}.{fig_hint}{hint}"),
                             run_id=f"ocr-p{page.number}")
    markdown = clean(reply_text(out))
    markdown = await _check_page(ctx, page, markdown, image, prompts.OCR_CHECK_MARKED_FIGURES if figures else "",
                                 text_layer, report)
    for n, figure in enumerate(figures, start=1):
        markdown = place_figure_marker(markdown, n, figure.anchor)
    return markdown, report, await _save_figures(ctx, page, figures, legends)


def _new_report(page: Page) -> dict:
    return {"page": page.number, "ok": True, "issues": [], "used_text_layer": page.has_text_layer, "figures": 0}


async def _check_page(ctx: Context, page: Page, markdown: str, image: types.Part, figure_note: str, text_layer: str,
                      report: dict) -> str:
    """The OCR check: skipped when the reading and a clean text layer agree (two independent readings; the text
    layer here leaves out the text inside the figures, as the reading does); otherwise a vision LLM compares the
    reading with the image, and its corrections are applied only where safe (`ocr/guard.py`) — the rest are
    listed as possible misreadings."""
    settings = get_settings()
    agreement = layer_agreement(markdown, text_layer) if text_layer.strip() and not page.full_page_image else 0
    if settings.ocr_check == "auto" and agreement >= settings.ocr_check_agreement:
        report.update(checked="text layer", agreement=round(agreement, 1))
        return markdown
    if not settings.ocr_check_enabled or not markdown:
        return markdown
    check_prompt = prompts.OCR_CHECK.format(
        transcription=markdown,
        text_layer_hint=" (and the PDF's embedded text layer)" if text_layer.strip() else "",
        text_layer_block=f"\n\n<text_layer>\n{text_layer.strip()}\n</text_layer>" if text_layer.strip() else "",
        figure_note=figure_note,
    )
    verdict = await ctx.run_node(ocr_checker, node_input=user_message(image, check_prompt), run_id=f"ocrcheck-p{page.number}")
    _ok, _issues, corrected = parse_ocr_check(reply_text(verdict))
    if corrected:
        markdown, applied, held = guard(markdown, corrected, text_layer)
        if applied:
            report.update(ok=False, issues=report["issues"] + applied)
        if held:
            report["suggestions"] = held
    return markdown


async def _save_figures(ctx: Context, page: Page, figures: list[Figure], legends: list[str]) -> dict[tuple[int, int], dict]:
    meta: dict[tuple[int, int], dict] = {}
    for n, (figure, legend) in enumerate(zip(figures, legends), start=1):
        name = f"figure-p{page.number}-{n}.png"
        await ctx.save_artifact(name, types.Part.from_bytes(data=figure.png, mime_type="image/png"))
        meta[(page.number, n)] = {"image": name, "text": legend}
    return meta


@node(rerun_on_resume=True)
async def ocr(ctx: Context, node_input: Any):
    settings = get_settings()
    filename = ctx.state.get("doc:filename") or "document.pdf"
    artifact = await ctx.load_artifact(ctx.state.get("doc:source_artifact"))
    if artifact is None or artifact.inline_data is None:
        raise RuntimeError("Source document artifact is missing.")
    pages = await asyncio.to_thread(load_pages, artifact.inline_data.data, filename, settings.ocr_dpi)
    total = len(pages)
    needs_ocr = any(p.image is not None for p in pages)

    yield say(
        f"Reading {total} page{'s' if total != 1 else ''} with vision OCR"
        + (" + OCR check" if settings.ocr_check_enabled else "") if needs_ocr else "Reading text document",
        state={**progress_state("ocr", 0, total, "Running OCR…", "ocr"), "doc:pages": total},
    )

    results: dict[int, tuple[str, dict, dict]] = {}
    tasks = [lambda p=p: _ocr_page(ctx, p) for p in pages]
    async for i, res in run_bounded(tasks, settings.max_concurrency):
        results[i] = res
        _md, report, _meta = res
        if report.get("cached"):
            note = "reused from the earlier run"
        elif report.get("checked") == "text layer":
            note = "matches the PDF's text layer (no second check needed)"
        else:
            note = "verified" if report["ok"] else f"checker fixed {len(report['issues'])} issue(s)"
        if report.get("suggestions"):
            n = len(report["suggestions"])
            note += f"; {n} possible misreading{'s' if n != 1 else ''} to check (not changed)"
        if report["figures"]:
            note += f"; {report['figures']} figure{'s' if report['figures'] != 1 else ''} kept ({report['figure_source']})"
        if n := len(report.get("figures_as_text") or []):
            note += f"; {n} region{'s' if n != 1 else ''} taken for a picture read as text"
        yield say(f"OCR page {pages[i].number}: {note}", state=progress_state("ocr", len(results), total, f"OCR page {len(results)}/{total}"))

    page_md = [(pages[i].number, results[i][0]) for i in range(total)]
    figure_meta = {k: v for i in range(total) for k, v in results[i][2].items()}
    segments = segments_from_pages(page_md, figure_meta)
    if not segments:
        raise RuntimeError("OCR produced no text. Is the document blank or unreadable?")
    delta: dict[str, Any] = {st.seg_key(s["id"]): st.normalize(s) for s in segments}
    delta["doc:seg_ids"] = [s["id"] for s in segments]
    delta["doc:ocr_report"] = [results[i][1] for i in range(total)]
    # A layout-preserving PDF needs a PDF with a real text layer (scans: later milestone).
    fixed = sum(1 for i in range(total) if not results[i][1]["ok"])
    n_fig = len(figure_meta)
    yield say(
        f"OCR done: {len(segments)} segments"
        + (f" incl. {n_fig} figure{'s' if n_fig != 1 else ''}" if n_fig else "")
        + f"; checker corrected {fixed} of {total} page(s)",
        state=delta,
    )
    yield Event(output={"segments": len(segments)})


def source_format(filename: str) -> str:
    """pdf | image (read with OCR) · text (.txt / .md, read as it is) · docx | pptx | xlsx (extracted, office/)."""
    from ... import office

    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return office.detect(filename) or ("pdf" if ext == ".pdf" else "text" if ext in (".txt", ".md", ".markdown") else "image")


def _where_to_look(state) -> str:
    """What the reading itself says is worth a look, page by page — so someone who doesn't read the language knows
    where to start."""
    image_upload = not (state.get("doc:filename") or "").lower().endswith(".pdf")
    lines = []
    for r in state.get("doc:ocr_report") or []:
        notes = []
        if n := len(r.get("suggestions") or []):
            notes.append(f"{n} possible misreading{'s' if n != 1 else ''} the OCR check listed but didn't change")
        if not r.get("ok", True) and (n := len(r.get("issues") or [])):
            notes.append(f"the OCR check corrected {n} thing{'s' if n != 1 else ''}")
        if n := r.get("seals") or 0:
            notes.append(f"{'a seal or stamp' if n == 1 else f'{n} seals or stamps'} — its text is kept as a picture "
                         "legend, and text under it is easy to misread")
        if n := len(r.get("figures_as_text") or []):
            notes.append(f"{n} region{'s' if n != 1 else ''} the layout model took for a picture {'were' if n != 1 else 'was'} "
                         "read as text: check nothing is missing there")
        if not r.get("used_text_layer"):
            notes.append("read from the image" if image_upload else "a scan: no text layer to compare the reading with")
        if notes:
            lines.append(f"- **Page {r['page']}:** " + "; ".join(notes))
    if not lines:
        return "Nothing stands out: every page matches the PDF's own text, and the OCR check changed nothing."
    return "Where to look first:\n" + "\n".join(lines)


@node(rerun_on_resume=True)
async def check_source(ctx: Context, node_input: Any):
    """PDFs and images stop after reading, so the person can check the source against the page images and have
    the chat fix it (page fixes they accept or reject; `document/source_check.py`), then continue to translation."""
    if not source_check.needs_check(ctx.state) or ctx.state.get(source_check.CHECKED):
        yield Event(output={"checked": False})
        return
    if (ctx.resume_inputs or {}).get(SOURCE_INTERRUPT) is None:
        pages = len(source_check.pages(ctx.state))
        text = (f"I've read {pages} page{'s' if pages != 1 else ''}. Before I translate, check the source text next to the "
                "page images (**Source & notes → Page images & OCR**).\n\n" + _where_to_look(ctx.state) + "\n\n"
                "If something is wrong — two columns read across, a paragraph split in two, a stamp's text inside a "
                "sentence, a misread word — tell me here: I'll look at the page and propose a fix for it. Press "
                "**Continue to translation** when it's right.")
        yield say(text, kind="assistant",
                   state=progress_state("check", 0, 0, "Waiting for you to check the source", "awaiting_source_check"))
        yield RequestInput(interrupt_id=SOURCE_INTERRUPT, message="Check the source", payload={})
        return
    dropped = len(ctx.state.get(source_check.FIXES) or {})
    text = "Thanks — translating now" + (f" ({dropped} page fix{'es' if dropped != 1 else ''} not accepted, left out)" if dropped else "")
    yield say(text, state={source_check.CHECKED: True, source_check.FIXES: {},
                            **progress_state("analyse", 0, 0, "Reading the whole document…", "translating")})
    yield Event(output={"checked": True})

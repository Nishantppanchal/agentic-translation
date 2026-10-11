"""Ingest pipeline as an ADK Workflow graph.

    START → route_source ─┬─(ocr)────→ ocr ─────┬→ analyse → ask → translate → clarify → review ─┬─(refine)→ refine → review
                          └─(extract)→ extract ─┘                                               └─(done)──→ polish → finalize

* `route_source` PDFs, images and text go through OCR; Word, PowerPoint, Excel and XLIFF files are
              read directly (`extract`), keeping their formatting as inline codes.

* `ocr`       fans out per page: vision OCR agent, then OCR-checker agent (image vs text). The check is
              skipped where the transcription matches the PDF's own text layer on a page without
              pictures; each page's result is cached so a retry doesn't read it again.
* `analyse`   reads the WHOLE document before translating: writes the brief up front and fixes the key
              terms once (forward definitions included); terms whose options differ in meaning become
              questions, explained in plain English with English options and a recommendation.
* `ask`       human-in-the-loop: pauses ONCE for those questions; answers go into the glossary (and the
              project termbase), so the translation uses them from the first page.
* `translate` goes page by page IN ORDER: each call carries the brief, the previous text (source +
              translation) and the running termbase; the translator records new term choices and
              may still flag a term it can't resolve.
* `clarify`   pauses again only for such late terms; answers re-translate the affected segments.
* `review`    fans out per page: reviewer agent lists issues; routes to refine or done.
* `refine`    fans out per page with issues: refiner agent rewrites flagged segments.
* `polish`    one translation per repeated sentence and the termbase applied (`ops.consistency_fixes`).
* `finalize`  saves the reviewed version and marks the document ready.

Function nodes stream progress by yielding `Event(state=...)`; the LLM work is done
by single-turn `LlmAgent`s invoked through `ctx.run_node` with a concurrency cap.
Bulk data (page images, segments) never travels as node output — it lives in the
source artifact and in session state, so session events stay small.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from google.adk import Context, Event, Workflow
from google.adk.agents import LlmAgent
from google.adk.events import RequestInput
from google.adk.workflow import START, node
from google.genai import types
from rapidfuzz import fuzz

from .. import layout, projects, prompts, qa, structured
from .. import state as st
from ..config import Role, get_settings
from ..documents import (
    Figure,
    Page,
    box_from_percent,
    crop_png,
    image_size,
    load_pages,
    batch_segments,
    mark_figures,
    page_batches,
    place_figure_marker,
    segments_from_pages,
)
from ..formats import (
    clean,
    is_none_reply,
    parse_figure_boxes,
    parse_issues,
    parse_keeps,
    parse_ocr_check,
    parse_scores,
    parse_segments,
    parse_terms,
    tag_body,
)
from ..languages import lang_code
from ..llm import build_model
from ..filters import inline, office, xliff
from ..text import with_markup_of

log = logging.getLogger(__name__)
T = TypeVar("T")

PIPELINE_NAME = "ingest"
UI = "ui"  # custom_metadata key telling the API how to show a message event
CLARIFY_INTERRUPT = "clarify"
ASK_INTERRUPT = "ask"
OCR_CACHE_VERSION = 1


# --------------------------------------------------------------------------- #
# Agents (single-turn LLM workers)
# --------------------------------------------------------------------------- #


def _worker(name: str, role: Role, instruction: str, structured_output: bool = False) -> LlmAgent:
    return LlmAgent(
        name=name,
        model=build_model(role),
        instruction=instruction,
        generate_content_config=types.GenerateContentConfig(temperature=get_settings().temperature),
        # Adds a per-call JSON schema when the prompt asks for JSON (see structured.py).
        before_model_callback=structured.inject_schema if structured_output else None,
    )


ocr_extractor = _worker("ocr_extractor", "ocr", prompts.OCR_EXTRACT)
ocr_checker = _worker("ocr_checker", "ocr_check", "You verify OCR transcriptions against page images.")
figure_detector = _worker("figure_detector", "ocr", prompts.FIGURE_DETECT)
analyst = _worker("analyst", "translate", "You are a lead translator preparing a document for translation.", structured_output=True)
translator = _worker("translator", "translate", "You are a meticulous professional translator.", structured_output=True)
reviewer = _worker("reviewer", "review", "You are a strict senior translation reviewer.", structured_output=True)
refiner = _worker("refiner", "translate", "You are a professional translator revising your work.", structured_output=True)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _user(*parts: types.Part | str) -> types.Content:
    return types.Content(
        role="user", parts=[types.Part(text=p) if isinstance(p, str) else p for p in parts]
    )


def _text(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, types.Content):
        return "".join(p.text or "" for p in output.parts or [] if not p.thought)
    return output if isinstance(output, str) else json.dumps(output)


def _progress(stage: str, current: int, total: int, message: str, status: str | None = None) -> dict:
    delta: dict[str, Any] = {"doc:progress": {"stage": stage, "current": current, "total": total, "message": message}}
    if status:
        delta["doc:status"] = status
    return delta


def _say(text: str, kind: str = "activity", state: dict | None = None) -> Event:
    """A chat-visible message from the pipeline (kind: activity | assistant)."""
    return Event(
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        custom_metadata={UI: kind},
        state=state or {},
    )


async def _bounded(tasks: list[Callable[[], Awaitable[T]]], limit: int) -> AsyncIterator[tuple[int, T]]:
    """Run task factories with a concurrency limit, yielding (index, result) as each finishes."""
    sem = asyncio.Semaphore(max(1, limit))

    async def run(i: int, make: Callable[[], Awaitable[T]]) -> tuple[int, T]:
        async with sem:
            return i, await make()

    pending = [asyncio.create_task(run(i, t)) for i, t in enumerate(tasks)]
    try:
        for fut in asyncio.as_completed(pending):
            yield await fut
    finally:
        for p in pending:
            p.cancel()


def _langs(state) -> tuple[str, str]:
    source = state.get("doc:source_lang") or "auto-detect"
    if source.lower().startswith("auto"):
        source = state.get("doc:detected_lang") or "the source language (detect it)"
    return source, state.get("doc:target_lang") or "English"


def _pairs(segments: list[dict]) -> str:
    return "\n\n".join(
        f'<pair id="{s["id"]}">\nSOURCE:\n{s["source"]}\n\nTRANSLATION:\n{s.get("target") or ""}\n</pair>'
        for s in segments
    )


async def _save_version(ctx: Context, note: str, changed: list[str], snap: dict[str, str] | None = None) -> dict:
    """Snapshot the translation as a new artifact version; returns the state delta to apply."""
    snap = snap if snap is not None else st.snapshot(ctx.state)
    adk_version = await ctx.save_artifact(st.TRANSLATION_ARTIFACT, types.Part(text=json.dumps(snap, ensure_ascii=False)))
    versions = list(ctx.state.get("doc:versions") or [])
    entry = st.new_version_entry(ctx.state, len(versions) + 1, note, changed)[-1]
    entry["artifact_version"] = adk_version
    return {"doc:versions": [*versions, entry], "doc:dirty": []}


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #


async def _detect_figures(ctx: Context, page: Page) -> list[Figure]:
    """Scanned page: ask the vision model where the figures are (boxes in % of the page)."""
    image = types.Part.from_bytes(data=page.image, mime_type=page.image_mime)
    out = _text(await ctx.run_node(figure_detector, node_input=_user(image, "Locate the figures."), run_id=f"figures-p{page.number}"))
    width, height = image_size(page.image)
    figures = []
    for values, _desc in parse_figure_boxes(out):
        box = box_from_percent(values, width, height, pad=0.025)
        if box and not any(_overlap(box, f.box) > 0.5 for f in figures):
            figures.append(Figure(box=box, png=crop_png(page.image, box)))
    return sorted(figures, key=lambda f: (round(f.box[1]), f.box[0]))


def _overlap(a: tuple, b: tuple) -> float:
    """Intersection over the smaller box."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / smaller


async def _find_figures(ctx: Context, page: Page) -> tuple[list[Figure], str]:
    """Figures on a page → (figures in reading order, which detectors contributed).

    Exact PDF image boxes first; PP-DocLayout (MCP tool) adds what they miss — vector charts,
    figures on scans; vision-LLM boxes are the fallback for scans when no layout server is available.
    """
    mode = get_settings().figure_detection
    if mode == "off":
        return [], ""
    figures = list(page.figures)
    sources = ["pdf"] if figures else []

    def add(boxes: list[tuple[float, float, float, float]]) -> bool:
        added = False
        for box in boxes:
            if not any(_overlap(box, f.box) > 0.5 for f in figures):
                figures.append(Figure(box=box, png=crop_png(page.image, box), anchor=page.anchor_below(box)))
                added = True
        return added

    layout_done = False
    if mode in ("auto", "layout") and layout.available():
        boxes = await layout.figure_boxes(page.image, ctx)
        if boxes is not None:
            layout_done = True
            if add(boxes):
                sources.append("layout")
    if not layout_done and page.is_scan and mode in ("auto", "vision"):
        if add([f.box for f in await _detect_figures(ctx, page)]):
            sources.append("vision")
    figures.sort(key=lambda f: (round(f.box[1]), f.box[0]))
    return figures, "+".join(sources)


async def _figure_text(ctx: Context, page: Page, n: int, figure: Figure) -> str:
    crop = types.Part.from_bytes(data=figure.png, mime_type="image/png")
    out = _text(await ctx.run_node(ocr_extractor, node_input=_user(crop, prompts.FIGURE_TEXT), run_id=f"figtext-p{page.number}-{n}"))
    return "" if is_none_reply(out) else clean(out)


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


def _ocr_signature(page: Page) -> str:
    """What a cached page result depends on: the page itself and the OCR settings."""
    s = get_settings()
    h = hashlib.sha1(page.image or b"")
    for part in (page.text_layer, s.role_model("ocr")[0], s.role_model("ocr_check")[0], s.ocr_check_enabled, s.ocr_check,
                 s.figure_detection, s.figure_text, OCR_CACHE_VERSION):
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
    """Figures + vision OCR + verification for one page → (markdown, report, figure metadata).
    Cached per page (an artifact), so retrying an interrupted document doesn't read pages again."""
    if page.image is None:  # plain text input: nothing to OCR
        report = {"page": page.number, "ok": True, "issues": [], "used_text_layer": False, "figures": 0}
        return page.text_layer, report, {}
    sig = _ocr_signature(page)
    if cached := await _cached_ocr(ctx, page, sig):
        return cached
    markdown, report, meta = await _read_page(ctx, page)
    data = {"sig": sig, "markdown": markdown, "report": report, "meta": {str(n): v for (_, n), v in meta.items()}}
    await ctx.save_artifact(f"ocr-p{page.number}.json", types.Part(text=json.dumps(data, ensure_ascii=False)))
    return markdown, report, meta


async def _read_page(ctx: Context, page: Page) -> tuple[str, dict, dict[tuple[int, int], dict]]:
    settings = get_settings()
    report = {"page": page.number, "ok": True, "issues": [], "used_text_layer": page.has_text_layer, "figures": 0}

    figures, figure_source = await _find_figures(ctx, page)
    report.update(figures=len(figures), figure_source=figure_source)

    # Set-of-marks: outline + number the figures so OCR can place [[FIGURE n]] in reading order.
    page_png = mark_figures(page.image, [f.box for f in figures]) if figures else page.image
    image = types.Part.from_bytes(data=page_png, mime_type="image/png" if figures else page.image_mime)
    hint = prompts.OCR_EXTRACT_TEXT_LAYER.format(text_layer=page.text_layer.strip()) if page.has_text_layer else ""
    fig_hint = prompts.OCR_FIGURES.format(n=len(figures)) if figures else ""
    out = await ctx.run_node(
        ocr_extractor,
        node_input=_user(image, f"Transcribe page {page.number}.{fig_hint}{hint}"),
        run_id=f"ocr-p{page.number}",
    )
    markdown = clean(_text(out))

    # Two independent readings that agree need no third look: the transcription and a clean text layer
    # on a page without pictures. Anything else (scans, figures, a messy layer) is checked as before.
    agreement = layer_agreement(markdown, page.text_layer) if page.has_text_layer and not figures and not page.full_page_image else 0
    if settings.ocr_check == "auto" and agreement >= settings.ocr_check_agreement:
        report.update(checked="text layer", agreement=round(agreement, 1))
    elif settings.ocr_check_enabled and markdown:
        check_prompt = prompts.OCR_CHECK.format(
            transcription=markdown,
            text_layer_hint=" (and the PDF's embedded text layer)" if page.has_text_layer else "",
            text_layer_block=f"\n\n<text_layer>\n{page.text_layer.strip()}\n</text_layer>" if page.has_text_layer else "",
            figure_note=prompts.OCR_CHECK_FIGURES if figures else "",
        )
        verdict = await ctx.run_node(ocr_checker, node_input=_user(image, check_prompt), run_id=f"ocrcheck-p{page.number}")
        ok, issues, corrected = parse_ocr_check(_text(verdict))
        if corrected:
            markdown = corrected
            report.update(ok=False, issues=issues or ["Transcription corrected"])

    meta: dict[tuple[int, int], dict] = {}
    for n, figure in enumerate(figures, start=1):
        markdown = place_figure_marker(markdown, n, figure.anchor)
        name = f"figure-p{page.number}-{n}.png"
        await ctx.save_artifact(name, types.Part.from_bytes(data=figure.png, mime_type="image/png"))
        text = await _figure_text(ctx, page, n, figure) if settings.figure_text else ""
        meta[(page.number, n)] = {"image": name, "text": text}
    return markdown, report, meta


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

    yield _say(
        f"Reading {total} page{'s' if total != 1 else ''} with vision OCR"
        + (" + OCR verification" if settings.ocr_check_enabled else "") if needs_ocr else "Reading text document",
        state={**_progress("ocr", 0, total, "Running OCR…", "ocr"), "doc:pages": total},
    )

    results: dict[int, tuple[str, dict, dict]] = {}
    tasks = [lambda p=p: _ocr_page(ctx, p) for p in pages]
    async for i, res in _bounded(tasks, settings.max_concurrency):
        results[i] = res
        _md, report, _meta = res
        if report.get("cached"):
            note = "reused from the earlier run"
        elif report.get("checked") == "text layer":
            note = "matches the PDF's text layer (no second check needed)"
        else:
            note = "verified" if report["ok"] else f"checker fixed {len(report['issues'])} issue(s)"
        if report["figures"]:
            note += f"; {report['figures']} figure{'s' if report['figures'] != 1 else ''} kept ({report['figure_source']})"
        yield _say(f"OCR page {pages[i].number}: {note}", state=_progress("ocr", len(results), total, f"OCR page {len(results)}/{total}"))

    page_md = [(pages[i].number, results[i][0]) for i in range(total)]
    figure_meta = {k: v for i in range(total) for k, v in results[i][2].items()}
    segments = segments_from_pages(page_md, figure_meta)
    if not segments:
        raise RuntimeError("OCR produced no text. Is the document blank or unreadable?")
    delta: dict[str, Any] = {st.seg_key(s["id"]): st.normalize(s) for s in segments}
    delta["doc:seg_ids"] = [s["id"] for s in segments]
    delta["doc:ocr_report"] = [results[i][1] for i in range(total)]
    # A layout-preserving PDF needs a PDF with a real text layer (scans: later milestone).
    delta["doc:layout_capable"] = filename.lower().endswith(".pdf") and any(not p.is_scan for p in pages)
    fixed = sum(1 for i in range(total) if not results[i][1]["ok"])
    n_fig = len(figure_meta)
    yield _say(
        f"OCR done: {len(segments)} segments"
        + (f" incl. {n_fig} figure{'s' if n_fig != 1 else ''}" if n_fig else "")
        + f"; checker corrected {fixed} of {total} page(s)",
        state=delta,
    )
    yield Event(output={"segments": len(segments)})


DIRECT_FORMATS = {**office.FORMATS, ".xlf": "xliff", ".xliff": "xliff"}


def source_format(filename: str) -> str:
    """docx | pptx | xlsx | xliff (read directly) · pdf | image | text (OCR / plain text)."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return DIRECT_FORMATS.get(ext) or ("pdf" if ext == ".pdf" else "text" if ext in (".txt", ".md", ".markdown") else "image")


@node(rerun_on_resume=True)
async def route_source(ctx: Context, node_input: Any):
    fmt = source_format(ctx.state.get("doc:filename") or "")
    yield Event(state={"doc:format": fmt}, output={"format": fmt}, route="extract" if fmt in DIRECT_FORMATS.values() else "ocr")


_FORMAT_NAME = {"docx": "Word document", "pptx": "PowerPoint presentation", "xlsx": "Excel workbook", "xliff": "XLIFF file"}


@node(rerun_on_resume=True)
async def extract(ctx: Context, node_input: Any):
    """Office and XLIFF files: read the text straight from the file (no OCR), formatting as inline codes."""
    fmt = ctx.state.get("doc:format") or source_format(ctx.state.get("doc:filename") or "")
    artifact = await ctx.load_artifact(ctx.state.get("doc:source_artifact"))
    if artifact is None or artifact.inline_data is None:
        raise RuntimeError("Source document artifact is missing.")
    yield Event(state=_progress("extract", 0, 1, f"Reading the {_FORMAT_NAME[fmt]}…", "ocr"))
    data = artifact.inline_data.data
    if fmt == "xliff":
        segments, info = await asyncio.to_thread(xliff.extract, data)
    else:
        segments, info = await asyncio.to_thread(office.extract, data, fmt)
    if not segments:
        raise RuntimeError(f"No text found in this {_FORMAT_NAME[fmt]}.")
    delta: dict[str, Any] = {st.seg_key(s["id"]): st.normalize(s) for s in segments}
    delta.update({"doc:seg_ids": [s["id"] for s in segments], "doc:pages": info["pages"], "doc:ocr_report": [],
                  "doc:layout_capable": False, "doc:tracked_changes": info.get("tracked_changes", 0),
                  **_progress("extract", 1, 1, "Read")})
    unit = info["unit"]
    msg = f"Read the {_FORMAT_NAME[fmt]}: {len(segments)} segments in {info['pages']} {unit}{'s' if info['pages'] != 1 else ''}"
    if info.get("with_codes"):
        msg += f"; {info['with_codes']} keep formatting, links or fields as inline codes"
    if info.get("pretranslated"):
        msg += f"; {info['pretranslated']} already translated (kept)"
    if info.get("in_formulas"):
        n = info["in_formulas"]
        msg += (f"; {n} cell text{'s are' if n != 1 else ' is'} also used inside formulas, which the translated file "
                "updates to the translation so their results stay right")
    yield _say(msg, state=delta)
    if info.get("tracked_changes"):
        n = info["tracked_changes"]
        yield _say(
            f"**Note:** this Word file contains {n} tracked change{'s' if n != 1 else ''}. The text is translated as if "
            "all changes were accepted, and the translated file has no tracked changes. If the client still needs to "
            "review those changes, ask them for a clean file.",
            kind="assistant",
        )
    if fmt == "xliff" and info.get("tgt"):
        _, target_lang = _langs(ctx.state)
        if lang_code(target_lang).split("-")[0] != info["tgt"].split("-")[0].lower():
            yield _say(f"**Note:** the XLIFF file's target language is {info['tgt']}, but this document is set to {target_lang}.", kind="assistant")
    yield Event(output={"segments": len(segments)})


def _parse_analysis(text: str) -> tuple[str | None, str | None, list[dict]]:
    """An analyst reply → (source language, brief, key terms). JSON first, tags as fallback."""
    obj = structured.parse_json(text)
    if obj is not None and ("terms" in obj or "brief" in obj):
        lang, brief = str(obj.get("source_language") or "").strip(), str(obj.get("brief") or "").strip()
        return lang or None, brief or None, structured.terms_from(obj, "terms")
    return tag_body(text, "source_lang"), tag_body(text, "brief"), parse_terms(text)


@node(rerun_on_resume=True)
async def analyse(ctx: Context, node_input: Any):
    """Read the whole document before translating: the brief up front, key terms fixed once (definitions
    found anywhere in the document count), and the terms whose options differ in meaning turned into
    questions for `ask`. Optional: if the analysis fails, translation goes ahead page by page as before."""
    settings = get_settings()
    segments = st.get_segments(ctx.state)
    todo = [s for s in segments if s["translatable"] and not s.get("target")]
    if not settings.analysis_enabled or not todo:
        yield Event(output={"terms": 0})
        return
    chunks = batch_segments(todo, settings.analysis_chunk_chars)
    source_lang, target_lang = _langs(ctx.state)
    yield _say(
        "Reading the whole document first, to fix key terms and find what to ask you",
        state=_progress("analyse", 0, len(chunks), "Reading the whole document…", "translating"),
    )
    # Approved terms are settled; proposed ones (accepted recommendations) may be asked about again.
    decided = {t["source"].casefold() for t in qa.terms_for(ctx.state, [s["source"] for s in todo]) if t.get("status") != "proposed"}
    brief, detected = ctx.state.get("doc:brief") or "", None
    found: dict[str, dict] = {}
    fmt = prompts.ANALYSE_FORMAT_JSON if structured.enabled("translate") else prompts.ANALYSE_FORMAT_TAGS
    for i, chunk in enumerate(chunks):
        prompt = prompts.ANALYSE.format(
            source_lang=source_lang,
            target_lang=target_lang,
            max_terms=settings.analysis_max_terms,
            max_questions=settings.max_questions,
            term_fields=prompts.TERM_FIELDS.format(source_lang=source_lang),
            instructions=projects.instructions_for(ctx.state),
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in chunk]),
            brief=brief or "(start of document)",
            scope=_scope(chunk, i + 1 if len(chunks) > 1 else None),
            segments="\n\n".join(f'<seg id="{s["id"]}">\n{s["source"]}\n</seg>' for s in chunk),
            output_format=fmt,
        )
        try:
            out = _text(await ctx.run_node(analyst, node_input=_user(prompt), run_id=f"analyse-{i}"))
        except Exception as exc:  # the analysis only helps; never block the translation on it
            log.warning("analysis of part %d failed: %s", i + 1, exc)
            continue
        lang, new_brief, terms = _parse_analysis(out)
        detected, brief = detected or lang, (new_brief or brief)[:1500]
        for term in terms:
            key = term["term"].casefold()
            if key in decided or key in found or not qa.in_source(term["term"], todo):
                continue  # already in the glossary/termbase, a duplicate, or not actually in the text
            term["segment_ids"] = [s["id"] for s in todo if s["id"] in _segments_mentioning(todo, term["term"])]
            found[key] = term
        yield Event(state=_progress("analyse", i + 1, len(chunks), f"Read part {i + 1} of {len(chunks)}"))

    asks = [t for t in found.values() if t.get("ambiguous")][: settings.max_questions]
    asked = {t["term"].casefold() for t in asks}
    clear = {t["term"]: t["guess"] for t in found.values() if t["term"].casefold() not in asked and t["guess"]}
    delta: dict[str, Any] = {
        "doc:key_terms": [
            {"term": t["term"], "target": t["guess"], "meaning": t.get("meaning", ""), "asked": t["term"].casefold() in asked}
            for t in found.values()
        ],
        "doc:termbase": st.merge_termbase(ctx.state, dict(ctx.state.get("doc:termbase") or {}), clear),
    }
    if brief:
        delta["doc:brief"] = brief
    if detected and (ctx.state.get("doc:source_lang") or "auto").lower().startswith("auto"):
        delta["doc:detected_lang"] = detected.strip()
    if asks:
        delta["doc:questions"] = st.add_questions(ctx.state, asks, origin="analysis")
    msg = f"Read the document: {len(found)} key term{'s' if len(found) != 1 else ''} fixed for the whole translation"
    if asks:
        msg += f"; {len(asks)} need{'s' if len(asks) == 1 else ''} your decision before I translate"
    yield _say(msg, state=delta)
    yield Event(output={"terms": len(found), "questions": len(asks)})


def _record_answers(state, open_qs: list[dict], answers: dict) -> tuple[list[dict], dict, int, dict[str, str]]:
    """A person's answers → (all questions, glossary, number answered, guesses kept for skipped ones).

    An answer with an English term becomes a glossary entry for this document and a project term — approved
    if the person chose it, proposed if they just accepted the recommendation; a note alone explains the
    meaning; a skipped question keeps the agent's recommendation as an unverified choice."""
    questions = [dict(q) for q in state.get("doc:questions") or []]
    by_id = {q["id"]: q for q in questions}
    glossary = dict(state.get("doc:glossary") or {})
    pid = projects.project_id(state)
    answered, kept = 0, {}
    for q in open_qs:
        q = by_id[q["id"]]
        answer = st.answer_of(answers.get(q["id"]))
        if answer:
            q.update(status="resolved", answer=answer["note"] or answer["target"], answer_target=answer["target"],
                     answer_recommended=answer["recommended"])
            glossary[q["term"]] = {"target": answer["target"], "note": answer["note"]}
            if pid:  # the decision helps later documents: approved if the person chose it, else only proposed
                note = answer["note"] or q.get("meaning", "")
                projects.get_store().upsert_term(pid, q["term"], answer["target"], note, status=st.term_status(answer))
            answered += 1
        else:
            q["status"] = "dismissed"
            if q.get("guess"):
                kept[q["term"]] = q["guess"]
    return questions, glossary, answered, kept


async def _pause_for(interrupt: str, open_qs: list[dict], text: str):
    """Ask once (the chat shows the question cards) and stop until the person answers."""
    yield _say(text, kind="assistant", state=_progress("clarify", 0, 0, "Waiting for your answers", "awaiting_answers"))
    yield RequestInput(interrupt_id=interrupt, message="Decide terms", payload={"question_ids": [q["id"] for q in open_qs]})


@node(rerun_on_resume=True)
async def ask(ctx: Context, node_input: Any):
    """The analysis's questions, before translating. Answers go into the glossary, so the translation uses
    them from the first page and nothing needs re-translating."""
    open_qs = [q for q in st.open_questions(ctx.state) if q.get("origin") == "analysis"]
    if not open_qs:
        yield Event(output={"answered": 0})
        return
    answers = (ctx.resume_inputs or {}).get(ASK_INTERRUPT)
    if answers is None:
        n = len(open_qs)
        text = (f"Before I translate, please decide {n} term{'s' if n != 1 else ''}. Each card explains the term in plain "
                "English and preselects my recommendation, so **Accept all recommendations** is fine if you're unsure.")
        async for item in _pause_for(ASK_INTERRUPT, open_qs, text):
            yield item
        return
    questions, glossary, answered, kept = _record_answers(ctx.state, open_qs, answers if isinstance(answers, dict) else {})
    termbase = st.without_terms(st.merge_termbase({"doc:glossary": glossary}, dict(ctx.state.get("doc:termbase") or {}), kept),
                                set(glossary))
    msg = (f"Thanks! {answered} term{'s' if answered != 1 else ''} decided; translating with "
           f"{'it' if answered == 1 else 'them'}" if answered else "Using my recommendations")
    yield _say(msg, state={"doc:questions": questions, "doc:glossary": glossary, "doc:termbase": termbase,
                           **_progress("translate", 0, 0, "Translating…", "translating")})
    yield Event(output={"answered": answered})


def _carried_context(segments: list[dict], before_id: str, translations: dict[str, str], max_chars: int) -> str:
    """Source + translation of the text just before `before_id`, newest last, within a char budget."""
    ids = [s["id"] for s in segments]
    idx = ids.index(before_id) if before_id in ids else 0
    parts: list[str] = []
    used = 0
    for seg in reversed(segments[:idx]):
        target = translations.get(seg["id"])
        if not seg["translatable"] or not target:
            continue
        block = f"[{seg['id']}] SOURCE: {seg['source']}\nTRANSLATION: {target}"
        if parts and used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(reversed(parts)) or "(start of document)"


def _page_context(segments: list[dict], batch: list[dict], max_chars: int) -> str:
    """For re-translating a few segments: the rest of their page(s) as already translated."""
    pages = {s["page"] for s in batch}
    skip = {s["id"] for s in batch}
    blocks = [
        f"[{s['id']}] SOURCE: {s['source']}\nTRANSLATION: {s.get('target') or ''}"
        for s in segments
        if s["page"] in pages and s["id"] not in skip and s["translatable"] and s.get("target")
    ]
    text = "\n\n".join(blocks)
    return text[-max_chars:] if text else "(no other text on this page)"


def _scope(batch: list[dict], part: int | None = None) -> str:
    pages = sorted({s["page"] for s in batch})
    label = f"page {pages[0]}" if len(pages) == 1 else f"pages {pages[0]}–{pages[-1]}"
    return f"{label}, part {part}" if part else label


@dataclass
class BatchResult:
    translated: dict[str, str]  # segment id → translation
    terms: list[dict]  # flagged uncertain terms
    keeps: dict[str, str]  # terminology choices to carry forward
    detected: str | None  # detected source language
    brief: str | None  # updated document brief
    merged: set[str]  # ids that still look merged with a neighbour after the retry


def _parse_translation(text: str) -> BatchResult:
    """A translator reply: structured JSON when available, else the tag format."""
    obj = structured.parse_json(text)
    if obj is not None and "segments" in obj:
        brief = str(obj.get("brief") or "").strip()
        return BatchResult(
            translated=structured.segments_from(obj),
            terms=structured.terms_from(obj),
            keeps=structured.terminology_from(obj),
            detected=str(obj.get("source_language") or "").strip() or None,
            brief=brief[:1200] or None,
            merged=set(),
        )
    return BatchResult(
        translated=parse_segments(text),
        terms=parse_terms(text),
        keeps=parse_keeps(text),
        detected=tag_body(text, "source_lang"),
        brief=(tag_body(text, "brief") or "").strip()[:1200] or None,
        merged=set(),
    )


def _parse_revision(text: str) -> dict[str, str]:
    obj = structured.parse_json(text)
    return structured.segments_from(obj) if obj is not None and "segments" in obj else parse_segments(text)


def _parse_review(text: str) -> tuple[list[dict], list[dict], dict[str, int]]:
    """→ (issues, uncertain terms, scores per segment). Missing parts are simply empty."""
    obj = structured.parse_json(text)
    if obj is not None and ("issues" in obj or "uncertain_terms" in obj or "scores" in obj):
        return structured.issues_from(obj), structured.terms_from(obj), structured.scores_from(obj)
    return parse_issues(text), parse_terms(text), parse_scores(text)


def is_major(issue: dict) -> bool:
    return issue["severity"] in ("major", "critical")


def issues_to_fix(issues: list[dict], segments: list[dict], round_no: int) -> list[dict]:
    """What the refiner gets: round 1 everything raised, later rounds only major issues. A 100% TM match is
    a person's approved wording for the same sentence: it is only changed for a major issue, never for style."""
    tm_exact = {s["id"] for s in segments if s.get("origin") == "tm_exact"}
    return [x for x in issues if (round_no == 1 or is_major(x)) and (x["segment_id"] not in tm_exact or is_major(x))]


async def _translate_batch(
    ctx: Context,
    run_id: str,
    batch: list[dict],
    *,
    source_lang: str,
    target_lang: str,
    glossary: str,
    termbase: str,
    context: str,
    scope: str,
    brief: str = "",
    detect: bool = False,
    instructions: str = "(none)",
    tm: str = "(none)",
) -> BatchResult:
    """One translator call for a page (+ targeted retries for dropped and merged segments)."""
    max_terms = get_settings().max_questions_per_batch
    if structured.enabled("translate"):
        output_format = prompts.TRANSLATE_FORMAT_JSON
    else:
        output_format = prompts.TRANSLATE_FORMAT_TAGS + (prompts.TRANSLATE_FORMAT_TAGS_DETECT if detect else "")

    def build(segs: list[dict], extra: str = "") -> str:
        return prompts.TRANSLATE.format(
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=glossary,
            termbase=termbase,
            brief=brief or "(start of document — no brief yet)",
            instructions=instructions,
            tm=tm,
            max_terms=max_terms,
            context=context,
            scope=scope,
            segments="\n\n".join(f'<seg id="{s["id"]}">\n{s["source"]}\n</seg>' for s in segs),
            inline_rules=_inline_rules(segs),
            output_format=output_format,
        ) + extra

    async def call(segs: list[dict], suffix: str, extra: str = "") -> BatchResult:
        out = _text(await ctx.run_node(translator, node_input=_user(build(segs, extra)), run_id=f"{run_id}{suffix}"))
        return _with_clean_codes(_parse_translation(out), segs)

    result = await call(batch, "")
    translated = dict(result.translated)

    missing = [s for s in batch if not translated.get(s["id"])]
    if missing:  # one retry with just the segments the model dropped
        retry = await call(missing, "-retry")
        translated.update({k: v for k, v in retry.translated.items() if v})
        result.terms += retry.terms

    merged = qa.suspect_merges(batch, translated)
    if merged:  # one retry for segments whose text looks shifted between neighbours
        retry = await call([s for s in batch if s["id"] in merged], "-split", prompts.TRANSLATE_SEPARATELY)
        candidate = {**translated, **{k: v for k, v in retry.translated.items() if k in merged and v}}
        still = qa.suspect_merges(batch, candidate)
        if len(still) < len(merged):
            translated, merged = candidate, still

    result.translated, result.merged = translated, merged
    result.terms = result.terms[:max_terms]
    result.detected = result.detected if detect else None
    return result


def _inline_rules(segments: list[dict]) -> str:
    return prompts.INLINE_RULES if any(inline.has_codes(s["source"]) for s in segments) else ""


def _with_clean_codes(result: BatchResult, segments: list[dict]) -> BatchResult:
    """Models sometimes escape or respell code tags: canonicalise them (validation happens in QA)."""
    coded = {s["id"] for s in segments if inline.has_codes(s["source"])}
    result.translated = {k: inline.normalize(v) if k in coded and v else v for k, v in result.translated.items()}
    return result


def _tm_pass(state, segments: list[dict]) -> tuple[dict[str, dict], dict[str, dict], dict[str, int]]:
    """→ (state delta for reused segments, fuzzy refs by segment id, stats)."""
    stats = {"context": 0, "exact": 0, "fuzzy": 0, "words": 0}
    pid = projects.project_id(state)
    if not pid:
        return {}, {}, stats
    store = projects.get_store()
    auto_confirm = (store.project(pid) or {}).get("auto_confirm_context", True)
    delta: dict[str, dict] = {}
    refs: dict[str, dict] = {}
    prev = ""
    for seg in segments:
        if not seg["translatable"]:
            continue
        if not st.is_frozen(seg) and not seg.get("target"):
            best = next(iter(store.lookup(pid, seg["source"], prev, limit=1)), None)
            if best and best["score"] >= 100 and inline.validate(seg["source"], best["target"]):
                best = {**best, "score": 99}  # same words, but the formatting codes differ: adapt it
            if best and best["score"] >= 100:
                # A person confirmed this sentence in this context before: 101% starts confirmed (project
                # setting, on by default as in CAT tools); 100% still wants a look.
                target = with_markup_of(seg["source"], best["target"])  # imported TMX units are plain text
                confirmed = best["score"] > 100 and auto_confirm
                new = st.apply_target(seg, target, origin="tm_exact", status="confirmed" if confirmed else "draft")
                new["match"] = best["score"]
                delta[st.seg_key(seg["id"])] = new
                stats["context" if best["score"] > 100 else "exact"] += 1
                stats["words"] += len(seg["source"].split())
            elif best:
                refs[seg["id"]] = best
                stats["fuzzy"] += 1
        prev = seg["source"]
    return delta, refs, stats


@node(rerun_on_resume=True)
async def translate(ctx: Context, node_input: Any):
    """Translate page by page, in order, carrying the previous text and the termbase forward."""
    settings = get_settings()
    segments = st.get_segments(ctx.state)
    # Segments that already have a translation (an XLIFF file's existing targets) are kept.
    batches = page_batches([s for s in segments if not s.get("target")], settings.page_max_chars)
    total = len(batches)
    source_lang, target_lang = _langs(ctx.state)
    detect = source_lang.startswith("the source language")
    n_pages = len({s["page"] for b in batches for s in b})
    yield _say(
        f"Translating {sum(len(b) for b in batches)} segments into {target_lang}, page by page ({n_pages} page{'s' if n_pages != 1 else ''})",
        state=_progress("translate", 0, total, "Translating…", "translating"),
    )

    translations = {s["id"]: s["target"] for s in segments if s.get("target")}  # non-translatable = copied
    snap = {s["id"]: s.get("target") or "" for s in segments}
    termbase: dict[str, str] = dict(ctx.state.get("doc:termbase") or {})
    instructions = projects.instructions_for(ctx.state)
    brief = ctx.state.get("doc:brief") or ""

    # Translation memory first: 100/101% matches are reused as-is (no model call); fuzzy matches
    # become references the translator adapts.
    tm_delta, tm_refs, tm_stats = _tm_pass(ctx.state, segments)
    if tm_delta or tm_refs:
        for key, seg in tm_delta.items():
            translations[seg["id"]] = snap[seg["id"]] = seg["target"]
        reused = tm_stats["context"] + tm_stats["exact"]
        yield _say(
            f"Translation memory: {reused} segment{'s' if reused != 1 else ''} reused"
            f" ({tm_stats['words']} words, no model call), {tm_stats['fuzzy']} fuzzy match{'es' if tm_stats['fuzzy'] != 1 else ''} to adapt",
            state={**tm_delta, "doc:tm_stats": tm_stats},
        )
        prefilled = {seg["id"] for seg in tm_delta.values()}
        batches = page_batches([s for s in segments if s["id"] not in prefilled and not s.get("target")], settings.page_max_chars)
        total = len(batches)
    all_terms: list[dict] = []
    part_of_page: dict[int, int] = {}
    flagged = 0
    decided = {k["term"].casefold() for k in ctx.state.get("doc:key_terms") or []}  # the analysis settled these

    for i, batch in enumerate(batches):
        page = batch[0]["page"]
        part_of_page[page] = part_of_page.get(page, 0) + 1
        multi = sum(1 for b in batches if b[0]["page"] == page) > 1
        tm_lines = [
            f"- [{s['id']}] {tm_refs[s['id']]['score']}% · {tm_refs[s['id']]['source']} → {tm_refs[s['id']]['target']}"
            for s in batch
            if s["id"] in tm_refs
        ]
        result = await _translate_batch(
            ctx,
            f"translate-{i}",
            batch,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in batch]),
            instructions=instructions,
            tm="\n".join(tm_lines) or "(none)",
            termbase=st.termbase_text({"doc:termbase": termbase}),
            context=_carried_context(segments, batch[0]["id"], translations, settings.carry_context_chars),
            scope=_scope(batch, part_of_page[page] if multi else None),
            brief=brief,
            detect=detect and i == 0,
        )
        # Models sometimes report made-up "terms" (e.g. "p1.7 fragment") or join two terms with "/".
        terms = [t for t in result.terms if qa.in_source(t["term"], batch) and t["term"].casefold() not in decided]
        result.keeps = {k: v for k, v in result.keeps.items() if qa.in_source(k, batch)}
        delta: dict[str, Any] = {}
        for seg in batch:
            produced = result.translated.get(seg["id"])
            # Fall back to the source text if the model dropped a segment; the flag forces a fix in review.
            target = produced or seg["source"]
            flags = qa.check_segment(seg, produced, merged=seg["id"] in result.merged)
            flagged += bool(flags)
            translations[seg["id"]] = target
            snap[seg["id"]] = target
            ref = tm_refs.get(seg["id"])
            new = st.apply_target(seg, target, origin="tm_fuzzy" if ref else "mt", status="draft", flags=flags)
            if ref:
                new["match"] = ref["score"]
            delta[st.seg_key(seg["id"])] = new
        if result.detected:
            source_lang = result.detected.strip()
            delta["doc:detected_lang"] = source_lang
        if result.brief:
            brief = result.brief
            delta["doc:brief"] = brief
        all_terms.extend(terms)
        # Uncertain guesses must not become "rules" for later pages.
        keeps = st.without_terms(result.keeps, {t["term"] for t in all_terms})
        if keeps:
            termbase = st.merge_termbase(ctx.state, termbase, keeps)
            delta["doc:termbase"] = termbase
        if terms:
            delta["doc:questions"] = st.add_questions(ctx.state, all_terms, origin="translator")
        delta.update(_progress("translate", i + 1, total, f"Translated {_scope(batch)} ({i + 1}/{total})"))
        yield Event(state=delta)

    version_delta = await _save_version(ctx, "Draft translation", [s["id"] for s in segments if s["translatable"]], snap)
    open_q = len(st.open_questions(ctx.state))
    msg = "Draft translation ready (v1)"
    if termbase:
        msg += f"; {len(termbase)} term{'s' if len(termbase) != 1 else ''} kept consistent across pages"
    if open_q:
        msg += f" — {open_q} term{'s' if open_q != 1 else ''} flagged for clarification"
    if flagged:
        msg += f" — {flagged} segment{'s' if flagged != 1 else ''} need{'s' if flagged == 1 else ''} a fix in review"
    yield _say(msg, state={**version_delta, "doc:review_round": 0, "doc:review_report": []})
    yield Event(output={"batches": total})


def _segments_mentioning(segments: list[dict], term: str) -> set[str]:
    t = term.casefold()
    return {s["id"] for s in segments if t in s["source"].casefold()}


@node(rerun_on_resume=True)
async def clarify(ctx: Context, node_input: Any):
    """Terms the translator still couldn't resolve after the analysis: pause once; answers re-translate the
    segments that use them."""
    settings = get_settings()
    open_qs = st.open_questions(ctx.state)
    if not open_qs:
        yield Event(output={"clarified": 0})
        return

    answers = (ctx.resume_inputs or {}).get(CLARIFY_INTERRUPT)
    if answers is None:
        n = len(open_qs)
        text = (f"Before the review pass I need your help with {n} term{'s' if n != 1 else ''} I wasn't sure about. "
                "Each card explains the term and preselects my recommendation; skip to keep my guesses.")
        async for item in _pause_for(CLARIFY_INTERRUPT, open_qs, text):
            yield item
        return

    # Resumed with {question_id: {"target", "note"} | null}.
    questions, glossary, answered, kept = _record_answers(ctx.state, open_qs, answers if isinstance(answers, dict) else {})
    segments = st.get_segments(ctx.state)
    affected: set[str] = set()
    for q in open_qs:
        if q["term"] in glossary:
            affected |= set(q["segment_ids"]) | _segments_mentioning(segments, q["term"])

    termbase = st.without_terms(st.merge_termbase({"doc:glossary": glossary}, dict(ctx.state.get("doc:termbase") or {}), kept),
                                set(glossary))
    if not answered:
        yield _say("Keeping my best guesses.", state={"doc:questions": questions, "doc:termbase": termbase,
                                                       **_progress("clarify", 0, 0, "Continuing…", "reviewing")})
        yield Event(output={"clarified": 0})
        return

    targets = [s for s in segments if s["id"] in affected and s["translatable"] and not st.is_frozen(s)]
    batches = page_batches(targets, settings.page_max_chars)
    total = len(batches)
    termbase_text = st.termbase_text(ctx.state)
    source_lang, target_lang = _langs(ctx.state)
    yield _say(
        f"Thanks! Applying {answered} answer{'s' if answered != 1 else ''}: re-translating {len(targets)} segment{'s' if len(targets) != 1 else ''}",
        state={
            "doc:questions": questions,
            "doc:glossary": glossary,
            "doc:termbase": termbase,
            **_progress("clarify", 0, total, "Applying your answers…", "translating"),
        },
    )

    snap = st.snapshot(ctx.state)
    changed: list[str] = []
    done = 0
    tasks = [
        lambda i=i, b=b: _translate_batch(
            ctx,
            f"clarify-{i}",
            b,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in b], glossary),
            termbase=termbase_text,
            context=_page_context(segments, b, settings.carry_context_chars * 2),
            scope=f"{_scope(b)} — re-translate these segments only, applying the glossary",
            brief=ctx.state.get("doc:brief") or "",
            instructions=projects.instructions_for(ctx.state),
        )
        for i, b in enumerate(batches)
    ]
    async for i, result in _bounded(tasks, settings.max_concurrency):
        done += 1
        delta: dict[str, Any] = {}
        for seg in batches[i]:
            new = result.translated.get(seg["id"])
            if new and new != seg.get("target"):
                delta[st.seg_key(seg["id"])] = st.apply_target(seg, new, origin="mt", status="draft")
                snap[seg["id"]] = new
                changed.append(seg["id"])
        delta.update(_progress("clarify", done, total, f"Re-translated {_scope(batches[i])} ({done}/{total})"))
        yield Event(state=delta)

    version_delta = await _save_version(ctx, "Applied your clarifications", changed, snap) if changed else {}
    yield _say(f"Updated {len(changed)} segment{'s' if len(changed) != 1 else ''} with your answers", state=version_delta)
    yield Event(output={"clarified": answered})


def _already_used(term: dict, batch: list[dict]) -> bool:
    """A reviewer "question" whose recommendation is what the translation already says confirms it rather
    than asking anything: not worth a person's time."""
    guess = (term.get("guess") or "").casefold().strip()
    if not guess:
        return False
    segs = [s for s in batch if s["id"] in set(term.get("segment_ids") or [])] or batch
    word = re.compile(rf"(?<!\w){re.escape(guess)}(?!\w)")  # whole words: "live" isn't in "delivered"
    return any(word.search(inline.strip(s.get("target") or "").casefold()) for s in segs)


@node(rerun_on_resume=True)
async def review(ctx: Context, node_input: Any):
    settings = get_settings()
    round_no = int(ctx.state.get("doc:review_round") or 0) + 1
    segments = st.get_segments(ctx.state)
    pending = ctx.state.get("doc:review_pending")  # None = first round; else ids the refiner changed
    if pending is not None:
        pending_set = set(pending)
        segments = [s for s in segments if s["id"] in pending_set]
    if not segments:  # the last refine pass changed nothing → nothing new to review
        yield Event(output={"issues": []}, route="done")
        return
    batches = page_batches(segments, settings.page_max_chars)
    total = len(batches)
    source_lang, target_lang = _langs(ctx.state)
    yield _say(
        f"Review round {round_no}: checking {sum(len(b) for b in batches)} segments",
        state=_progress("review", 0, total, f"Reviewing (round {round_no})…", "reviewing"),
    )

    review_format = prompts.REVIEW_FORMAT_JSON if structured.enabled("review") else prompts.REVIEW_FORMAT_TAGS
    # Deterministic findings (untranslated / merged segments, QA errors such as a missing number or a
    # forbidden term) are always fixed, whatever the reviewer says.
    forced: list[dict] = qa.forced_review_issues(ctx.state, segments)
    # Terms already settled (the analysis's key terms, the glossary) aren't questions for the person.
    decided = {k["term"].casefold() for k in ctx.state.get("doc:key_terms") or []}
    decided |= {g.casefold() for g in ctx.state.get("doc:glossary") or {}}

    async def review_batch(i: int, batch: list[dict]) -> tuple[list[dict], list[dict], dict[str, int]]:
        ids = {s["id"] for s in batch}
        auto = "\n".join(f"- [{x['segment_id']}] {x['note']}" for x in forced if x["segment_id"] in ids)
        prompt = prompts.REVIEW.format(
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in batch]),
            termbase=st.termbase_text(ctx.state),
            brief=ctx.state.get("doc:brief") or "(none)",
            instructions=projects.instructions_for(ctx.state),
            pairs=_pairs(batch),
            auto_issues=auto or "(none)",
            output_format=review_format,
        )
        out = _text(await ctx.run_node(reviewer, node_input=_user(prompt), run_id=f"review-r{round_no}-b{i}"))
        issues, terms, scores = _parse_review(out)
        terms = [t for t in terms if qa.in_source(t["term"], batch) and t["term"].casefold() not in decided
                 and not _already_used(t, batch)]
        return (
            [x for x in issues if x["segment_id"] in ids],
            terms[: settings.max_questions_per_batch],
            {k: v for k, v in scores.items() if k in ids},
        )

    issues: list[dict] = list(forced)
    terms: list[dict] = []
    scores: dict[str, int] = {}
    done = 0
    async for _, (batch_issues, batch_terms, batch_scores) in _bounded(
        [lambda i=i, b=b: review_batch(i, b) for i, b in enumerate(batches)], settings.max_concurrency
    ):
        done += 1
        issues.extend(batch_issues)
        terms.extend(batch_terms)
        scores.update(batch_scores)
        yield Event(state=_progress("review", done, total, f"Reviewed {done}/{total} (round {round_no})"))

    majors = sum(1 for x in issues if is_major(x))
    # Record the AI verdict and quality estimate per segment. This is NOT the human "reviewed" status.
    major_ids = {x["segment_id"] for x in issues if is_major(x)}
    passed = {
        st.seg_key(s["id"]): {
            **st.normalize(s),
            "ai_check": "issues" if s["id"] in major_ids or s.get("flags") else "passed",
            "qe": scores.get(s["id"], s.get("qe")),
        }
        for s in segments
        if not st.is_frozen(s)
    }
    report = list(ctx.state.get("doc:review_report") or [])
    report.append({"batch": 0, "round": round_no, "issues": issues})
    delta: dict[str, Any] = {"doc:review_round": round_no, "doc:review_report": report, **passed}
    if terms:
        delta["doc:questions"] = st.add_questions(ctx.state, terms, origin="reviewer")

    to_fix = issues_to_fix(issues, segments, round_no)
    go_refine = bool(to_fix) and round_no <= settings.review_max_rounds
    summary = (
        f"Review round {round_no}: {len(issues)} issue{'s' if len(issues) != 1 else ''} ({majors} major)"
        if issues
        else f"Review round {round_no}: no issues found"
    )
    yield _say(summary + (" — refining" if go_refine else ""), state=delta)
    yield Event(output={"issues": to_fix if go_refine else []}, route="refine" if go_refine else "done")


@node(rerun_on_resume=True)
async def refine(ctx: Context, node_input: Any):
    settings = get_settings()
    issues: list[dict] = (node_input or {}).get("issues", [])
    by_seg: dict[str, list[dict]] = {}
    for x in issues:
        by_seg.setdefault(x["segment_id"], []).append(x)
    targets = [s for s in st.get_segments(ctx.state) if s["id"] in by_seg and not st.is_frozen(s)]
    batches = page_batches(targets, settings.page_max_chars)
    total = len(batches)
    round_no = int(ctx.state.get("doc:review_round") or 1)
    source_lang, target_lang = _langs(ctx.state)
    yield Event(state=_progress("refine", 0, total, f"Refining {len(targets)} segments…", "reviewing"))

    async def refine_batch(i: int, batch: list[dict]) -> dict[str, str]:
        issue_text = "\n".join(
            f"- [{x['segment_id']}] ({x['severity']}) {x['note']}" for s in batch for x in by_seg[s["id"]]
        )
        prompt = prompts.REFINE.format(
            source_lang=source_lang, target_lang=target_lang,
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in batch]),
            termbase=st.termbase_text(ctx.state), pairs=_pairs(batch), issues=issue_text,
            instructions=projects.instructions_for(ctx.state), inline_rules=_inline_rules(batch),
            output_format=prompts.REFINE_FORMAT_JSON if structured.enabled("translate") else prompts.REFINE_FORMAT_TAGS,
        )
        out = _text(await ctx.run_node(refiner, node_input=_user(prompt), run_id=f"refine-r{round_no}-b{i}"))
        coded = {s["id"] for s in batch if inline.has_codes(s["source"])}
        return {k: inline.normalize(v) if k in coded and v else v for k, v in _parse_revision(out).items()}

    changed: list[str] = list(ctx.state.get("doc:refined") or [])
    changed_now: list[str] = []
    done = 0
    async for i, revised in _bounded(
        [lambda i=i, b=b: refine_batch(i, b) for i, b in enumerate(batches)], settings.max_concurrency
    ):
        done += 1
        delta: dict[str, Any] = {}
        for seg in batches[i]:
            new = revised.get(seg["id"])
            if new and new != seg.get("target"):
                delta[st.seg_key(seg["id"])] = st.apply_target(seg, new, origin="mt", status="draft")
                changed_now.append(seg["id"])
                if seg["id"] not in changed:
                    changed.append(seg["id"])
        delta.update(_progress("refine", done, total, f"Refined batch {done}/{total}"))
        yield Event(state=delta)

    n = len(targets)
    yield _say(
        f"Refiner revised {len(changed_now)} of {n} flagged segment{'s' if n != 1 else ''}"
        if changed_now
        else "Refiner kept the current wording",
        state={"doc:refined": changed, "doc:review_pending": changed_now},
    )
    yield Event(output={"refined": len(targets)})


@node(rerun_on_resume=True)
async def polish(ctx: Context, node_input: Any):
    """Before handing over: one translation per repeated sentence and the termbase applied. This is still
    the AI draft, so the fixes are applied directly (the consistency task on a finished document only
    proposes them)."""
    from .ops import consistency_fixes  # ops builds on this module

    try:
        fixes, counts = await consistency_fixes(ctx)
    except Exception as exc:  # polishing is a bonus; never lose the reviewed translation over it
        log.warning("polish failed: %s", exc)
        fixes, counts = {}, {}
    current = {s["id"]: s for s in st.get_segments(ctx.state)}
    delta: dict[str, Any] = {}
    for sid, text in fixes.items():
        if (seg := current.get(sid)) is not None:
            delta[st.seg_key(sid)] = st.apply_target(seg, text, origin=seg.get("origin") or "mt", status=seg.get("status") or "draft")
    if delta:
        refined = list(ctx.state.get("doc:refined") or [])
        delta["doc:refined"] = refined + [sid for sid in fixes if sid not in refined]
        n = len(fixes)
        parts = []
        if counts.get("same"):
            parts.append(f"{counts['same']} repeated sentence{'s' if counts['same'] != 1 else ''} unified")
        if counts.get("terms"):
            parts.append(f"{counts['terms']} termbase rule{'s' if counts['terms'] != 1 else ''} applied")
        yield _say(f"Consistency pass: {n} segment{'s' if n != 1 else ''} adjusted ({', '.join(parts)})", state=delta)
    yield Event(output={"polished": len(fixes)})


@node(rerun_on_resume=True)
async def finalize(ctx: Context, node_input: Any):
    changed = list(ctx.state.get("doc:refined") or [])
    delta: dict[str, Any] = {"doc:refined": [], "doc:review_pending": None}  # reset for any later re-run
    # A reviewer's question whose recommendation the refiner has since applied asks nothing any more.
    segs = st.get_segments(ctx.state)
    questions = [dict(q) for q in ctx.state.get("doc:questions") or []]
    moot = [q for q in questions if q["status"] == "open" and q.get("origin") == "reviewer" and _already_used(q, segs)]
    for q in moot:
        q.update(status="resolved", answer="applied in review", answer_target=q.get("guess"))
    if moot:
        delta["doc:questions"] = questions
    if changed:
        delta.update(await _save_version(ctx, "AI review fixes", changed))
    delta.update(_progress("done", 0, 0, "Done", "ready"))

    n_versions = len((delta.get("doc:versions") or ctx.state.get("doc:versions") or []))
    open_q = [q for q in (delta.get("doc:questions") or ctx.state.get("doc:questions") or []) if q["status"] == "open"]
    _, target_lang = _langs(ctx.state)
    lines = [
        f"Your {target_lang} translation is ready (v{n_versions}).",
        f"The AI reviewer's fixes changed {len(changed)} segment{'s' if len(changed) != 1 else ''} — open **Changes** to see the diff."
        if changed
        else "The AI reviewer didn't require any changes.",
    ]
    still_flagged = [x["id"] for x in st.get_segments(ctx.state) if x.get("flags")]
    if still_flagged:
        lines.append(
            f"⚠️ {len(still_flagged)} segment{'s' if len(still_flagged) != 1 else ''} still need attention "
            f"({', '.join(still_flagged[:6])}{'…' if len(still_flagged) > 6 else ''}) — they're marked in the translation."
        )
    if open_q:
        lines.append(
            f"I wasn't sure about {len(open_q)} term{'s' if len(open_q) != 1 else ''} "
            f"({', '.join('“' + q['term'] + '”' for q in open_q[:5])}). Answer the question cards below and I'll update the translation."
        )
    yield _say("\n\n".join(lines), kind="assistant", state=delta)  # next steps are buttons in the UI
    yield Event(output={"versions": n_versions})


ingest_workflow = Workflow(
    name=PIPELINE_NAME,
    edges=[
        (START, route_source),
        (route_source, {"ocr": ocr, "extract": extract}),
        (ocr, analyse, ask, translate, clarify, review),
        (extract, analyse),
        (review, {"refine": refine, "done": polish}),
        (refine, review),
        (polish, finalize),
    ],
)

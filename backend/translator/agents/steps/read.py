"""Reading the source: every page of a PDF or an image read at once, each by its own small graph (agents/steps/
page.py: two models read it, and where they differ the OCR check model settles it), then the source check pause.

    ocr → read_pages (the page graph, for each page in parallel) → assemble → check_source"""

from __future__ import annotations

import asyncio
from typing import Any

from google.adk import Context, Event
from google.adk.events import RequestInput
from google.adk.workflow import node

from ...config import get_settings
from ...document import source_check
from ...document import state as st
from ...document.pages import page_count, segments_from_pages
from ...ocr import second
from ..common import progress_state, say
from .page import layer_agreement, page, signature  # noqa: F401  (layer_agreement, signature: used by tests)
from .settle import load_json

SOURCE_INTERRUPT = "source_check"


@node(rerun_on_resume=True)
async def ocr(ctx: Context, node_input: Any):
    """Which pages there are; the page graph reads them (`read_pages`)."""
    filename = ctx.state.get("doc:filename") or "document.pdf"
    artifact = await ctx.load_artifact(ctx.state.get("doc:source_artifact"))
    if artifact is None or artifact.inline_data is None:
        raise RuntimeError("Source document artifact is missing.")
    total = await asyncio.to_thread(page_count, artifact.inline_data.data, filename)
    text = source_format(filename) == "text"
    two = second.enabled(ctx.state)
    yield say(
        "Reading text document" if text else
        f"Reading {total} page{'s' if total != 1 else ''} with vision OCR"
        + (" (two models, side by side)" if two else " + OCR check" if get_settings().ocr_check_enabled else ""),
        state={**progress_state("ocr", 0, total, "Running OCR…", "ocr"), "doc:pages": total, "doc:ocr_done": 0},
    )
    yield Event(output=[{"page": n} for n in range(1, total + 1)])


# Every page at once (at most MAX_CONCURRENCY pages; within a page, the two readers run side by side).
read_pages = node(page, name="read_pages", parallel_worker=True, max_parallel_workers=max(1, get_settings().max_concurrency))


@node(rerun_on_resume=True)
async def assemble(ctx: Context, node_input: Any):
    """The pages' results (`ocr-p{n}.json`) → the document's segments."""
    total = int(ctx.state.get("doc:pages") or 0)
    results = [await load_json(ctx, f"ocr-p{n}.json") for n in range(1, total + 1)]
    missing = [n for n, r in enumerate(results, start=1) if r is None]
    if missing:
        raise RuntimeError(f"Page{'s' if len(missing) != 1 else ''} {', '.join(map(str, missing))} not read.")
    page_md = [(n, r["markdown"]) for n, r in enumerate(results, start=1)]
    figure_meta = {(n, int(k)): v for n, r in enumerate(results, start=1) for k, v in r["meta"].items()}
    segments = segments_from_pages(page_md, figure_meta)
    if not segments:
        raise RuntimeError("OCR produced no text. Is the document blank or unreadable?")
    reused = {r["page"] for r in node_input or [] if r and r.get("cached")}
    reports = [{**r["report"], **({"cached": True} if n in reused else {})} for n, r in enumerate(results, start=1)]
    delta: dict[str, Any] = {st.seg_key(s["id"]): st.normalize(s) for s in segments}
    delta["doc:seg_ids"] = [s["id"] for s in segments]
    delta["doc:ocr_report"] = reports
    fixed = sum(1 for r in reports if not r["ok"])
    hard = [r["page"] for r in reports if r.get("hard")]
    n_fig = len(figure_meta)
    yield say(
        f"OCR done: {len(segments)} segments"
        + (f" incl. {n_fig} figure{'s' if n_fig != 1 else ''}" if n_fig else "")
        + f"; corrected on {fixed} of {total} page(s)"
        + (f"; hard to read: page{'s' if len(hard) != 1 else ''} {', '.join(map(str, hard))}" if hard else ""),
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
        if r.get("hard"):
            notes.append(f"**hard to read**: the two readings differ in {r.get('disagreements', 0)} places, so nothing "
                         "was changed — check the whole page")
        elif n := len(r.get("suggestions") or []):
            notes.append(f"{n} possible misreading{'s' if n != 1 else ''} the OCR check listed but didn't change")
        if not r.get("ok", True) and (n := len(r.get("issues") or [])):
            notes.append(f"the OCR check corrected {n} thing{'s' if n != 1 else ''}"
                         + (" where the two readings differed" if r.get("readers") == 2 else ""))
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

"""One page of a PDF or an image upload, read as its own small graph; the ingest workflow runs it for every page at
once (`read_pages` in agents/steps/read.py):

    START → prepare ─(read)──→ figures → first ∥ second → read → compare ─(disagree)─→ arbitrate → finish
                    └(done)──→ finish                                    ├(single)───→ check ─────→ finish
                                                                         └(done)─────────────────→ finish

* prepare   renders the page; a page whose result an earlier run saved (and nothing it depends on changed), or a
            text file, is done. Otherwise it finds the picture candidates: the PDF's embedded images, and the
            pictures, charts and seals the layout model finds.
* figures   reads each candidate with the picture graph (agents/steps/picture.py): a picture keeps its text as its
            legend, a block of text is read with the page. Then the page image the readers get: pictures outlined
            and numbered in red, enlarged when it is small (vision models misread small text).
* first ∥ second   two models read the page at the same time (the `ocr` and `ocr_second` steps). There is no second
            reading on a PDF page with its own text layer (that is a second reading already) or when it is off.
* compare   word by word (ocr/compare.py): the same → done; a few differences → arbitrate; so many that the page is
            hard to read (at least OCR_HARD_MIN, and more than OCR_HARD_RATE per 100 words) → done, nothing changed,
            the differences listed and the page marked. With one reading → check.
* arbitrate the OCR check model says what is printed at each difference (agents/steps/settle.py).
* check     the OCR check as with one reader: skipped where the reading is the PDF's own text layer; otherwise the
            check model lists its amendments, applied where safe (ocr/guard.py), the rest listed.
* finish    puts the figure markers in, saves the figures and the page's result (`ocr-p{n}.json`, which is also
            the cache), and says how the page went.

Nodes pass the page number; the page image, the readings and the results are artifacts (`ocr-p{n}-…`), so session
events stay small."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from typing import Any

from google.adk import Context, Event
from google.adk.workflow import START, JoinNode, Workflow, node
from google.genai import types
from rapidfuzz import fuzz

from ...config import get_settings
from ...document.pages import Figure, Page, crop_png, enlarged, load_page, mark_figures, place_figure_marker
from ...models import routing
from ...models.replies import clean, parse_ocr_fixes
from ...ocr import compare, layout, second
from ...ocr.figures import FIGURE_LABELS, Guard, judge
from ...ocr.guard import apply_fixes, guard
from .. import prompts
from ..common import progress_state, reply_text, run_bounded, say, user_message
from ..workers import ocr_checker, ocr_reader, ocr_second_reader
from .picture import picture
from .settle import MAX_LISTED, arbitrate, decide, describe, load_bytes, load_json, save_json

OCR_CACHE_VERSION = 5  # 5: two readings, settled by the OCR check model; the check amends


def _overlap(a: tuple, b: tuple) -> float:
    """Intersection over the smaller box."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / smaller


def figure_guard() -> Guard:
    return Guard(text_cover=get_settings().figure_text_cover)


def two_readings(page: Page, state) -> bool:
    """A second reading for this page: on (Settings, the document, the server), and not a page with a text layer."""
    return second.enabled(state) and (not page.has_text_layer or page.full_page_image)


def signature(page: Page, state=None) -> str:
    """What a page's result depends on: the page itself, the reading models the document uses (and their levels),
    the OCR settings and the prompts."""
    s = get_settings()
    two = two_readings(page, state)
    h = hashlib.sha1(page.image or b"")
    steps = ("ocr", "ocr_second", "ocr_check") if two else ("ocr", "ocr_check")
    models = [f"{m.model_name}/{m.effort}" for m in (routing.resolve(step, state) for step in steps)]
    for part in (page.text_layer, *models, two, s.layout_model, s.ocr_check_enabled, s.ocr_check, s.figure_detection,
                 s.figure_text, s.figure_check, s.ocr_hard_rate, s.ocr_hard_min, s.ocr_min_page_px, s.ocr_min_picture_px,
                 s.ocr_max_upscale, s.ocr_max_image_px, json.dumps(layout.thresholds(), sort_keys=True), figure_guard(),
                 OCR_CACHE_VERSION, prompts.VISION_OCR, prompts.VISION_OCR_TEXT_LAYER, prompts.VISION_OCR_FIGURES,
                 prompts.OCR_CHECK, prompts.FIGURE_CHECK, prompts.ARBITRATE):  # a better prompt reads the page again
        h.update(str(part).encode())
    return h.hexdigest()


async def load(ctx: Context, number: int) -> Page:
    artifact = await ctx.load_artifact(ctx.state.get("doc:source_artifact"))
    if artifact is None or artifact.inline_data is None:
        raise RuntimeError("Source document artifact is missing.")
    return await asyncio.to_thread(load_page, artifact.inline_data.data, ctx.state.get("doc:filename") or "document.pdf",
                                   number, get_settings().ocr_dpi)


async def save_text(ctx: Context, name: str, text: str) -> None:
    await save_json(ctx, name, {"text": text})


async def load_text(ctx: Context, name: str) -> str:
    return ((await load_json(ctx, name)) or {}).get("text", "")


def _image_size(png: bytes) -> tuple[int, int]:
    import pymupdf

    pix = pymupdf.Pixmap(png)
    return pix.width, pix.height


async def candidates(page: Page) -> tuple[list[Figure], list[dict]]:
    """Picture candidates that pass the checks in ocr/figures.py → (candidates, regions turned down as pictures).
    The PDF's embedded images, plus the pictures, charts and seals PP-DocLayoutV3 finds (the layout server, if it is
    running) on scans and in vector drawings."""
    if get_settings().figure_detection == "off":
        return [], []
    guard_ = figure_guard()
    size = _image_size(page.image)
    text_blocks = page.text_blocks if page.has_text_layer else []
    found: list[Figure] = []
    dropped: list[dict] = []
    for f in page.figures:  # an image embedded in a PDF: a picture unless the PDF's own text covers it
        if reason := judge(f.box, "image", 1.0, size, [], text_blocks, from_layout=False, guard=guard_):
            dropped.append({"label": "image", "reason": reason})
        else:
            found.append(f)
    detected = await layout.detect_layout(page.image) if layout.available() else None
    regions = (detected or {}).get("regions") or []
    for r in regions:
        box = tuple(r["box"])
        if r["label"] not in FIGURE_LABELS or any(_overlap(box, f.box) > 0.5 for f in page.figures):
            continue
        if reason := judge(box, r["label"], float(r.get("score", 1.0)), size, regions, text_blocks, guard=guard_):
            dropped.append({"label": r["label"], "reason": reason})
            continue
        found.append(Figure(box=box, png=crop_png(page.image, box), anchor=page.anchor_below(box), kind=r["label"],
                            source="layout"))
    found.sort(key=lambda f: (round(f.box[1]), f.box[0]))
    return found, dropped


@node(name="page_prepare", rerun_on_resume=True)
async def prepare(ctx: Context, node_input: Any):
    n = node_input["page"]
    page = await load(ctx, n)
    if page.image is None:  # a text file: read as it is
        report = {"page": n, "ok": True, "issues": [], "used_text_layer": False, "figures": 0}
        await save_json(ctx, f"ocr-p{n}.json", {"sig": "", "markdown": page.text_layer, "report": report, "meta": {}})
        yield Event(output={"page": n, "ready": True}, route="done")
        return
    sig = signature(page, ctx.state)
    cached = await load_json(ctx, f"ocr-p{n}.json")
    if cached and cached.get("sig") == sig:
        yield Event(output={"page": n, "ready": True, "cached": True}, route="done")
        return
    found, dropped = await candidates(page)
    for k, f in enumerate(found, start=1):
        await ctx.save_artifact(f"figcand-p{n}-{k}.png", types.Part.from_bytes(data=f.png, mime_type="image/png"))
    await save_json(ctx, f"ocr-p{n}-cand.json", {
        "sig": sig, "dropped": dropped,
        "candidates": [{"box": list(f.box), "kind": f.kind, "source": f.source, "anchor": f.anchor,
                        "sha": hashlib.sha1(f.png).hexdigest()} for f in found]})
    yield Event(output={"page": n}, route="read")


@node(name="page_figures", rerun_on_resume=True)
async def figures(ctx: Context, node_input: Any):
    settings = get_settings()
    n = node_input["page"]
    cand = await load_json(ctx, f"ocr-p{n}-cand.json")
    page = await load(ctx, n)
    found = cand["candidates"]
    report = {"page": n, "ok": True, "issues": [], "used_text_layer": page.has_text_layer, "figures": 0}
    results: list[dict | None] = [None] * len(found)
    if found and not (settings.figure_check == "off" and not settings.figure_text):
        items = [{"key": f"p{n}-{k}-{c['sha']}", "image": f"figcand-p{n}-{k}.png", "label": c["kind"]}
                 for k, c in enumerate(found, start=1)]
        tasks = [lambda it=it: ctx.run_node(picture, node_input=it, run_id=f"picture-{it['key'][:24]}", use_sub_branch=True)
                 for it in items]
        async for i, res in run_bounded(tasks, settings.max_concurrency):
            results[i] = res
    kept, as_text, notes, changes = [], [], [], []
    for k, (c, r) in enumerate(zip(found, results), start=1):
        if r is not None and settings.figure_check == "auto" and r["kind"] == "text" and c["kind"] != "seal":
            as_text.append({"label": c["kind"], "reason": "vision"})  # a block of text: the page reading has it
            continue
        kept.append({**c, "cand": k, "legend": (r or {}).get("text", "") if settings.figure_text else ""})
        number = len(kept)
        notes += [f"Figure {number}: {o}" for o in (r or {}).get("open", [])]
        changes += [f"Figure {number}: {o}" for o in (r or {}).get("changed", [])]
    sources = {c["source"] for c in kept}
    report.update(figures=len(kept), figure_source="+".join(x for x in ("pdf", "layout") if x in sources),
                  seals=sum(c["kind"] == "seal" for c in kept))
    if cand["dropped"] or as_text:
        report["figures_as_text"] = cand["dropped"] + as_text
    boxes = [tuple(c["box"]) for c in kept]
    png = mark_figures(page.image, boxes) if boxes else page.image
    mime = "image/png" if boxes else page.image_mime
    big = await asyncio.to_thread(enlarged, png, settings.ocr_min_page_px, settings.ocr_max_upscale, settings.ocr_max_image_px)
    if big is not png:
        mime = "image/png"
        report["enlarged"] = True
    await ctx.save_artifact(f"ocr-p{n}-page.png", types.Part.from_bytes(data=big, mime_type=mime))
    text_layer = page.text_layer_outside(boxes) if page.has_text_layer else ""
    hint = prompts.VISION_OCR_TEXT_LAYER.format(
        text_layer=text_layer.strip(), outside_figures=" (the text inside the red boxes is left out of it)" if boxes else ""
    ) if text_layer.strip() else ""
    fig_hint = prompts.VISION_OCR_FIGURES.format(n=len(boxes)) if boxes else ""
    await save_json(ctx, f"ocr-p{n}-prep.json", {
        "sig": cand["sig"], "prompt": f"Transcribe page {n}.{fig_hint}{hint}", "mime": mime, "kept": kept,
        "text_layer": text_layer, "figure_note": prompts.OCR_CHECK_MARKED_FIGURES if boxes else "",
        "full_page_image": page.full_page_image, "two": two_readings(page, ctx.state), "report": report,
        "figure_notes": notes, "figure_changes": changes})
    yield Event(output={"page": n})


async def _page_image(ctx: Context, n: int, mime: str) -> types.Part:
    return types.Part.from_bytes(data=await load_bytes(ctx, f"ocr-p{n}-page.png"), mime_type=mime)


async def _read(ctx: Context, agent, n: int, run_id: str) -> str:
    prep = await load_json(ctx, f"ocr-p{n}-prep.json")
    out = await ctx.run_node(agent, node_input=user_message(await _page_image(ctx, n, prep["mime"]), prep["prompt"]),
                             run_id=run_id)
    return clean(reply_text(out))


@node(name="page_first", rerun_on_resume=True)
async def first(ctx: Context, node_input: Any):
    n = node_input["page"]
    await save_text(ctx, f"ocr-p{n}-first.md", await _read(ctx, ocr_reader, n, f"ocr-p{n}"))
    yield Event(output={"page": n})


@node(name="page_second", rerun_on_resume=True)
async def second_reading(ctx: Context, node_input: Any):
    n = node_input["page"]
    if not (await load_json(ctx, f"ocr-p{n}-prep.json"))["two"]:
        yield Event(output={"page": n, "skipped": True})
        return
    await save_text(ctx, f"ocr-p{n}-second.md", await _read(ctx, ocr_second_reader, n, f"ocr2-p{n}"))
    yield Event(output={"page": n})


read = JoinNode(name="page_read")


@node(name="page_compare", rerun_on_resume=True)
async def compare_readings(ctx: Context, node_input: Any):
    n = node_input["page_first"]["page"]
    ours = await load_text(ctx, f"ocr-p{n}-first.md")
    if node_input["page_second"].get("skipped"):
        await save_json(ctx, f"ocr-p{n}-work.json", {"markdown": ours})
        yield Event(output={"page": n}, route="single")
        return
    theirs = await load_text(ctx, f"ocr-p{n}-second.md")
    if not ours.strip() and theirs.strip():  # the first reader returned nothing: the second's reading is the page
        ours, theirs = theirs, ours
    found = compare.disputes(ours, theirs)
    rate = compare.rate(ours, found)
    work: dict[str, Any] = {"markdown": ours, "theirs": theirs, "disagreements": len(found), "rate": round(rate, 1)}
    settings = get_settings()
    if len(found) >= settings.ocr_hard_min and rate > settings.ocr_hard_rate:
        listed = [describe(d) for d in found[:MAX_LISTED]]
        if len(found) > MAX_LISTED:
            listed.append(f"… and {len(found) - MAX_LISTED} more: check the whole page")
        work.update(hard=True, open=listed)
    await save_json(ctx, f"ocr-p{n}-work.json", work)
    yield Event(output={"page": n}, route="disagree" if found and not work.get("hard") else "done")


@node(name="page_arbitrate", rerun_on_resume=True)
async def arbitrate_page(ctx: Context, node_input: Any):
    n = node_input["page"]
    prep, work = await load_json(ctx, f"ocr-p{n}-prep.json"), await load_json(ctx, f"ocr-p{n}-work.json")
    found = compare.disputes(work["markdown"], work["theirs"])
    answers = await arbitrate(ctx, await _page_image(ctx, n, prep["mime"]), found, "page", f"settle-p{n}")
    settled = decide(work["markdown"], found, answers)
    work.update(markdown=settled.text, changed=settled.changed, open=settled.open, settled=len(found) - len(settled.open))
    await save_json(ctx, f"ocr-p{n}-work.json", work)
    yield Event(output={"page": n})


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


@node(name="page_check", rerun_on_resume=True)
async def check(ctx: Context, node_input: Any):
    """One reading: skipped where it is the PDF's own text layer (two independent readings agree); otherwise the
    check model compares it with the image and lists its amendments, applied only where safe (`ocr/guard.py`) —
    the rest are listed as possible misreadings."""
    settings = get_settings()
    n = node_input["page"]
    prep, work = await load_json(ctx, f"ocr-p{n}-prep.json"), await load_json(ctx, f"ocr-p{n}-work.json")
    markdown, text_layer = work["markdown"], prep["text_layer"]
    agreement = layer_agreement(markdown, text_layer) if text_layer.strip() and not prep["full_page_image"] else 0
    if settings.ocr_check == "auto" and agreement >= settings.ocr_check_agreement:
        work.update(checked="text layer", agreement=round(agreement, 1))
    elif settings.ocr_check_enabled and markdown:
        check_prompt = prompts.OCR_CHECK.format(
            transcription=markdown,
            text_layer_hint=" (and the PDF's embedded text layer)" if text_layer.strip() else "",
            text_layer_block=f"\n\n<text_layer>\n{text_layer.strip()}\n</text_layer>" if text_layer.strip() else "",
            figure_note=prep["figure_note"],
        )
        reply = await ctx.run_node(ocr_checker, node_input=user_message(await _page_image(ctx, n, prep["mime"]), check_prompt),
                                   run_id=f"ocrcheck-p{n}")
        _ok, fixes, whole = parse_ocr_fixes(reply_text(reply))
        corrected, missing = (whole, []) if whole else apply_fixes(markdown, fixes)
        if corrected != markdown:
            markdown, applied, held = guard(markdown, corrected, text_layer)
            work.update(markdown=markdown, changed=applied, open=held)
        if missing:
            work["open"] = work.get("open", []) + [f"“{read}” → “{printed}”? (not found in the reading)" for read, printed in missing]
    await save_json(ctx, f"ocr-p{n}-work.json", work)
    yield Event(output={"page": n})


def note(report: dict) -> str:
    """How a page went, for the chat."""
    if report.get("cached"):
        return "reused from the earlier run"
    if report.get("hard"):
        text = (f"hard to read: the two readings differ in {report['disagreements']} places; nothing changed, they're "
                "listed for you")
    elif report.get("readers") == 2:
        n, changed = report.get("disagreements", 0), len(report.get("issues") or [])
        settled = report.get("settled", 0)
        text = ("two readings agree" if not n else
                f"two readings differ in {n} place{'s' if n != 1 else ''}: the OCR check settled {settled}"
                + (f" ({changed} changed)" if changed else ""))
    elif report.get("checked") == "text layer":
        text = "matches the PDF's text layer (no second check needed)"
    else:
        text = "verified" if report["ok"] else f"checker fixed {len(report['issues'])} issue(s)"
    if report.get("suggestions") and not report.get("hard"):
        k = len(report["suggestions"])
        text += f"; {k} possible misreading{'s' if k != 1 else ''} to check (not changed)"
    if report["figures"]:
        text += f"; {report['figures']} figure{'s' if report['figures'] != 1 else ''} kept ({report['figure_source']})"
    if k := len(report.get("figures_as_text") or []):
        text += f"; {k} region{'s' if k != 1 else ''} taken for a picture read as text"
    return text


@node(name="page_finish", rerun_on_resume=True)
async def finish(ctx: Context, node_input: Any):
    n = node_input["page"]
    if node_input.get("ready"):
        result = await load_json(ctx, f"ocr-p{n}.json")
        report = {**result["report"], "cached": bool(node_input.get("cached"))}
    else:
        prep, work = await load_json(ctx, f"ocr-p{n}-prep.json"), await load_json(ctx, f"ocr-p{n}-work.json")
        report = dict(prep["report"])
        markdown = work["markdown"]
        changed = prep.get("figure_changes", []) + work.get("changed", [])
        listed = prep.get("figure_notes", []) + work.get("open", [])
        report.update(readers=2 if prep["two"] else 1, disagreements=work.get("disagreements", 0))
        if changed:
            report.update(ok=False, issues=report["issues"] + changed)
        if listed:
            report["suggestions"] = listed
        for key in ("hard", "checked", "agreement", "settled"):
            if key in work:
                report[key] = work[key]
        meta = {}
        for i, f in enumerate(prep["kept"], start=1):
            markdown = place_figure_marker(markdown, i, f["anchor"])
            name = f"figure-p{n}-{i}.png"
            await ctx.save_artifact(name, types.Part.from_bytes(data=await load_bytes(ctx, f"figcand-p{n}-{f['cand']}.png"),
                                                                mime_type="image/png"))
            meta[str(i)] = {"image": name, "text": f["legend"]}
        await save_json(ctx, f"ocr-p{n}.json", {"sig": prep["sig"], "markdown": markdown, "report": report, "meta": meta})
    done = int(ctx.state.get("doc:ocr_done") or 0) + 1
    total = int(ctx.state.get("doc:pages") or done)
    yield say(f"OCR page {n}: {note(report)}",
              state={"doc:ocr_done": done, **progress_state("ocr", min(done, total), total, f"OCR page {min(done, total)}/{total}")})
    yield Event(output={"page": n, "cached": bool(node_input.get("cached"))})


page = Workflow(name="page", edges=[
    (START, prepare),
    (prepare, {"read": figures, "done": finish}),
    (figures, (first, second_reading)),
    ((first, second_reading), read),
    (read, compare_readings),
    (compare_readings, {"disagree": arbitrate_page, "single": check, "done": finish}),
    (arbitrate_page, finish),
    (check, finish),
])

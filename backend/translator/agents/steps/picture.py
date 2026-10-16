"""The text in one picture — a figure cut from a page, or a picture in a Word, PowerPoint or Excel file — read as its
own small graph: two models read it at once, and where they differ the OCR check model settles it.

    START → start ─(read)───→ first ∥ second → read → settle → done
                  └(cached)─────────────────────────────────→ done

Input: {"key", "image" (the artifact holding it), "label" (image | chart | seal | picture)}. Output: {"key",
"kind" (picture | text), "text", "changed", "open", "readers"} — `open`: where the two readings differ and the
arbiter couldn't settle it, for the person to check. Each result is cached per document (by key and signature), so
a retry doesn't read the picture again."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from google.adk import Context, Event
from google.adk.workflow import START, JoinNode, Workflow, node
from google.genai import types

from ...config import get_settings
from ...document.pages import enlarged
from ...models import routing
from ...models.replies import parse_figure_reply
from ...ocr import compare, second
from .. import prompts
from ..common import reply_text, user_message
from ..workers import figure_reader, figure_second_reader
from .settle import arbitrate, decide, load_bytes, load_json, save_json

PICTURE_CACHE_VERSION = 2  # 2: two readings, settled by the OCR check model


def signature(state, label: str, two: bool) -> str:
    """What a picture's reading depends on, besides the picture: the models (and levels), the prompts, the sizes."""
    s = get_settings()
    h = hashlib.sha1(f"{label}/{two}/{PICTURE_CACHE_VERSION}".encode())
    for step in ("ocr", "ocr_second", "ocr_check") if two else ("ocr",):
        m = routing.resolve(step, state)
        h.update(f"{m.model_name}/{m.effort}".encode())
    for part in (prompts.FIGURE_CHECK, prompts.ARBITRATE if two else "", s.ocr_min_picture_px, s.ocr_max_upscale):
        h.update(str(part).encode())
    return h.hexdigest()


async def _image(ctx: Context, name: str) -> types.Part:
    s = get_settings()
    png = await asyncio.to_thread(enlarged, await load_bytes(ctx, name), s.ocr_min_picture_px, s.ocr_max_upscale,
                                  s.ocr_max_image_px)
    return types.Part.from_bytes(data=png, mime_type="image/png")


@node(name="picture_start", rerun_on_resume=True)
async def start(ctx: Context, node_input: Any):
    two = second.enabled(ctx.state)
    sig = signature(ctx.state, node_input["label"], two)
    cached = await load_json(ctx, f"picture-{node_input['key']}.json")
    if cached and cached.get("sig") == sig:
        yield Event(output={**cached["result"], "key": node_input["key"], "cached": True}, route="cached")
        return
    yield Event(output={**node_input, "sig": sig, "two": two}, route="read")


async def _look(ctx: Context, agent, item: dict, run_id: str) -> dict:
    out = await ctx.run_node(agent, node_input=user_message(await _image(ctx, item["image"]),
                                                            prompts.FIGURE_CHECK.format(label=item["label"])), run_id=run_id)
    kind, text = parse_figure_reply(reply_text(out))
    return {**item, "kind": kind, "text": text}


@node(name="picture_first", rerun_on_resume=True)
async def first(ctx: Context, node_input: Any):
    yield Event(output=await _look(ctx, figure_reader, node_input, f"look-{node_input['key'][:16]}"))


@node(name="picture_second", rerun_on_resume=True)
async def second_reading(ctx: Context, node_input: Any):
    if not node_input["two"]:
        yield Event(output={"skipped": True})
        return
    yield Event(output=await _look(ctx, figure_second_reader, node_input, f"look2-{node_input['key'][:16]}"))


read = JoinNode(name="picture_read")


@node(name="picture_settle", rerun_on_resume=True)
async def settle(ctx: Context, node_input: Any):
    a, b = node_input["picture_first"], node_input["picture_second"]
    text, changed, left, readers = a["text"], [], [], 1
    kind = a["kind"]
    if not b.get("skipped"):
        readers = 2
        if "picture" in (a["kind"], b["kind"]):  # as a picture, nothing is lost: its text is kept as its legend
            kind = "picture"
        found = compare.disputes(a["text"], b["text"])
        if found:
            answers = await arbitrate(ctx, await _image(ctx, a["image"]), found, "picture", f"settle-{a['key'][:16]}")
            settled = decide(a["text"], found, answers)
            text, changed, left = settled.text, settled.changed, settled.open
    result = {"kind": kind, "text": text, "changed": changed, "open": left, "readers": readers}
    await save_json(ctx, f"picture-{a['key']}.json", {"sig": a["sig"], "result": result})
    yield Event(output={**result, "key": a["key"]})


@node(name="picture_done", rerun_on_resume=True)
async def done(ctx: Context, node_input: Any):
    yield Event(output=node_input)


picture = Workflow(name="picture", edges=[
    (START, start),
    (start, {"cached": done, "read": (first, second_reading)}),
    ((first, second_reading), read),
    (read, settle),
    (settle, done),
])

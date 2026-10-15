"""Office files: the text is read from the file itself (no OCR, no source check): office/. The text inside the
file's pictures is read by the OCR model (as for a PDF's figures) and translated like a figure's legend."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from google.adk import Context, Event
from google.adk.workflow import node
from google.genai import types

from ... import office
from ...config import get_settings
from ...document import state as st
from ...models import routing
from ...models.replies import parse_figure_reply
from ...office import pictures
from ...office.common import has_letters
from .. import prompts
from ..common import progress_state, reply_text, run_bounded, say, user_message
from ..workers import figure_reader
from .read import source_format

PICTURE_CACHE_VERSION = 1


@node
async def route_source(ctx: Context, node_input: Any):
    """PDFs, images and text files are read with OCR (or as they are); Word, PowerPoint and Excel files are extracted."""
    fmt = source_format(ctx.state.get("doc:filename") or "")
    yield Event(output={"format": fmt}, route="extract" if fmt in office.LABEL else "ocr")


def _summary(info: dict, n: int, label: str) -> str:
    parts = [f"Read the {label}: {n} segment{'s' if n != 1 else ''} in {len(info['page_labels'])} {info['unit']}"
             f"{'s' if len(info['page_labels']) != 1 else ''}"]
    if tracked := info.get("tracked_changes"):
        parts.append(f"{tracked} tracked change{'s' if tracked != 1 else ''} accepted")
    if skipped := info.get("not_translated"):
        parts.append("not translated: " + ", ".join(f"{v} {k}" if k != "sheet names" else f"{v} sheet name{'s' if v != 1 else ''}"
                                                   for k, v in skipped.items()))
    return "; ".join(parts)


def _pictures_line(read: int, empty: int, info: dict, reason: str | None) -> str | None:
    found = (info.get("pictures") or {}).get("found", 0)
    alts = (info.get("pictures") or {}).get("alt_texts", 0)
    alt_note = (f" The alt text of {alts} picture{'s' if alts != 1 else ''} (what its author wrote for it) is translated too."
                if alts else "")
    if reason:
        return (f"The text in the file's {found} picture{'s' if found != 1 else ''} wasn't read: {reason}.{alt_note}"
                if found else None)
    if not read:
        return alt_note.strip() or None
    line = f"Read the text in {read} picture{'s' if read != 1 else ''}"
    if empty:
        line += f" ({empty} had none)"
    left = {k: v for k, v in (info.get("pictures") or {}).get("skipped", {}).items() if k in ("small", "decorative")}
    if left:
        line += "; left alone: " + ", ".join(f"{v} {'small' if k == 'small' else 'decorative'}" for k, v in left.items())
    return line + f". {'Their' if read != 1 else 'Its'} English goes into the picture's alt text" + {
        "docx": ", and a caption under it.", "pptx": ", and the slide's notes.", "xlsx": "."}.get(info.get("format"), ".") + alt_note


def _signature(sha: str, state) -> str:
    """What a picture's reading depends on: the picture, the reading model (and its level), the prompt."""
    ocr = routing.resolve("ocr", state)
    h = hashlib.sha1(sha.encode())
    for part in (f"{ocr.model_name}/{ocr.effort}", prompts.FIGURE_CHECK, PICTURE_CACHE_VERSION):
        h.update(str(part).encode())
    return h.hexdigest()


async def _read_picture(ctx: Context, sha: str, png: bytes) -> str:
    """The text the OCR model reads in a picture (cached per document, so a retry doesn't read it again)."""
    name, sig = f"picture-{sha}.json", _signature(sha, ctx.state)
    cached = await ctx.load_artifact(name)
    if cached is not None and cached.text:
        try:
            data = json.loads(cached.text)
            if data.get("sig") == sig:
                return data.get("text", "")
        except ValueError:
            pass
    crop = types.Part.from_bytes(data=png, mime_type="image/png")
    out = await ctx.run_node(figure_reader, node_input=user_message(crop, prompts.FIGURE_CHECK.format(label="picture")),
                             run_id=f"picture-{sha[:12]}")
    _kind, text = parse_figure_reply(reply_text(out))  # a picture or a block of text: either way its text is the legend
    await ctx.save_artifact(name, types.Part(text=json.dumps({"sig": sig, "text": text}, ensure_ascii=False)))
    return text


def _why_not(state) -> str | None:
    """Why the pictures can't be read (None: they can)."""
    if get_settings().office_pictures == "off":
        return "reading pictures is turned off (OFFICE_PICTURES=off)"
    if not routing.resolve("ocr", state).vision:
        return "the reading model doesn't read images"
    return None


@node(rerun_on_resume=True)
async def extract(ctx: Context, node_input: Any):
    settings = get_settings()
    filename = ctx.state.get("doc:filename") or "document.docx"
    fmt = office.detect(filename)
    artifact = await ctx.load_artifact(ctx.state.get("doc:source_artifact"))
    if artifact is None or artifact.inline_data is None:
        raise RuntimeError("Source document artifact is missing.")
    label = office.LABEL[fmt]
    yield Event(state=progress_state("extract", 0, 1, f"Reading the {label}…", "reading"))
    reason = _why_not(ctx.state)
    segments, info = await asyncio.to_thread(
        office.extract, artifact.inline_data.data, fmt, read_pictures=reason is None,
        min_cm=settings.office_picture_min_cm, max_pictures=settings.office_picture_max)
    files: dict[str, pictures.Picture] = info.pop("picture_files", {})
    if reason is not None and info["pictures"]["found"]:
        info["pictures"]["not_read"] = reason
    figures = [s for s in segments if s["kind"] == "figure"]
    read = empty = 0
    if figures:
        yield Event(state=progress_state("extract", 0, 1, f"Reading the text in {len(figures)} "
                                         f"picture{'s' if len(figures) != 1 else ''}…", "reading"))
        pngs = dict(zip(files, await asyncio.gather(*(asyncio.to_thread(pictures.to_png, p.blob) for p in files.values())),
                        strict=True))
        unreadable = {sha for sha, png in pngs.items() if png is None}
        todo = [(sha, png) for sha, png in pngs.items() if png is not None]
        texts: dict[str, str] = {}
        async for i, text in run_bounded([lambda s=s, p=p: _read_picture(ctx, s, p) for s, p in todo], settings.max_concurrency):
            texts[todo[i][0]] = text
        for seg in figures:
            if seg["sha1"] in unreadable:
                continue
            await ctx.save_artifact(seg["image"], types.Part.from_bytes(data=pngs[seg["sha1"]], mime_type="image/png"))
            text = (texts.get(seg["sha1"]) or "").strip()
            seg["source"] = text
            seg["translatable"] = has_letters(text)
            seg["target"] = None if seg["translatable"] else text
            read += 1
            empty += not text
        if unreadable:
            segments = [s for s in segments if s.get("sha1") not in unreadable]
            info["not_translated"] = {**info.get("not_translated", {}), "pictures that couldn't be opened": len(unreadable)}
    if not segments:
        raise RuntimeError(f"No text or pictures found in the {label}.")
    delta: dict[str, Any] = {st.seg_key(s["id"]): st.normalize(s) for s in segments}
    delta.update({"doc:seg_ids": [s["id"] for s in segments], "doc:pages": len(info["page_labels"]), "doc:unit": info["unit"],
                  "doc:page_labels": info["page_labels"], "doc:office": info, "doc:ocr_report": [],
                  **progress_state("extract", 1, 1, "Read the file")})
    yield say(_summary(info, len(segments), label), state=delta)
    if line := _pictures_line(read, empty, info, reason):
        yield say(line)
    if info.get("tracked_changes"):
        yield say(f"**Note:** this {label} had {info['tracked_changes']} tracked change(s). I translated the text as if they "
                  "were all accepted, and the translated file has them accepted too.", kind="assistant")
    yield Event(output={"segments": len(segments)})

"""Office files: the text is read from the file itself (no OCR, no source check): office/. The text inside the
file's pictures is read by the picture graph (agents/steps/picture.py: two models, as for a PDF's figures) and
translated like a figure's legend.

    extract → read_pictures (the picture graph, for each distinct picture in parallel) → finish_extract"""

from __future__ import annotations

import asyncio
from typing import Any

from google.adk import Context, Event
from google.adk.workflow import node
from google.genai import types

from ... import office
from ...config import get_settings
from ...document import state as st
from ...models import routing
from ...office import pictures
from ...office.common import has_letters
from ..common import progress_state, say
from .picture import picture
from .read import source_format


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


def _why_not(state) -> str | None:
    """Why the pictures can't be read (None: they can)."""
    if get_settings().office_pictures == "off":
        return "reading pictures is turned off (OFFICE_PICTURES=off)"
    if not routing.resolve("ocr", state).vision:
        return "the reading model doesn't read images"
    return None


@node(rerun_on_resume=True)
async def extract(ctx: Context, node_input: Any):
    """The file's own text → segments; its pictures (one per distinct image) go to `read_pictures`."""
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
    items: list[dict] = []
    if figures:
        yield Event(state=progress_state("extract", 0, 1, f"Reading the text in {len(figures)} "
                                         f"picture{'s' if len(figures) != 1 else ''}…", "reading"))
        pngs = dict(zip(files, await asyncio.gather(*(asyncio.to_thread(pictures.to_png, p.blob) for p in files.values())),
                        strict=True))
        unreadable = {sha for sha, png in pngs.items() if png is None}
        for seg in figures:
            if seg["sha1"] in unreadable:
                continue
            await ctx.save_artifact(seg["image"], types.Part.from_bytes(data=pngs[seg["sha1"]], mime_type="image/png"))
            if seg["sha1"] not in {i["key"] for i in items}:  # a picture used twice is read once
                items.append({"key": seg["sha1"], "image": seg["image"], "label": "picture"})
        if unreadable:
            segments = [s for s in segments if s.get("sha1") not in unreadable]
            info["not_translated"] = {**info.get("not_translated", {}), "pictures that couldn't be opened": len(unreadable)}
    if not segments:
        raise RuntimeError(f"No text or pictures found in the {label}.")
    delta: dict[str, Any] = {st.seg_key(s["id"]): st.normalize(s) for s in segments}
    delta.update({"doc:seg_ids": [s["id"] for s in segments], "doc:pages": len(info["page_labels"]), "doc:unit": info["unit"],
                  "doc:page_labels": info["page_labels"], "doc:office": {**info, "pictures_not_read": reason},
                  "doc:ocr_report": [], **progress_state("extract", 1, 1, "Read the file")})
    yield say(_summary(info, len(segments), label), state=delta)
    if info.get("tracked_changes"):
        yield say(f"**Note:** this {label} had {info['tracked_changes']} tracked change(s). I translated the text as if they "
                  "were all accepted, and the translated file has them accepted too.", kind="assistant")
    yield Event(output=items)


# Each distinct picture by the picture graph: two models read it, the OCR check model settles where they differ.
read_pictures = node(picture, name="read_pictures", parallel_worker=True,
                     max_parallel_workers=max(1, get_settings().max_concurrency))


@node(rerun_on_resume=True)
async def finish_extract(ctx: Context, node_input: Any):
    """The text read in each picture → its segments (the legend translated into its alt text, caption or notes);
    where the two readings differ and nothing settled it, the segment says so (a Quality warning)."""
    results = {r["key"]: r for r in node_input or [] if r}
    info = dict(ctx.state.get("doc:office") or {})
    reason = info.pop("pictures_not_read", None)
    delta: dict[str, Any] = {}
    read = empty = 0
    for sid in ctx.state.get("doc:seg_ids") or []:
        seg = dict(ctx.state.get(st.seg_key(sid)) or {})
        if seg.get("kind") != "figure" or seg.get("sha1") not in results:
            continue
        r = results[seg["sha1"]]
        text = (r.get("text") or "").strip()
        seg["source"] = text
        seg["translatable"] = has_letters(text)
        seg["target"] = None if seg["translatable"] else text
        seg["reading_flags"] = list(r.get("open") or [])
        delta[st.seg_key(sid)] = st.normalize(seg)
        read += 1
        empty += not text
    delta["doc:office"] = info  # without the note for this step
    yield Event(state=delta)
    if line := _pictures_line(read, empty, info, reason):
        flagged = sum(1 for k in delta if delta[k].get("reading_flags"))
        if flagged:
            line += (f" The two readings of {flagged} picture{'s' if flagged != 1 else ''} still differ: "
                     f"see **Quality** to check {'them' if flagged != 1 else 'it'}.")
        yield say(line)
    yield Event(output={"pictures": read})

"""The source check before translating: accept or reject page fixes, then continue to translation."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from google.genai import types

from ...agents import prompts
from ...agents.reread import read_page_again
from ...document import source_check, versions
from ...document import state as st
from ...document.pages import IMAGE_EXTS, guess_mime, render_page
from ..services import (
    REQUEST_INPUT_TOOL,
    ensure_source_check,
    figure_bytes,
    ingest_runner,
    load_session,
    open_interrupt,
    session_service,
    source_bytes,
    start_run,
)

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/sessions/{session_id}/source/fixes/{page}/accept")
async def accept_source_fix(session_id: str, page: int) -> dict[str, Any]:
    """Apply a page fix the chat proposed during the source check: the page is split into segments again."""
    session = await load_session(session_id)
    ensure_source_check(session)
    fixes = dict(session.state.get(source_check.FIXES) or {})
    fix = fixes.pop(str(page), None)
    if fix is None:
        raise HTTPException(404, f"No proposed fix for page {page}.")
    delta = source_check.resegment(session.state, page, fix["after"])
    delta[source_check.FIXES] = fixes
    await session_service.append_event(session, versions.activity_event(f"Source of page {page} fixed: {fix['reason'] or 'accepted'}", delta))
    return {"ok": True, "segments": sum(1 for k in delta if k.startswith(st.SEG))}


@router.post("/api/sessions/{session_id}/source/fixes/{page}/reject")
async def reject_source_fix(session_id: str, page: int) -> dict[str, bool]:
    session = await load_session(session_id)
    ensure_source_check(session)
    fixes = dict(session.state.get(source_check.FIXES) or {})
    if fixes.pop(str(page), None) is None:
        raise HTTPException(404, f"No proposed fix for page {page}.")
    await session_service.append_event(session, versions.activity_event(f"Fix for page {page} rejected", {source_check.FIXES: fixes}))
    return {"ok": True}


@router.post("/api/sessions/{session_id}/source/continue")
async def continue_after_source_check(session_id: str) -> dict[str, bool]:
    """The source is right: resume the workflow, which analyses and translates it."""
    session = await load_session(session_id)
    ensure_source_check(session)
    interrupt_id = open_interrupt(session)
    if not interrupt_id:
        raise HTTPException(409, "The pipeline is not paused.")
    response = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=interrupt_id, name=REQUEST_INPUT_TOOL, response={"result": {"continue": True}}))])
    start_run(session_id, ingest_runner, response, streaming=False)
    return {"ok": True}


@router.post("/api/sessions/{session_id}/source/figures/{page}/{n}/text")
async def figure_is_text(session_id: str, page: int, n: int) -> dict[str, Any]:
    """"This is text, not a picture": the page is read again with that region transcribed in its place, and the
    result is proposed as a page fix (accept or reject it like any other). If the reading fails, the text the OCR
    read inside the picture is put in its place instead."""
    session = await load_session(session_id)
    ensure_source_check(session)
    seg = next((s for s in source_check.page_segments(session.state, page)
                if s["kind"] == "figure" and source_check.figure_number(s) == n), None)
    if seg is None:
        raise HTTPException(404, f"No picture {n} on page {page}.")
    previous = source_check.page_markdown(session.state, page)
    marker = re.compile(rf"^[ \t]*\[\[\s*FIGURE\s+{n}\s*\]\][ \t]*$", re.M | re.I)
    data, filename = await source_bytes(session)
    png = await asyncio.to_thread(render_page, data, filename, page)
    markdown, reason = "", ""
    if png is not None:
        is_upload = any(filename.lower().endswith(ext) for ext in IMAGE_EXTS)
        image = types.Part.from_bytes(data=png, mime_type=guess_mime(filename) if is_upload else "image/png")
        crop = types.Part.from_bytes(data=await figure_bytes(session_id, seg["image"]), mime_type="image/png")
        try:
            markdown = await read_page_again(image, page, prompts.FIGURE_IS_TEXT.format(n=n), previous, extra=[crop],
                                             state=session.state)
            reason = f"Picture {n} is text: the page read again with its text in place"
        except Exception:
            log.exception("reading page %s again failed", page)
    if not markdown.strip() or marker.search(markdown):
        legend = (seg.get("source") or "").strip()
        if not legend:
            raise HTTPException(502, "The page couldn't be read again, and no text was read inside the picture.")
        markdown, reason = marker.sub(lambda _: legend, previous), f"Picture {n} is text: the text read inside it put in its place"
    session = await load_session(session_id)  # fresh: the reading took a while
    ensure_source_check(session)
    fix = source_check.stage(session.state, page, markdown, reason, "figure")
    if fix is None:
        return {"status": "unchanged"}
    fixes = {**(session.state.get(source_check.FIXES) or {}), str(page): fix}
    await session_service.append_event(
        session, versions.activity_event(f"Proposed for page {page}: picture {n} is text", {source_check.FIXES: fixes}))
    return {"status": "proposed", "fix": fix}

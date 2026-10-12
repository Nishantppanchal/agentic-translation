"""The source check before translating: accept or reject page fixes, then continue to translation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from google.genai import types

from ...document import source_check, versions
from ...document import state as st
from ..services import (
    REQUEST_INPUT_TOOL,
    ensure_source_check,
    ingest_runner,
    load_session,
    open_interrupt,
    session_service,
    start_run,
)

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

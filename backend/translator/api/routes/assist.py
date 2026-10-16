"""AI assist in the chat (agents/assist.py): suggested next prompts, Tab completions, and the translation summary for the client.
Suggestions and completions are only offered when Settings → AI assist is on; none of them changes the document
(the notes are stored with it, while no run is working on it)."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import app_settings
from ...agents import assist
from ...document import state as st
from ...models.llm import error_text
from ..services import load_session, runs, set_state

log = logging.getLogger(__name__)
router = APIRouter()

MIN_TYPED = 4  # characters typed before a completion is worth asking for


class TypedIn(BaseModel):
    text: str = Field("", max_length=4000)


@router.post("/api/sessions/{session_id}/assist/suggestions")
async def suggest(session_id: str) -> dict[str, Any]:
    """Up to 3 next requests for the chat, once the document is ready."""
    session = await load_session(session_id)
    if not app_settings.load().assist:
        return {"suggestions": [], "disabled": True}
    if session.state.get("doc:status") != "ready" or not st.segment_ids(session.state):
        return {"suggestions": [], "cached": False}
    try:
        found, cached = await assist.suggestions(session_id, session.state, session.events)
    except Exception as exc:  # noqa: BLE001 — suggestions are a nicety: the chat works without them
        log.warning("suggestions for %s failed: %s", session_id, error_text(exc))
        return {"suggestions": [], "cached": False, "error": error_text(exc)}
    return {"suggestions": found, "cached": cached}


@router.post("/api/sessions/{session_id}/assist/complete")
async def complete(session_id: str, body: TypedIn) -> dict[str, str]:
    """The next few words of the chat message being typed ("" when there is nothing good to add)."""
    session = await load_session(session_id)
    if not app_settings.load().assist or len(body.text.strip()) < MIN_TYPED:
        return {"completion": ""}
    try:
        return {"completion": await assist.complete(session_id, session.state, session.events, body.text)}
    except Exception as exc:  # noqa: BLE001 — as above
        log.warning("completion for %s failed: %s", session_id, error_text(exc))
        return {"completion": ""}


@router.post("/api/sessions/{session_id}/assist/notes")
async def client_notes(session_id: str) -> dict[str, Any]:
    """The translation summary for the client (Markdown): decisions, assumptions, open queries, what wasn't translated, quality.
    Kept with the document (export "notes") unless the agents started working on it meanwhile."""
    session = await load_session(session_id)
    if not st.segment_ids(session.state):
        raise HTTPException(409, "There is no translation to write notes about yet.")
    try:
        text = await assist.client_notes(session_id, session.state)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Couldn't write the notes: {error_text(exc)}") from exc
    if not text:
        raise HTTPException(502, "The model returned no notes; try again.")
    versions = session.state.get("doc:versions") or []
    notes = {"text": text, "version": versions[-1]["version"] if versions else None, "at": time.time()}
    stored = not runs.is_running(session_id)
    if stored:
        await set_state(session_id, {"doc:client_notes": notes})
    return {**notes, "stored": stored}

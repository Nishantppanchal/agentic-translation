"""What the routes share: the session and artifact stores, the runners, the run manager, and helpers that
load a document, describe it for the UI and start runs."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException
from google.adk import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.apps import App
from google.adk.artifacts import FileArtifactService
from google.adk.events import Event, EventActions
from google.adk.sessions import DatabaseSessionService, Session
from google.genai import types

from .. import projects, references
from ..agents.editor import editor_agent
from ..agents.pipeline import ingest_workflow
from ..agents.tasks import ops_workflow
from ..config import TARGET_LANG, get_settings
from ..document import comments, source_check
from ..models import routing
from ..document import state as st
from .runs import Emit, RunManager
from .timeline import pending_interrupt, stream_events

APP_NAME = "translator"
settings = get_settings()
USER = settings.user_id
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings.data_dir.mkdir(parents=True, exist_ok=True)

session_service = DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{(settings.data_dir / 'sessions.db').resolve()}")
artifact_service = FileArtifactService(root_dir=str((settings.data_dir / "artifacts").resolve()))


def _runner(agent) -> Runner:
    return Runner(app=App(name=APP_NAME, root_agent=agent), session_service=session_service, artifact_service=artifact_service)


# Three entry points over the same documents: the pipeline, the chat editor, and tasks on a finished document
# (rewrites, consistency fixes, LQA).
ingest_runner = _runner(ingest_workflow)
editor_runner = _runner(editor_agent)
ops_runner = _runner(ops_workflow)
runs = RunManager(max_heavy=settings.max_parallel_runs)


async def load_session(session_id: str) -> Session:
    session = await session_service.get_session(app_name=APP_NAME, user_id=USER, session_id=session_id)
    if not session:
        raise HTTPException(404, "Document not found")
    return session


def summary(session: Session) -> dict[str, Any]:
    s = session.state
    pid = s.get("doc:project_id")
    return {
        "project_id": pid,
        "project_name": projects.get_store().project_name(pid) if pid else None,
        "id": session.id,
        "filename": s.get("doc:filename", "document"),
        "source_lang": s.get("doc:detected_lang") or s.get("doc:source_lang", "auto-detect"),
        "target_lang": s.get("doc:target_lang", TARGET_LANG),
        "status": s.get("doc:status", "uploaded"),
        "pages": s.get("doc:pages", 0),
        "updated_at": session.last_update_time,
        "progress": s.get("doc:progress") if runs.is_running(session.id) else None,
        "open_questions": len(st.open_questions(s)),
        "running": runs.is_running(session.id),
        "counts": st.status_counts(s),
        "format": s.get("doc:format"),
        "title": s.get("doc:title") or None,  # an English title from the analysis
        "abstract": s.get("doc:abstract") or None,  # and a two-sentence summary of what it says
    }


def document_view(session: Session) -> dict[str, Any]:
    s = session.state
    placed, orphans = comments.place(s)
    return {
        "segments": [{**st.normalize(x), "comments": placed.get(x["id"], [])} for x in st.get_segments(s)],
        "orphan_comments": orphans,
        "human_dirty": s.get("doc:human_dirty") or [],
        "glossary": s.get("doc:glossary") or {},
        "termbase": s.get("doc:termbase") or {},
        "brief": s.get("doc:brief") or "",
        "key_terms": s.get("doc:key_terms") or [],
        "source_fixes": s.get(source_check.FIXES) or {},
        "terms": document_terms(s),
        "tm_stats": s.get("doc:tm_stats"),
        "lqa": s.get("doc:lqa"),
        "format": s.get("doc:format"),
        "proposal": st.get_proposal(s),
        "questions": s.get("doc:questions") or [],
        "versions": s.get("doc:versions") or [],
        "ocr_report": s.get("doc:ocr_report") or [],
        "review_report": s.get("doc:review_report") or [],
        "settings": {"models": routing.choices(s), "dictionary": references.dictionary_status(s)},
        # Word / PowerPoint / Excel: what a "page" is (part, slide, sheet), their labels, what reading left out.
        "unit": s.get("doc:unit"),
        "page_labels": s.get("doc:page_labels"),
        "office": s.get("doc:office"),
        "title": s.get("doc:title") or None,
        "abstract": s.get("doc:abstract") or None,
        "client_notes": s.get("doc:client_notes"),
    }


def document_terms(state) -> list[dict]:
    """Project terms that occur in this document (for highlighting in the grid)."""
    pid = projects.project_id(state)
    if not pid:
        return []
    return projects.get_store().terms_in(pid, [x["source"] for x in st.get_segments(state) if x.get("source")])


async def set_state(session_id: str, delta: dict[str, Any]) -> None:
    """Apply a state change outside an agent run (recorded as a system event)."""
    session = await load_session(session_id)
    await session_service.append_event(session, Event(author="system", actions=EventActions(state_delta=delta)))


def start_run(session_id: str, runner: Runner, message: str | types.Content, streaming: bool) -> None:
    if isinstance(message, str):
        message = types.Content(role="user", parts=[types.Part(text=message)])
    run_config = RunConfig(streaming_mode=StreamingMode.SSE if streaming else StreamingMode.NONE)

    async def work(emit: Emit) -> None:
        partial: dict[str, str] = {}
        if runner is not ingest_runner:  # don't show the previous run's progress (e.g. "Assessed 2/2") meanwhile
            await set_state(session_id, {"doc:progress": None})
        try:
            async for ev in runner.run_async(
                user_id=USER, session_id=session_id, new_message=message, run_config=run_config, yield_user_message=True
            ):
                for payload in stream_events(ev, partial):
                    emit(payload)
        except Exception:
            if runner is ingest_runner:
                await set_state(session_id, {"doc:status": "error"})
            raise

    runs.start(session_id, work, heavy=runner is not editor_runner)


REQUEST_INPUT_TOOL = "adk_request_input"


def open_interrupt(session: Session) -> str | None:
    return pending_interrupt(session.events)


def ensure_idle(session: Session) -> None:
    if runs.is_running(session.id):
        raise HTTPException(409, "The agents are still working on this document.")
    if session.state.get("doc:status") == "awaiting_answers":
        raise HTTPException(409, "Answer (or skip) the open questions first so the pipeline can continue.")


async def source_bytes(session: Session) -> tuple[bytes, str]:
    part = await artifact_service.load_artifact(
        app_name=APP_NAME, user_id=USER, session_id=session.id, filename=session.state["doc:source_artifact"]
    )
    if not part or not part.inline_data:
        raise HTTPException(404, "Source document missing")
    return part.inline_data.data, session.state.get("doc:filename", "document.pdf")


async def editable_session(session_id: str) -> Session:
    session = await load_session(session_id)
    if runs.is_running(session_id):
        raise HTTPException(409, "The agents are working on this document; edit when they finish.")
    return session


def ensure_source_check(session: Session) -> None:
    if runs.is_running(session.id):
        raise HTTPException(409, "The agents are still working on this document.")
    if not source_check.in_review(session.state):
        raise HTTPException(409, "The document is not waiting for the source check.")


FIGURE_NAME = re.compile(r"^figure-p\d+-\d+\.png$")


async def figure_bytes(session_id: str, name: str) -> bytes:
    if not FIGURE_NAME.match(name):
        raise HTTPException(404, "Not a figure")
    part = await artifact_service.load_artifact(app_name=APP_NAME, user_id=USER, session_id=session_id, filename=name)
    if not part or not part.inline_data:
        raise HTTPException(404, "Figure not found")
    return part.inline_data.data

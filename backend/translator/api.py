"""FastAPI server: sessions, uploads, background agent runs and SSE streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from google.adk import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.apps import App
from google.adk.artifacts import FileArtifactService
from google.adk.events import Event, EventActions
from google.adk.sessions import DatabaseSessionService, Session
from google.genai import types
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import exports, layout, projects, proposals, qa, segments, usage, versions
from . import replace as rp
from . import state as st
from .agents.editor import editor_agent
from .agents.ops import ops_workflow
from .agents.pipeline import ingest_workflow, source_format
from .config import TARGET_LANG, get_settings
from .documents import SUPPORTED_EXTS, guess_mime, load_pages
from .downloads import content_disposition
from .filters import office, office_view, xliff
from .languages import LANGUAGES, lang_code, language_name
from .llm import model_name
from .project_routes import router as project_router
from .runs import Emit, RunManager
from .timeline import history, pending_interrupt, stream_events

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

APP_NAME = "translator"
settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)

session_service = DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{(settings.data_dir / 'sessions.db').resolve()}")
artifact_service = FileArtifactService(root_dir=str((settings.data_dir / "artifacts").resolve()))

# Two entry points over the same sessions: the ingest workflow and the chat editor.
ingest_runner = Runner(
    app=App(name=APP_NAME, root_agent=ingest_workflow),
    session_service=session_service,
    artifact_service=artifact_service,
)
editor_runner = Runner(
    app=App(name=APP_NAME, root_agent=editor_agent),
    session_service=session_service,
    artifact_service=artifact_service,
)
ops_runner = Runner(  # tasks on a finished document: rewrites, consistency fixes, LQA
    app=App(name=APP_NAME, root_agent=ops_workflow),
    session_service=session_service,
    artifact_service=artifact_service,
)
runs = RunManager(max_heavy=settings.max_parallel_runs)
USER = settings.user_id


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await ingest_runner.close()
    await editor_runner.close()
    await ops_runner.close()
    await layout.close()


app = FastAPI(title="Agentic Translator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(project_router)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _session(session_id: str) -> Session:
    session = await session_service.get_session(app_name=APP_NAME, user_id=USER, session_id=session_id)
    if not session:
        raise HTTPException(404, "Document not found")
    return session


def _summary(session: Session) -> dict[str, Any]:
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
    }


def _document(session: Session) -> dict[str, Any]:
    s = session.state
    return {
        "segments": [st.normalize(x) for x in st.get_segments(s)],
        "human_dirty": s.get("doc:human_dirty") or [],
        "glossary": s.get("doc:glossary") or {},
        "termbase": s.get("doc:termbase") or {},
        "brief": s.get("doc:brief") or "",
        "key_terms": s.get("doc:key_terms") or [],
        "terms": _document_terms(s),
        "tm_stats": s.get("doc:tm_stats"),
        "lqa": s.get("doc:lqa"),
        "format": s.get("doc:format"),
        "proposal": st.get_proposal(s),
        "questions": s.get("doc:questions") or [],
        "versions": s.get("doc:versions") or [],
        "ocr_report": s.get("doc:ocr_report") or [],
        "review_report": s.get("doc:review_report") or [],
    }


def _document_terms(state) -> list[dict]:
    """Project terms that occur in this document (for highlighting in the grid)."""
    pid = projects.project_id(state)
    if not pid:
        return []
    return projects.get_store().terms_in(pid, [x["source"] for x in st.get_segments(state) if x.get("source")])


async def _set_state(session_id: str, delta: dict[str, Any]) -> None:
    """Apply a state change outside an agent run (recorded as a system event)."""
    session = await _session(session_id)
    await session_service.append_event(session, Event(author="system", actions=EventActions(state_delta=delta)))


def _start_run(session_id: str, runner: Runner, message: str | types.Content, streaming: bool) -> None:
    if isinstance(message, str):
        message = types.Content(role="user", parts=[types.Part(text=message)])
    run_config = RunConfig(streaming_mode=StreamingMode.SSE if streaming else StreamingMode.NONE)

    async def work(emit: Emit) -> None:
        partial: dict[str, str] = {}
        if runner is not ingest_runner:  # don't show the previous run's progress (e.g. "Assessed 2/2") meanwhile
            await _set_state(session_id, {"doc:progress": None})
        try:
            async for ev in runner.run_async(
                user_id=USER, session_id=session_id, new_message=message, run_config=run_config, yield_user_message=True
            ):
                for payload in stream_events(ev, partial):
                    emit(payload)
        except Exception:
            if runner is ingest_runner:
                await _set_state(session_id, {"doc:status": "error"})
            raise

    runs.start(session_id, work, heavy=runner is not editor_runner)


REQUEST_INPUT_TOOL = "adk_request_input"


def _pending_interrupt(session: Session) -> str | None:
    return pending_interrupt(session.events)


def _ensure_idle(session: Session) -> None:
    if runs.is_running(session.id):
        raise HTTPException(409, "The agents are still working on this document.")
    if session.state.get("doc:status") == "awaiting_answers":
        raise HTTPException(409, "Answer (or skip) the open questions first so the pipeline can continue.")


_page_cache: OrderedDict[tuple[str, int], bytes] = OrderedDict()


async def _source_bytes(session: Session) -> tuple[bytes, str]:
    part = await artifact_service.load_artifact(
        app_name=APP_NAME, user_id=USER, session_id=session.id, filename=session.state["doc:source_artifact"]
    )
    if not part or not part.inline_data:
        raise HTTPException(404, "Source document missing")
    return part.inline_data.data, session.state.get("doc:filename", "document.pdf")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@app.get("/api/config")
async def config() -> dict[str, Any]:
    roles = ["ocr", "ocr_check", "translate", "review", "editor", "lqa"]
    return {"models": {r: model_name(r) for r in roles}, "languages": LANGUAGES, "target_lang": TARGET_LANG}


@app.get("/api/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    listed = await session_service.list_sessions(app_name=APP_NAME, user_id=USER)
    out = []
    for s in listed.sessions:
        full = await session_service.get_session(app_name=APP_NAME, user_id=USER, session_id=s.id)
        if full:
            out.append(_summary(full))
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)


async def _create_document(filename: str, data: bytes, source_lang: str, pages: int, project: dict | None) -> Session:
    """One document = one session, with its own ingest run."""
    source_artifact = f"source{Path(filename).suffix.lower()}"
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER,
        state={
            "doc:filename": filename,
            "doc:mime": guess_mime(filename),
            "doc:source_artifact": source_artifact,
            "doc:source_lang": source_lang,
            "doc:target_lang": TARGET_LANG,
            "doc:status": "uploaded",
            "doc:pages": pages,
            "doc:progress": {"stage": "queued", "current": 0, "total": 0, "message": "Starting…"},
            "doc:seg_ids": [],
            "doc:glossary": {},
            "doc:questions": [],
            "doc:versions": [],
            "doc:ocr_report": [],
            "doc:review_report": [],
            **({"doc:project_id": project["id"]} if project else {}),
        },
    )
    if project:
        projects.get_store().attach(session.id, project["id"])
    await artifact_service.save_artifact(
        app_name=APP_NAME,
        user_id=USER,
        session_id=session.id,
        filename=source_artifact,
        artifact=types.Part.from_bytes(data=data, mime_type=guess_mime(filename)),
    )
    _start_run(session.id, ingest_runner, f"Translate {filename} into {TARGET_LANG}.", streaming=False)
    return session


@app.post("/api/sessions")
async def create_session(
    file: UploadFile = File(...),
    source_lang: str = Form("auto-detect"),
    project_id: str = Form(""),
) -> dict[str, Any]:
    """Upload a document to translate into English."""
    filename = Path(file.filename or "document").name
    project = projects.get_store().project(project_id) if project_id else None
    if project_id and not project:
        raise HTTPException(404, "Project not found")
    if project:  # a project fixes the source language
        source_lang = project["source_lang"] or source_lang
    if source_lang == TARGET_LANG:
        raise HTTPException(400, f"The document is already in {TARGET_LANG}.")
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(400, f"Unsupported file type {ext or '?'}. Use PDF, Word, PowerPoint, Excel, XLIFF, an image, TXT or MD.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    fmt = source_format(filename)
    try:
        if ext == ".pdf":
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                pages = doc.page_count
        elif fmt == "xliff":
            _, info = await asyncio.to_thread(xliff.extract, data)
            pages = info["pages"]
            if source_lang.startswith("auto") and info.get("src"):
                source_lang = language_name(info["src"]) or source_lang
        elif fmt in ("docx", "pptx", "xlsx"):
            pages = (await asyncio.to_thread(office.extract, data, fmt))[1]["pages"]
        else:
            pages = 1
    except Exception as exc:
        raise HTTPException(400, f"Could not read file: {exc}") from exc

    session = await _create_document(filename, data, source_lang, pages, project)
    return _summary(await _session(session.id))


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = await _session(session_id)
    return {"summary": _summary(session), "document": _document(session), "timeline": history(session.events)}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    runs.cancel(session_id)
    for key in await artifact_service.list_artifact_keys(app_name=APP_NAME, user_id=USER, session_id=session_id):
        await artifact_service.delete_artifact(app_name=APP_NAME, user_id=USER, session_id=session_id, filename=key)
    await session_service.delete_session(app_name=APP_NAME, user_id=USER, session_id=session_id)
    projects.get_store().detach(session_id)
    return {"ok": True}


class MessageIn(BaseModel):
    text: str


@app.post("/api/sessions/{session_id}/messages")
async def send_message(session_id: str, body: MessageIn) -> dict[str, bool]:
    session = await _session(session_id)
    _ensure_idle(session)
    if not session.state.get("doc:seg_ids"):
        raise HTTPException(409, "The document hasn't been processed yet.")
    await segments.flush_human_edits(session_service, artifact_service, session)
    _start_run(session_id, editor_runner, body.text.strip(), streaming=True)
    return {"ok": True}


class AnswerIn(BaseModel):
    answer: str | None = None  # an explanation of the meaning (older clients)
    target: str | None = None  # the English term to use
    note: str | None = None
    recommended: bool = False  # the recommendation, taken as it was


@app.post("/api/sessions/{session_id}/questions/{question_id}")
async def answer_question(session_id: str, question_id: str, body: AnswerIn) -> dict[str, bool]:
    session = await _session(session_id)
    _ensure_idle(session)
    questions = [dict(q) for q in session.state.get("doc:questions") or []]
    q = next((q for q in questions if q["id"] == question_id), None)
    if not q:
        raise HTTPException(404, "Question not found")
    answer = st.answer_of({"target": body.target, "note": body.note or body.answer, "recommended": body.recommended})
    if not answer:
        q["status"] = "dismissed"
        await _set_state(session_id, {"doc:questions": questions})
        return {"ok": True}
    q["answer_recommended"] = answer["recommended"]  # how the term is saved to the project when the edits are accepted
    await _set_state(session_id, {"doc:questions": questions})
    if answer["target"]:
        text = f'[Answer to {question_id}] "{q["term"]}": use "{answer["target"]}"' + (f' ({answer["note"]})' if answer["note"] else "")
    else:
        text = f'[Answer to {question_id}] "{q["term"]}": {answer["note"]}'
    await segments.flush_human_edits(session_service, artifact_service, session)
    _start_run(session_id, editor_runner, text, streaming=True)
    return {"ok": True}


class AcceptIn(BaseModel):
    changes: list[str] | None = None  # "segment_id|field" keys to apply; None = all
    choices: dict[str, int] | None = None  # change key → chosen alternative (default: the first)


@app.post("/api/sessions/{session_id}/proposal/accept")
async def accept_proposal(session_id: str, body: AcceptIn) -> dict[str, Any]:
    """Apply the editor's pending proposal (all, or the selected changes) as a new version."""
    session = await _session(session_id)
    if runs.is_running(session_id):
        raise HTTPException(409, "The agents are still working on this document.")
    await segments.flush_human_edits(session_service, artifact_service, session)
    try:
        return await proposals.accept(session_service, artifact_service, session, body.changes, body.choices)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sessions/{session_id}/proposal/reject")
async def reject_proposal(session_id: str) -> dict[str, Any]:
    session = await _session(session_id)
    if runs.is_running(session_id):
        raise HTTPException(409, "The agents are still working on this document.")
    try:
        return await proposals.reject(session_service, session)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


# ---- Segment grid: direct human edits ---------------------------------------- #


class SegmentEdit(BaseModel):
    target: str | None = None
    confirm: bool = False
    base_target: str | None = None  # the text the editor started from (stale-edit check)
    role: Literal["translator", "reviewer"] = "translator"  # what "confirm" means (confirmed vs reviewed)


async def _grid_session(session_id: str) -> Session:
    session = await _session(session_id)
    if runs.is_running(session_id):
        raise HTTPException(409, "The agents are working on this document; edit when they finish.")
    return session


@app.patch("/api/sessions/{session_id}/segments/{segment_id}")
async def edit_segment(session_id: str, segment_id: str, body: SegmentEdit) -> dict[str, Any]:
    session = await _grid_session(session_id)
    try:
        seg = await segments.edit_segment(
            session_service, session, segment_id, target=body.target, confirm=body.confirm,
            base_target=body.base_target, role=body.role,
        )
    except KeyError as exc:
        raise HTTPException(404, f"No segment {segment_id}") from exc
    except segments.EditConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"segment": seg, "human_dirty": session.state.get("doc:human_dirty") or [], "counts": st.status_counts(session.state)}


class LockIn(BaseModel):
    locked: bool


@app.post("/api/sessions/{session_id}/segments/{segment_id}/lock")
async def lock_segment(session_id: str, segment_id: str, body: LockIn) -> dict[str, Any]:
    session = await _grid_session(session_id)
    try:
        return {"segment": await segments.set_locked(session_service, session, segment_id, body.locked)}
    except KeyError as exc:
        raise HTTPException(404, f"No segment {segment_id}") from exc


class ConfirmIn(BaseModel):
    ids: list[str] | None = None  # None = translator: drafts the AI check passed · reviewer: all confirmed
    role: Literal["translator", "reviewer"] = "translator"


@app.get("/api/sessions/{session_id}/segments/{segment_id}/tm")
async def segment_tm(session_id: str, segment_id: str) -> dict[str, Any]:
    """Top translation-memory matches for one segment (101 = same source and same previous segment)."""
    session = await _session(session_id)
    pid = projects.project_id(session.state)
    order = [x for x in st.get_segments(session.state) if x.get("translatable", True)]
    i = next((i for i, x in enumerate(order) if x["id"] == segment_id), None)
    if i is None:
        raise HTTPException(404, f"No segment {segment_id}")
    if not pid:
        return {"matches": []}
    prev = order[i - 1]["source"] if i else ""
    return {"matches": await asyncio.to_thread(projects.get_store().lookup, pid, order[i]["source"], prev, 5)}


class CommentIn(BaseModel):
    text: str
    role: Literal["translator", "reviewer"] = "translator"


class CommentPatch(BaseModel):
    resolved: bool


@app.post("/api/sessions/{session_id}/segments/{segment_id}/comments")
async def add_comment(session_id: str, segment_id: str, body: CommentIn) -> dict[str, Any]:
    session = await _grid_session(session_id)
    try:
        return {"segment": await segments.add_comment(session_service, session, segment_id, body.text, body.role)}
    except KeyError as exc:
        raise HTTPException(404, f"No segment {segment_id}") from exc
    except segments.EditConflict as exc:
        raise HTTPException(400, str(exc)) from exc


@app.patch("/api/sessions/{session_id}/segments/{segment_id}/comments/{comment_id}")
async def resolve_comment(session_id: str, segment_id: str, comment_id: str, body: CommentPatch) -> dict[str, Any]:
    session = await _grid_session(session_id)
    try:
        return {"segment": await segments.update_comment(session_service, session, segment_id, comment_id, resolved=body.resolved)}
    except KeyError as exc:
        raise HTTPException(404, "Comment not found") from exc


@app.delete("/api/sessions/{session_id}/segments/{segment_id}/comments/{comment_id}")
async def delete_comment(session_id: str, segment_id: str, comment_id: str) -> dict[str, Any]:
    session = await _grid_session(session_id)
    try:
        return {"segment": await segments.update_comment(session_service, session, segment_id, comment_id, delete=True)}
    except KeyError as exc:
        raise HTTPException(404, "Comment not found") from exc


@app.post("/api/sessions/{session_id}/segments/confirm")
async def confirm_segments(session_id: str, body: ConfirmIn) -> dict[str, Any]:
    session = await _grid_session(session_id)
    try:
        confirmed = await segments.confirm_segments(session_service, session, body.ids, body.role)
    except segments.EditConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"confirmed": confirmed, "counts": st.status_counts(session.state)}


@app.post("/api/sessions/{session_id}/versions")
async def save_version(session_id: str) -> dict[str, Any]:
    """Save pending human edits as one version."""
    session = await _grid_session(session_id)
    return {"version": await segments.flush_human_edits(session_service, artifact_service, session)}


# ---- QA, find & replace, LQA -------------------------------------------------- #


@app.get("/api/sessions/{session_id}/qa")
async def get_qa(session_id: str) -> dict[str, Any]:
    """Automatic QA over the current translation (computed on request; ignored issues are marked)."""
    session = await _session(session_id)
    issues = await asyncio.to_thread(qa.document_qa, session.state)
    return {"issues": issues, "summary": qa.summary(issues), "checks": [{"id": c.id, "label": c.label} for c in qa.CHECKS]}


class IgnoreIn(BaseModel):
    ids: list[str]
    ignored: bool = True


@app.post("/api/sessions/{session_id}/qa/ignore")
async def ignore_qa(session_id: str, body: IgnoreIn) -> dict[str, Any]:
    """Ignore (or restore) QA issues. An issue comes back if its segment's text changes."""
    session = await _session(session_id)
    current = list(session.state.get("doc:qa_ignored") or [])
    ids = set(body.ids)
    updated = [*current, *(i for i in body.ids if i not in current)] if body.ignored else [i for i in current if i not in ids]
    await _set_state(session_id, {"doc:qa_ignored": updated[-2000:]})
    return {"ignored": len(updated)}


class ReplaceIn(BaseModel):
    find: str
    replace: str = ""
    regex: bool = False
    case: bool = False
    whole_word: bool = False
    scope: Literal["all", "unconfirmed"] = "all"
    ids: list[str] | None = None  # apply: only these segments (from the preview)


@app.post("/api/sessions/{session_id}/replace/preview")
async def replace_preview(session_id: str, body: ReplaceIn) -> dict[str, Any]:
    session = await _session(session_id)
    try:
        pattern = rp.compile_find(body.find, regex=body.regex, case=body.case, whole_word=body.whole_word)
        found, locked = rp.matches(st.get_segments(session.state), pattern, body.replace, regex=body.regex, scope=body.scope)
    except rp.ReplaceError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"matches": found, "locked": locked}


@app.post("/api/sessions/{session_id}/replace")
async def replace_apply(session_id: str, body: ReplaceIn) -> dict[str, Any]:
    """Apply find & replace as human edits, saved as one version."""
    session = await _grid_session(session_id)
    try:
        return await segments.replace_in_targets(
            session_service, artifact_service, session, body.find, body.replace, regex=body.regex, case=body.case,
            whole_word=body.whole_word, scope=body.scope, ids=body.ids,
        )
    except rp.ReplaceError as exc:
        raise HTTPException(400, str(exc)) from exc
    except segments.EditConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sessions/{session_id}/import/xliff")
async def import_xliff(session_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """A returned XLIFF 2.0 file → a proposal (nothing changes until you accept it) + a report."""
    session = await _grid_session(session_id)
    if st.get_proposal(session.state):
        raise HTTPException(409, "Accept or reject the pending proposal first.")
    s = session.state
    try:
        changes, report = await asyncio.to_thread(
            xliff.import_changes, await file.read(), [st.normalize(x) for x in st.get_segments(s)],
            src=lang_code(s.get("doc:detected_lang") or s.get("doc:source_lang")), tgt=lang_code(s.get("doc:target_lang")),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    name = Path(file.filename or "import.xlf").name
    skipped = {k: len(v) for k, v in report.items() if isinstance(v, list) and v}
    labels = {"unknown": "unknown units", "source_changed": "source changed", "locked": "locked", "kept_confirmed": "kept your confirmed",
              "codes": "codes broken"}
    text = f"Imported {name}: {report['changes']} change{'s' if report['changes'] != 1 else ''} to review, {report['unchanged']} unchanged"
    if skipped:
        text += " · skipped " + ", ".join(f"{n} {labels[k]}" for k, n in skipped.items())
    delta = {"doc:proposal": xliff.proposal(changes, name)} if changes else {}
    await session_service.append_event(session, versions.activity_event(text, delta))
    return report


@app.post("/api/sessions/{session_id}/lqa")
async def run_lqa(session_id: str) -> dict[str, Any]:
    """Start an independent LQA run (MQM scoring) on the current translation."""
    session = await _session(session_id)
    _ensure_idle(session)
    if session.state.get("doc:status") != "ready":
        raise HTTPException(409, "The document has no finished translation yet.")
    await segments.flush_human_edits(session_service, artifact_service, session)  # assess a saved version
    await _set_state(session_id, {"doc:task": {"kind": "lqa"}})
    _start_run(session_id, ops_runner, "Run an LQA assessment.", streaming=False)
    return {"ok": True, "model": model_name("lqa")}


class TaskIn(BaseModel):
    kind: Literal["alternatives", "retranslate", "consistency", "lqa"]
    segment_ids: list[str] = []
    instruction: str = ""
    n: int = 1


TASK_MESSAGES = {
    "alternatives": "Suggest alternatives{for_}{how}.",
    "retranslate": "Rewrite{for_}{how}.",
    "consistency": "Make the translation consistent (repeated sentences, termbase).",
    "lqa": "Run an LQA assessment.",
}


@app.post("/api/sessions/{session_id}/tasks")
async def run_task(session_id: str, body: TaskIn) -> dict[str, Any]:
    """Start a task on the finished document. Rewrites and consistency fixes come back as a proposal."""
    session = await _session(session_id)
    _ensure_idle(session)
    if session.state.get("doc:status") != "ready":
        raise HTTPException(409, "The document has no finished translation yet.")
    if body.kind in ("alternatives", "retranslate") and not body.segment_ids:
        raise HTTPException(400, "Select the segments to rewrite.")
    await segments.flush_human_edits(session_service, artifact_service, session)
    task = {"kind": body.kind, "segment_ids": body.segment_ids[:200], "instruction": body.instruction.strip()[:500],
            "n": 3 if body.kind == "alternatives" and body.n < 2 else body.n}
    await _set_state(session_id, {"doc:task": task})
    ids = body.segment_ids
    for_ = f" for {ids[0]}" if len(ids) == 1 else f" for {len(ids)} segments" if ids else ""
    how = f": {task['instruction']}" if task["instruction"] else ""
    _start_run(session_id, ops_runner, TASK_MESSAGES[body.kind].format(for_=for_, how=how), streaming=False)
    return {"ok": True, "task": task}


@app.get("/api/sessions/{session_id}/usage")
async def get_usage(session_id: str) -> dict[str, Any]:
    session = await _session(session_id)
    return await asyncio.to_thread(usage.summarize, session.events)


class ClarificationsIn(BaseModel):
    answers: dict[str, dict[str, Any] | str | None]  # {question_id: {"target", "note", "recommended"} | note | null}


@app.post("/api/sessions/{session_id}/clarifications")
async def submit_clarifications(session_id: str, body: ClarificationsIn) -> dict[str, bool]:
    """Resume the paused ingest workflow with the user's answers ({question_id: answer | null})."""
    session = await _session(session_id)
    if runs.is_running(session_id):
        raise HTTPException(409, "The agents are still working on this document.")
    interrupt_id = _pending_interrupt(session)
    if session.state.get("doc:status") != "awaiting_answers" or not interrupt_id:
        raise HTTPException(409, "The pipeline is not waiting for answers.")
    answers = {k: st.answer_of(v) for k, v in body.answers.items()}
    response = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id, name=REQUEST_INPUT_TOOL, response={"result": answers}
                )
            )
        ],
    )
    _start_run(session_id, ingest_runner, response, streaming=False)
    return {"ok": True}


@app.post("/api/sessions/{session_id}/retry")
async def retry_ingest(session_id: str) -> dict[str, bool]:
    """Re-run the ingest workflow for a document whose run failed or was interrupted (e.g. server restart)."""
    session = await _session(session_id)
    status = session.state.get("doc:status")
    if runs.is_running(session_id):
        raise HTTPException(409, "The agents are still working on this document.")
    if status in ("ready", "awaiting_answers"):
        raise HTTPException(409, "Nothing to retry.")
    await _set_state(
        session_id,
        {
            "doc:status": "uploaded",
            "doc:seg_ids": [],
            "doc:questions": [],
            "doc:versions": [],
            "doc:termbase": {},
            "doc:key_terms": [],
            "doc:brief": "",
            "doc:proposal": None,
            "doc:ocr_report": [],
            "doc:review_report": [],
            "doc:review_round": 0,
            "doc:review_pending": None,
            "doc:refined": [],
            "doc:dirty": [],
        },
    )
    _start_run(session_id, ingest_runner, f"Retry: translate {session.state.get('doc:filename')} into {TARGET_LANG}.", streaming=False)
    return {"ok": True}


@app.get("/api/sessions/{session_id}/stream")
async def stream(session_id: str) -> EventSourceResponse:
    async def gen():
        async for ev in runs.subscribe(session_id):
            yield {"data": json.dumps(ev, ensure_ascii=False, default=str)}

    return EventSourceResponse(gen(), ping=15)


@app.get("/api/sessions/{session_id}/versions/{version}")
async def get_version(session_id: str, version: int) -> dict[str, Any]:
    session = await _session(session_id)
    entry = next((v for v in session.state.get("doc:versions") or [] if v["version"] == version), None)
    if not entry:
        raise HTTPException(404, "Version not found")
    part = await artifact_service.load_artifact(
        app_name=APP_NAME,
        user_id=USER,
        session_id=session_id,
        filename=st.TRANSLATION_ARTIFACT,
        version=entry["artifact_version"],
    )
    if not part or part.text is None:
        raise HTTPException(404, "Version artifact missing")
    return {"version": version, "segments": json.loads(part.text)}


@app.get("/api/sessions/{session_id}/pages/{page}")
async def page_image(session_id: str, page: int) -> Response:
    key = (session_id, page)
    if key not in _page_cache:
        session = await _session(session_id)
        data, filename = await _source_bytes(session)
        if Path(filename).suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(404, "No page image for text documents")
        pages = await asyncio.to_thread(load_pages, data, filename, 110)
        if not 1 <= page <= len(pages):
            raise HTTPException(404, "Page out of range")
        for p in pages:
            _page_cache[(session_id, p.number)] = p.image or b""
        while len(_page_cache) > 200:
            _page_cache.popitem(last=False)
    data = _page_cache[key]
    media = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return Response(data, media_type=media, headers={"Cache-Control": "max-age=3600"})


FIGURE_NAME = re.compile(r"^figure-p\d+-\d+\.png$")


async def _figure_bytes(session_id: str, name: str) -> bytes:
    if not FIGURE_NAME.match(name):
        raise HTTPException(404, "Not a figure")
    part = await artifact_service.load_artifact(app_name=APP_NAME, user_id=USER, session_id=session_id, filename=name)
    if not part or not part.inline_data:
        raise HTTPException(404, "Figure not found")
    return part.inline_data.data


@app.get("/api/sessions/{session_id}/figures/{name}")
async def figure(session_id: str, name: str) -> Response:
    return Response(await _figure_bytes(session_id, name), media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/sessions/{session_id}/export/formats")
async def export_formats(session_id: str) -> list[dict[str, Any]]:
    session = await _session(session_id)
    return await exports.available(artifact_service, session)


@app.get("/api/sessions/{session_id}/export", response_model=None)
async def export(session_id: str, format: str = "md", version: int | None = None, field: str = "target") -> Response:
    """Download a version: pdf (original layout) | docx | html | md (zip with figures) | bilingual (review DOCX)."""
    session = await _session(session_id)
    if version is None and not runs.is_running(session_id):
        await segments.flush_human_edits(session_service, artifact_service, session)
    if version is None and format == "pdf":
        version = exports.latest_version(session)
    try:
        content, media, name = await exports.build(artifact_service, session, format, version, field)
    except exports.ExportError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(content, media_type=media, headers={"Content-Disposition": content_disposition(name)})


_preview_cache: OrderedDict[tuple[str, int, int], bytes] = OrderedDict()


async def _preview_version(session: Session, version: int | None) -> int:
    v = version or exports.latest_version(session)
    if v is None:
        raise HTTPException(409, "No translation version yet.")
    return v


_office_views: OrderedDict[str, dict] = OrderedDict()


@app.get("/api/sessions/{session_id}/preview/office")
async def office_preview(session_id: str) -> dict[str, Any]:
    """An Excel or PowerPoint file's layout (sheets as grids, slides with their text boxes), each text linked
    to its segment. Built once per document: the source never changes."""
    session = await _session(session_id)
    fmt = session.state.get("doc:format")
    if fmt not in ("xlsx", "pptx"):
        raise HTTPException(404, "Only Excel and PowerPoint files have this view.")
    if session_id not in _office_views:
        data, _ = await _source_bytes(session)
        _office_views[session_id] = await asyncio.to_thread(office_view.view, data, fmt, st.get_segments(session.state))
        while len(_office_views) > 20:
            _office_views.popitem(last=False)
    return _office_views[session_id]


@app.get("/api/sessions/{session_id}/preview/report")
async def preview_report(session_id: str, version: int | None = None) -> dict[str, Any]:
    """Per-segment layout result for the translated PDF: fit | shrunk | overflow | unaligned + boxes."""
    session = await _session(session_id)
    v = await _preview_version(session, version)
    try:
        _, report = await exports.layout_pdf(artifact_service, session, v)
    except exports.ExportError as exc:
        raise HTTPException(409, str(exc)) from exc
    return report


@app.get("/api/sessions/{session_id}/preview/pages/{page}")
async def preview_page(session_id: str, page: int, version: int | None = None) -> Response:
    """A page of the layout-preserving translated PDF, as PNG."""
    session = await _session(session_id)
    v = await _preview_version(session, version)
    key = (session_id, v, page)
    if key not in _preview_cache:
        try:
            pdf, _ = await exports.layout_pdf(artifact_service, session, v)
        except exports.ExportError as exc:
            raise HTTPException(409, str(exc)) from exc

        def rasterize() -> bytes:
            with pymupdf.open(stream=pdf, filetype="pdf") as doc:
                if not 1 <= page <= doc.page_count:
                    raise HTTPException(404, "Page out of range")
                return doc[page - 1].get_pixmap(dpi=110).tobytes("png")

        _preview_cache[key] = await asyncio.to_thread(rasterize)
        while len(_preview_cache) > 100:
            _preview_cache.popitem(last=False)
    return Response(_preview_cache[key], media_type="image/png", headers={"Cache-Control": "max-age=3600"})

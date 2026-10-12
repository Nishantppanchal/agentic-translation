"""Talking to the agents: chat messages, answers to questions, proposals, tasks and LQA runs."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from google.genai import types
from pydantic import BaseModel

from ...document import edits, proposals
from ...document import state as st
from ...models.llm import model_name
from ..services import (
    REQUEST_INPUT_TOOL,
    artifact_service,
    editor_runner,
    ensure_idle,
    ingest_runner,
    load_session,
    open_interrupt,
    ops_runner,
    runs,
    session_service,
    set_state,
    start_run,
)

router = APIRouter()


class MessageIn(BaseModel):
    text: str


@router.post("/api/sessions/{session_id}/messages")
async def send_message(session_id: str, body: MessageIn) -> dict[str, bool]:
    session = await load_session(session_id)
    ensure_idle(session)
    if not session.state.get("doc:seg_ids"):
        raise HTTPException(409, "The document hasn't been processed yet.")
    await edits.flush_human_edits(session_service, artifact_service, session)
    start_run(session_id, editor_runner, body.text.strip(), streaming=True)
    return {"ok": True}


class AnswerIn(BaseModel):
    answer: str | None = None  # an explanation of the meaning (older clients)
    target: str | None = None  # the English term to use
    note: str | None = None
    recommended: bool = False  # the recommendation, taken as it was


@router.post("/api/sessions/{session_id}/questions/{question_id}")
async def answer_question(session_id: str, question_id: str, body: AnswerIn) -> dict[str, bool]:
    session = await load_session(session_id)
    ensure_idle(session)
    questions = [dict(q) for q in session.state.get("doc:questions") or []]
    q = next((q for q in questions if q["id"] == question_id), None)
    if not q:
        raise HTTPException(404, "Question not found")
    answer = st.answer_of({"target": body.target, "note": body.note or body.answer, "recommended": body.recommended})
    if not answer:
        q["status"] = "dismissed"
        await set_state(session_id, {"doc:questions": questions})
        return {"ok": True}
    q["answer_recommended"] = answer["recommended"]  # how the term is saved to the project when the edits are accepted
    await set_state(session_id, {"doc:questions": questions})
    if answer["target"]:
        text = f'[Answer to {question_id}] "{q["term"]}": use "{answer["target"]}"' + (f' ({answer["note"]})' if answer["note"] else "")
    else:
        text = f'[Answer to {question_id}] "{q["term"]}": {answer["note"]}'
    await edits.flush_human_edits(session_service, artifact_service, session)
    start_run(session_id, editor_runner, text, streaming=True)
    return {"ok": True}


class AcceptIn(BaseModel):
    changes: list[str] | None = None  # "segment_id|field" keys to apply; None = all
    choices: dict[str, int] | None = None  # change key → chosen alternative (default: the first)


@router.post("/api/sessions/{session_id}/proposal/accept")
async def accept_proposal(session_id: str, body: AcceptIn) -> dict[str, Any]:
    """Apply the editor's pending proposal (all, or the selected changes) as a new version."""
    session = await load_session(session_id)
    if runs.is_running(session_id):
        raise HTTPException(409, "The agents are still working on this document.")
    await edits.flush_human_edits(session_service, artifact_service, session)
    try:
        return await proposals.accept(session_service, artifact_service, session, body.changes, body.choices)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/sessions/{session_id}/proposal/reject")
async def reject_proposal(session_id: str) -> dict[str, Any]:
    session = await load_session(session_id)
    if runs.is_running(session_id):
        raise HTTPException(409, "The agents are still working on this document.")
    try:
        return await proposals.reject(session_service, session)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/sessions/{session_id}/lqa")
async def run_lqa(session_id: str) -> dict[str, Any]:
    """Start an independent LQA run (MQM scoring) on the current translation."""
    session = await load_session(session_id)
    ensure_idle(session)
    if session.state.get("doc:status") != "ready":
        raise HTTPException(409, "The document has no finished translation yet.")
    await edits.flush_human_edits(session_service, artifact_service, session)  # assess a saved version
    await set_state(session_id, {"doc:task": {"kind": "lqa"}})
    start_run(session_id, ops_runner, "Run an LQA assessment.", streaming=False)
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


@router.post("/api/sessions/{session_id}/tasks")
async def run_task(session_id: str, body: TaskIn) -> dict[str, Any]:
    """Start a task on the finished document. Rewrites and consistency fixes come back as a proposal."""
    session = await load_session(session_id)
    ensure_idle(session)
    if session.state.get("doc:status") != "ready":
        raise HTTPException(409, "The document has no finished translation yet.")
    if body.kind in ("alternatives", "retranslate") and not body.segment_ids:
        raise HTTPException(400, "Select the segments to rewrite.")
    await edits.flush_human_edits(session_service, artifact_service, session)
    task = {"kind": body.kind, "segment_ids": body.segment_ids[:200], "instruction": body.instruction.strip()[:500],
            "n": 3 if body.kind == "alternatives" and body.n < 2 else body.n}
    await set_state(session_id, {"doc:task": task})
    ids = body.segment_ids
    for_ = f" for {ids[0]}" if len(ids) == 1 else f" for {len(ids)} segments" if ids else ""
    how = f": {task['instruction']}" if task["instruction"] else ""
    start_run(session_id, ops_runner, TASK_MESSAGES[body.kind].format(for_=for_, how=how), streaming=False)
    return {"ok": True, "task": task}


class ClarificationsIn(BaseModel):
    answers: dict[str, dict[str, Any] | str | None]  # {question_id: {"target", "note", "recommended"} | note | null}


@router.post("/api/sessions/{session_id}/clarifications")
async def submit_clarifications(session_id: str, body: ClarificationsIn) -> dict[str, bool]:
    """Resume the paused ingest workflow with the user's answers ({question_id: answer | null})."""
    session = await load_session(session_id)
    if runs.is_running(session_id):
        raise HTTPException(409, "The agents are still working on this document.")
    interrupt_id = open_interrupt(session)
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
    start_run(session_id, ingest_runner, response, streaming=False)
    return {"ok": True}

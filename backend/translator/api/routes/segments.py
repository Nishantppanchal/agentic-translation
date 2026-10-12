"""The segment grid: human edits, locks, comments, confirmation, versions, QA, find & replace and token usage."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import projects
from ...document import edits, find_replace
from ...document import state as st
from ...quality import qa
from .. import usage
from ..services import artifact_service, editable_session, load_session, session_service, set_state

router = APIRouter()


class SegmentEdit(BaseModel):
    target: str | None = None
    confirm: bool = False
    base_target: str | None = None  # the text the editor started from (stale-edit check)
    role: Literal["translator", "reviewer"] = "translator"  # what "confirm" means (confirmed vs reviewed)


@router.patch("/api/sessions/{session_id}/segments/{segment_id}")
async def edit_segment(session_id: str, segment_id: str, body: SegmentEdit) -> dict[str, Any]:
    session = await editable_session(session_id)
    try:
        seg = await edits.edit_segment(
            session_service, session, segment_id, target=body.target, confirm=body.confirm,
            base_target=body.base_target, role=body.role,
        )
    except KeyError as exc:
        raise HTTPException(404, f"No segment {segment_id}") from exc
    except edits.EditConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"segment": seg, "human_dirty": session.state.get("doc:human_dirty") or [], "counts": st.status_counts(session.state)}


class LockIn(BaseModel):
    locked: bool


@router.post("/api/sessions/{session_id}/segments/{segment_id}/lock")
async def lock_segment(session_id: str, segment_id: str, body: LockIn) -> dict[str, Any]:
    session = await editable_session(session_id)
    try:
        return {"segment": await edits.set_locked(session_service, session, segment_id, body.locked)}
    except KeyError as exc:
        raise HTTPException(404, f"No segment {segment_id}") from exc


class ConfirmIn(BaseModel):
    ids: list[str] | None = None  # None = translator: drafts the AI check passed · reviewer: all confirmed
    role: Literal["translator", "reviewer"] = "translator"


@router.get("/api/sessions/{session_id}/segments/{segment_id}/tm")
async def segment_tm(session_id: str, segment_id: str) -> dict[str, Any]:
    """Top translation-memory matches for one segment (101 = same source and same previous segment)."""
    session = await load_session(session_id)
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


@router.post("/api/sessions/{session_id}/segments/{segment_id}/comments")
async def add_comment(session_id: str, segment_id: str, body: CommentIn) -> dict[str, Any]:
    session = await editable_session(session_id)
    try:
        return {"segment": await edits.add_comment(session_service, session, segment_id, body.text, body.role)}
    except KeyError as exc:
        raise HTTPException(404, f"No segment {segment_id}") from exc
    except edits.EditConflict as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/api/sessions/{session_id}/segments/{segment_id}/comments/{comment_id}")
async def resolve_comment(session_id: str, segment_id: str, comment_id: str, body: CommentPatch) -> dict[str, Any]:
    session = await editable_session(session_id)
    try:
        return {"segment": await edits.update_comment(session_service, session, segment_id, comment_id, resolved=body.resolved)}
    except KeyError as exc:
        raise HTTPException(404, "Comment not found") from exc


@router.delete("/api/sessions/{session_id}/segments/{segment_id}/comments/{comment_id}")
async def delete_comment(session_id: str, segment_id: str, comment_id: str) -> dict[str, Any]:
    session = await editable_session(session_id)
    try:
        return {"segment": await edits.update_comment(session_service, session, segment_id, comment_id, delete=True)}
    except KeyError as exc:
        raise HTTPException(404, "Comment not found") from exc


@router.post("/api/sessions/{session_id}/segments/confirm")
async def confirm_segments(session_id: str, body: ConfirmIn) -> dict[str, Any]:
    session = await editable_session(session_id)
    try:
        confirmed = await edits.confirm_segments(session_service, session, body.ids, body.role)
    except edits.EditConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"confirmed": confirmed, "counts": st.status_counts(session.state)}


@router.post("/api/sessions/{session_id}/versions")
async def save_version(session_id: str) -> dict[str, Any]:
    """Save pending human edits as one version."""
    session = await editable_session(session_id)
    return {"version": await edits.flush_human_edits(session_service, artifact_service, session)}


@router.get("/api/sessions/{session_id}/qa")
async def get_qa(session_id: str) -> dict[str, Any]:
    """Automatic QA over the current translation (computed on request; ignored issues are marked)."""
    session = await load_session(session_id)
    issues = await asyncio.to_thread(qa.document_qa, session.state)
    return {"issues": issues, "summary": qa.summary(issues), "checks": [{"id": c.id, "label": c.label} for c in qa.CHECKS]}


class IgnoreIn(BaseModel):
    ids: list[str]
    ignored: bool = True


@router.post("/api/sessions/{session_id}/qa/ignore")
async def ignore_qa(session_id: str, body: IgnoreIn) -> dict[str, Any]:
    """Ignore (or restore) QA issues. An issue comes back if its segment's text changes."""
    session = await load_session(session_id)
    current = list(session.state.get("doc:qa_ignored") or [])
    ids = set(body.ids)
    updated = [*current, *(i for i in body.ids if i not in current)] if body.ignored else [i for i in current if i not in ids]
    await set_state(session_id, {"doc:qa_ignored": updated[-2000:]})
    return {"ignored": len(updated)}


class ReplaceIn(BaseModel):
    find: str
    replace: str = ""
    regex: bool = False
    case: bool = False
    whole_word: bool = False
    scope: Literal["all", "unconfirmed"] = "all"
    ids: list[str] | None = None  # apply: only these segments (from the preview)


@router.post("/api/sessions/{session_id}/replace/preview")
async def replace_preview(session_id: str, body: ReplaceIn) -> dict[str, Any]:
    session = await load_session(session_id)
    try:
        pattern = find_replace.compile_find(body.find, regex=body.regex, case=body.case, whole_word=body.whole_word)
        found, locked = find_replace.matches(st.get_segments(session.state), pattern, body.replace, regex=body.regex, scope=body.scope)
    except find_replace.ReplaceError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"matches": found, "locked": locked}


@router.post("/api/sessions/{session_id}/replace")
async def replace_apply(session_id: str, body: ReplaceIn) -> dict[str, Any]:
    """Apply find & replace as human edits, saved as one version."""
    session = await editable_session(session_id)
    try:
        return await edits.replace_in_targets(
            session_service, artifact_service, session, body.find, body.replace, regex=body.regex, case=body.case,
            whole_word=body.whole_word, scope=body.scope, ids=body.ids,
        )
    except find_replace.ReplaceError as exc:
        raise HTTPException(400, str(exc)) from exc
    except edits.EditConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/sessions/{session_id}/usage")
async def get_usage(session_id: str) -> dict[str, Any]:
    session = await load_session(session_id)
    return await asyncio.to_thread(usage.summarize, session.events)

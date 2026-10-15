"""Direct human work in the segment grid: edit, confirm, lock — and versioning those edits.

Every change is a session event (author "human"), so it is persisted and auditable. Edits
accumulate in `doc:human_dirty` and become ONE version ("Human edits: n segments") when the
user saves, or automatically before an agent run, a proposal accept, or an export.
"""

from __future__ import annotations

import asyncio
import logging
import time

from google.adk.artifacts import BaseArtifactService
from google.adk.events import Event, EventActions
from google.adk.sessions import BaseSessionService, Session

from . import comments, memory
from . import state as st
from .versions import activity_event, snapshot_version

log = logging.getLogger(__name__)

EDITABLE_STATUSES = {"ready", "error"}


class EditConflict(Exception):
    """The edit can't be applied (locked, stale base, pipeline still running…)."""


def _segment(session: Session, seg_id: str) -> dict:
    seg = st.get_segment(session.state, seg_id)
    if seg is None:
        raise KeyError(seg_id)
    return st.normalize(seg)


def _check_editable(session: Session) -> None:
    status = session.state.get("doc:status")
    if status not in EDITABLE_STATUSES:
        raise EditConflict("The document is still being processed; edit it when the pipeline has finished.")


async def save_to_memory(state, segs: list[dict], approval: str) -> set[str]:
    """Confirmed/reviewed segments → the project's TM (memory.save, in a thread). → the ids now in the TM.
    A TM that can't be written doesn't undo the confirmation: the segment just isn't marked as saved."""
    try:
        return (await asyncio.to_thread(memory.save, state, segs, approval)).saved
    except Exception:
        log.exception("saving %d segment(s) to the translation memory failed", len(segs))
        return set()


def _without_proposal_change(session: Session, seg_id: str) -> dict:
    """Drop a pending agent proposal for this segment's translation (the human's edit wins)."""
    proposal = st.get_proposal(session.state)
    if not proposal:
        return {}
    changes = [c for c in proposal["changes"] if not (c["segment_id"] == seg_id and c["field"] == "target")]
    if len(changes) == len(proposal["changes"]):
        return {}
    remaining = {**proposal, "changes": changes}
    return {"doc:proposal": remaining if (changes or remaining.get("glossary")) else None}


ROLE_STATUS = {"translator": "confirmed", "reviewer": "reviewed"}


async def edit_segment(
    session_service: BaseSessionService,
    session: Session,
    seg_id: str,
    *,
    target: str | None = None,
    confirm: bool = False,
    base_target: str | None = None,
    role: str = "translator",
) -> dict:
    """Save a human edit and/or confirm it. Confirming sets `confirmed` (translator) or `reviewed`
    (reviewer: the second-linguist check). `base_target` = the text the editor started from (stale check)."""
    done = ROLE_STATUS.get(role, "confirmed")
    _check_editable(session)
    seg = _segment(session, seg_id)
    if seg["locked"]:
        raise EditConflict(f"Segment {seg_id} is locked.")
    current = seg.get("target") or ""
    if base_target is not None and base_target != current:
        raise EditConflict(f"Segment {seg_id} changed since you started editing; reload it.")

    changed = target is not None and target != current
    if changed:
        seg = st.apply_target(seg, target, origin="human", status=done if confirm else "draft")
    elif confirm and seg["status"] != done:
        seg = {**seg, "status": done, "updated_at": time.time()}
    else:
        return seg

    if seg["status"] in st.HUMAN_DONE:  # confirmed or reviewed: its wording goes into the project's TM
        saved = await save_to_memory(session.state, [seg], "review" if done == "reviewed" else "segment")
        seg = {**seg, "tm_saved": seg_id in saved}
    delta: dict = {st.seg_key(seg_id): seg, **_without_proposal_change(session, seg_id)}
    if changed:
        dirty = list(session.state.get("doc:human_dirty") or [])
        if seg_id not in dirty:
            delta["doc:human_dirty"] = [*dirty, seg_id]
    await session_service.append_event(session, Event(author="human", actions=EventActions(state_delta=delta)))
    return seg


async def set_locked(session_service: BaseSessionService, session: Session, seg_id: str, locked: bool) -> dict:
    seg = {**_segment(session, seg_id), "locked": locked, "updated_at": time.time()}
    await session_service.append_event(
        session, Event(author="human", actions=EventActions(state_delta={st.seg_key(seg_id): seg}))
    )
    return seg


async def confirm_segments(
    session_service: BaseSessionService, session: Session, ids: list[str] | None = None, role: str = "translator"
) -> list[str]:
    """Bulk confirm. Translator: the given drafts, or (ids=None) every draft the AI check passed.
    Reviewer: mark the given confirmed segments reviewed, or (ids=None) all confirmed ones."""
    _check_editable(session)
    done = ROLE_STATUS.get(role, "confirmed")
    eligible = {"confirmed": ("new", "draft"), "reviewed": ("confirmed",) if ids is None else ("new", "draft", "confirmed")}[done]
    delta: dict = {}
    now = time.time()
    for seg in map(st.normalize, st.get_segments(session.state)):
        if seg["locked"] or seg["status"] not in eligible or not seg.get("target"):
            continue
        default_pick = seg["ai_check"] == "passed" if done == "confirmed" else True
        if (ids is None and default_pick) or (ids is not None and seg["id"] in ids):
            delta[st.seg_key(seg["id"])] = {**seg, "status": done, "updated_at": now}
    if delta:
        n = len(delta)
        # Into the TM too, as CAT tools do — tagged "bulk": such a unit never confirms a later segment by itself
        # (a 101% match from it arrives as a draft), and it never replaces wording a person approved one by one.
        saved = await save_to_memory(session.state, list(delta.values()), "bulk")
        for key, seg in delta.items():
            seg["tm_saved"] = seg["id"] in saved
        verb = "Confirmed" if done == "confirmed" else "Marked reviewed:"
        text = f"{verb} {n} segment{'s' if n != 1 else ''}" + (f" · {len(saved)} saved to the TM" if saved else "")
        await session_service.append_event(session, activity_event(text, delta))
    return [k.removeprefix(st.SEG) for k in delta]


async def flush_human_edits(
    session_service: BaseSessionService, artifact_service: BaseArtifactService, session: Session
) -> int | None:
    """Turn pending human edits into one version. Returns the version number, or None if nothing pending."""
    dirty = list(session.state.get("doc:human_dirty") or [])
    if not dirty:
        return None
    n = len(dirty)
    note = f"Human edits: {n} segment{'s' if n != 1 else ''}"
    delta, artifact_delta, version = await snapshot_version(artifact_service, session, session.state, note, dirty)
    delta["doc:human_dirty"] = []
    await session_service.append_event(session, activity_event(f"Saved your edits → v{version}", delta, artifact_delta))
    return version


async def replace_in_targets(
    session_service: BaseSessionService,
    artifact_service: BaseArtifactService,
    session: Session,
    find: str,
    replace: str,
    *,
    regex: bool = False,
    case: bool = False,
    whole_word: bool = False,
    scope: str = "all",
    ids: list[str] | None = None,
) -> dict:
    """Find & replace as human edits, saved as one version. `ids` limits it to segments chosen in the preview."""
    from . import find_replace

    _check_editable(session)
    pattern = find_replace.compile_find(find, regex=regex, case=case, whole_word=whole_word)
    found, locked = find_replace.matches(st.get_segments(session.state), pattern, replace, regex=regex, scope=scope)
    if ids is not None:
        found = [m for m in found if m["segment_id"] in set(ids)]
    if not found:
        return {"changed": [], "version": None, "locked": locked}
    await flush_human_edits(session_service, artifact_service, session)  # earlier edits get their own version

    delta: dict = {}
    for m in found:
        seg = st.apply_target(_segment(session, m["segment_id"]), m["after"], origin="human", status="draft")
        delta[st.seg_key(seg["id"])] = seg
    proposal = st.get_proposal(session.state)
    if proposal:  # the person's replacement wins over pending agent changes to the same segments
        replaced = {m["segment_id"] for m in found}
        changes = [c for c in proposal["changes"] if not (c["field"] == "target" and c["segment_id"] in replaced)]
        if len(changes) != len(proposal["changes"]):
            delta["doc:proposal"] = {**proposal, "changes": changes} if changes or proposal.get("glossary") else None
    view = {**session.state, **delta}
    n = len(found)
    label = f"“{find[:30]}” → “{replace[:30]}”"
    version_delta, artifact_delta, version = await snapshot_version(
        artifact_service, session, view, f"Find & replace: {label}", [m["segment_id"] for m in found]
    )
    delta.update(version_delta)
    text = f"Replaced {label} in {n} segment{'s' if n != 1 else ''} → v{version}"
    await session_service.append_event(session, activity_event(text, delta, artifact_delta))
    return {"changed": [m["segment_id"] for m in found], "version": version, "locked": locked}


# ---- Comments ---------------------------------------------------------------- #
# Stored in doc:comments (see comments.py); any status, but not while a run is active (the API checks that).


def _with_comments(state, seg_id: str) -> dict | None:
    seg = st.get_segment(state, seg_id)
    return {**st.normalize(seg), "comments": comments.for_segment(state, seg_id)} if seg else None


async def add_comment(session_service: BaseSessionService, session: Session, seg_id: str, text: str, role: str = "translator") -> dict:
    """A note on a segment (a question for the reviewer, a client remark…). Comments never change the text."""
    try:
        delta, _ = comments.add(session.state, seg_id, text, role)
    except ValueError as exc:
        raise EditConflict(str(exc)) from exc
    await session_service.append_event(session, Event(author="human", actions=EventActions(state_delta=delta)))
    return _with_comments({**session.state, **delta}, seg_id)


async def update_comment(session_service: BaseSessionService, session: Session, seg_id: str, comment_id: str,
                         *, resolved: bool | None = None, delete: bool = False) -> dict | None:
    """Resolve, reopen or delete a comment. Returns the segment `seg_id` with its comments (None if it's gone)."""
    delta = comments.update(session.state, comment_id, resolved=resolved, delete=delete)
    await session_service.append_event(session, Event(author="human", actions=EventActions(state_delta=delta)))
    return _with_comments({**session.state, **delta}, seg_id)

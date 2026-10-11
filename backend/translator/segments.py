"""Direct human work in the segment grid: edit, confirm, lock — and versioning those edits.

Every change is a session event (author "human"), so it is persisted and auditable. Edits
accumulate in `doc:human_dirty` and become ONE version ("Human edits: n segments") when the
user saves, or automatically before an agent run, a proposal accept, or an export.
"""

from __future__ import annotations

import time
import uuid

from google.adk.artifacts import BaseArtifactService
from google.adk.events import Event, EventActions
from google.adk.sessions import BaseSessionService, Session

from . import projects
from .filters import inline
from . import state as st
from .versions import activity_event, snapshot_version

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


def remember(session: Session, segs: list[dict]) -> int:
    """Write human-confirmed segments to the project's translation memory (with their context)."""
    pid = projects.project_id(session.state)
    if not pid:
        return 0
    order = [s for s in st.get_segments(session.state) if s.get("translatable", True)]
    prev_of = {s["id"]: (order[i - 1]["source"] if i else "") for i, s in enumerate(order)}
    filename = session.state.get("doc:filename", "")
    store, n = projects.get_store(), 0
    for seg in segs:
        if seg.get("target") and seg.get("status") in st.HUMAN_DONE:
            store.add_unit(pid, seg["source"], seg["target"], prev_of.get(seg["id"], ""), origin=f"{filename}#{seg['id']}")
            n += 1
    return n


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
    if changed and (inline.has_codes(seg["source"]) or inline.has_codes(target)):
        target = inline.normalize(target)
        problems = inline.validate(seg["source"], target)
        if problems:
            raise EditConflict(
                f"Inline codes in {seg_id} don't match the source ({'; '.join(problems)}). "
                "Keep each code from the source exactly once — Alt+S copies the source with its codes."
            )
    if changed:
        seg = st.apply_target(seg, target, origin="human", status=done if confirm else "draft")
    elif confirm and seg["status"] != done:
        seg = {**seg, "status": done, "updated_at": time.time()}
    else:
        return seg

    delta: dict = {st.seg_key(seg_id): seg, **_without_proposal_change(session, seg_id)}
    if changed:
        dirty = list(session.state.get("doc:human_dirty") or [])
        if seg_id not in dirty:
            delta["doc:human_dirty"] = [*dirty, seg_id]
    await session_service.append_event(session, Event(author="human", actions=EventActions(state_delta=delta)))
    if seg["status"] in st.HUMAN_DONE:
        remember(session, [seg])
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
        verb = "Confirmed" if done == "confirmed" else "Marked reviewed:"
        await session_service.append_event(
            session, activity_event(f"{verb} {n} segment{'s' if n != 1 else ''}", delta)
        )
        # Not written to the translation memory: a bulk click isn't a person checking each sentence, and the TM
        # reuses its units as approved wording. Segments confirmed one by one (edit / Ctrl+Enter) go in.
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
    from . import replace as rp

    _check_editable(session)
    pattern = rp.compile_find(find, regex=regex, case=case, whole_word=whole_word)
    found, locked = rp.matches(st.get_segments(session.state), pattern, replace, regex=regex, scope=scope)
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

COMMENT_ROLES = ("translator", "reviewer", "agent")


async def add_comment(session_service: BaseSessionService, session: Session, seg_id: str, text: str, role: str = "translator") -> dict:
    """A note on a segment (a question for the reviewer, a client remark…). Comments never change the text."""
    seg = _segment(session, seg_id)
    if not text.strip():
        raise EditConflict("The comment is empty.")
    comment = {"id": uuid.uuid4().hex[:8], "role": role if role in COMMENT_ROLES else "translator",
               "text": text.strip(), "at": time.time(), "resolved": False}
    seg = {**seg, "comments": [*seg["comments"], comment]}
    await session_service.append_event(session, Event(author="human", actions=EventActions(state_delta={st.seg_key(seg_id): seg})))
    return seg


async def update_comment(session_service: BaseSessionService, session: Session, seg_id: str, comment_id: str,
                         *, resolved: bool | None = None, delete: bool = False) -> dict:
    seg = _segment(session, seg_id)
    if not any(c["id"] == comment_id for c in seg["comments"]):
        raise KeyError(comment_id)
    if delete:
        comments = [c for c in seg["comments"] if c["id"] != comment_id]
    else:
        comments = [{**c, "resolved": bool(resolved)} if c["id"] == comment_id else c for c in seg["comments"]]
    seg = {**seg, "comments": comments}
    await session_service.append_event(session, Event(author="human", actions=EventActions(state_delta={st.seg_key(seg_id): seg})))
    return seg

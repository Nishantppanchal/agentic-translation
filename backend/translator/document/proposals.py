"""Proposals: changes agents stage for a person to accept or reject.

Staging (`open_proposal` / `stage_change` / `close_proposal`) is shared by the chat editor's tools, the
task workflow (rewrites, consistency fixes). A change may offer `alternatives`
(the first is the default); accepting picks one per change.

Accepting applies the selected changes, merges any proposed glossary entries (which supersede the
translator's termbase), snapshots a new translation version and records it all as one session event,
so it shows up in history and diffs.
"""

from __future__ import annotations

import copy
import time
import uuid

from google.adk.artifacts import BaseArtifactService
from google.adk.sessions import BaseSessionService, Session

from .. import projects
from ..quality import qa
from . import state as st
from .versions import activity_event, snapshot_version


def change_key(change: dict) -> str:
    return f"{change['segment_id']}|{change['field']}"


def open_proposal(state, note: str | None = None) -> dict:
    """The pending proposal (a copy, so callers can stage into it) or a new, empty one."""
    current = st.get_proposal(state)
    proposal = copy.deepcopy(current) if current else {
        "id": f"p{uuid.uuid4().hex[:8]}", "notes": [], "changes": [], "glossary": {}, "created_at": time.time(),
    }
    if note and note not in proposal["notes"]:
        proposal["notes"].append(note)
    return proposal


def stage_change(proposal: dict, state, segment_id: str, field: str, after: str,
                 alternatives: list[dict] | None = None) -> bool:
    """Stage `field` of a segment. Staging the committed text again drops the change; with
    `alternatives` ([{text, note}], at least two different texts) the person picks one when accepting.
    Locked segments are never staged. Returns whether a change is now staged for the segment."""
    seg = st.normalize(st.get_segment(state, segment_id) or {})
    if not seg.get("id") or seg.get("locked"):
        return False
    committed = seg.get(field) or ""
    proposal["changes"] = [c for c in proposal["changes"] if not (c["segment_id"] == segment_id and c["field"] == field)]
    options: list[dict] = []
    for alt in alternatives or []:
        text = (alt.get("text") or "").strip()
        if text and text != committed and all(o["text"] != text for o in options):
            options.append({"text": text, "note": (alt.get("note") or "").strip()})
    if len(options) > 1:
        proposal["changes"].append({"segment_id": segment_id, "field": field, "before": committed,
                                    "after": options[0]["text"], "alternatives": options})
        return True
    if options:
        after = options[0]["text"]
    if after == committed:
        return False
    proposal["changes"].append({"segment_id": segment_id, "field": field, "before": committed, "after": after})
    return True


def close_proposal(proposal: dict) -> dict | None:
    """What to store as `doc:proposal`: None once nothing is left in it."""
    return proposal if (proposal["changes"] or proposal["glossary"]) else None


async def accept(
    session_service: BaseSessionService,
    artifact_service: BaseArtifactService,
    session: Session,
    selected: list[str] | None = None,
    choices: dict[str, int] | None = None,
    confirm: bool = False,
) -> dict:
    """Apply the pending proposal (or only the `selected` change keys). Unselected changes are dropped.
    `choices` picks an alternative per change key (default: the first). `confirm`: the person confirms the new
    translations as they accept them (Accept & confirm), so they go into the project's TM."""
    proposal = st.get_proposal(session.state)
    if not proposal:
        raise ValueError("There is no pending proposal.")
    keys = set(selected) if selected is not None else None
    changes = [c for c in proposal["changes"] if keys is None or change_key(c) in keys]
    for i, c in enumerate(changes):
        options = c.get("alternatives") or []
        pick = (choices or {}).get(change_key(c), 0)
        if options and 0 <= pick < len(options):
            changes[i] = {**c, "after": options[pick]["text"]}
    # A segment locked after the proposal was made is left alone.
    changes = [c for c in changes if not st.normalize(st.get_segment(session.state, c["segment_id"]) or {}).get("locked")]

    view = dict(session.state)  # state as it will be, to snapshot the new version
    delta: dict = {}
    for c in changes:
        seg = st.normalize(view[st.seg_key(c["segment_id"])])
        if c["field"] == "target":
            seg = st.apply_target(seg, c["after"], origin="agent", status="confirmed" if confirm else "draft")
        else:  # OCR fix in the source: the translation needs another look
            seg = {**seg, "source": c["after"], "status": "draft", "updated_at": time.time()}
            seg["flags"] = qa.check_segment(seg, seg.get("target"))
        view[st.seg_key(c["segment_id"])] = delta[st.seg_key(c["segment_id"])] = seg

    if proposal.get("glossary"):
        pid = projects.project_id(session.state)
        # A term whose question was answered by taking the recommendation as it was stays "proposed".
        recommended = {q["term"] for q in session.state.get("doc:questions") or [] if q.get("answer_recommended")}
        for term, entry in proposal["glossary"].items():
            if pid:  # accepted terminology becomes project terminology for the next documents
                status = "proposed" if term in recommended and entry.get("target") else "approved"
                projects.get_store().upsert_term(pid, term, entry.get("target", ""), entry.get("note", ""), status=status)
        glossary = {**(session.state.get("doc:glossary") or {}), **proposal["glossary"]}
        delta["doc:glossary"] = glossary
        delta["doc:termbase"] = st.without_terms(dict(session.state.get("doc:termbase") or {}), set(glossary))

    changed_ids = list(dict.fromkeys(c["segment_id"] for c in changes))
    artifact_delta: dict = {}
    version = None
    if changed_ids:
        request = (proposal.get("notes") or [""])[0]
        note = f"Edit: {request[:70]}{'…' if len(request) > 70 else ''}" if request else "Accepted edits"
        version_delta, artifact_delta, version = await snapshot_version(artifact_service, session, view, note, changed_ids)
        delta.update(version_delta)

    dropped = len(proposal["changes"]) - len(changes)
    delta["doc:proposal"] = None
    delta["doc:last_proposal"] = {"id": proposal["id"], "outcome": "accepted", "version": version, "at": time.time()}
    text = f"Accepted {len(changes)} change{'s' if len(changes) != 1 else ''}"
    if version:
        text += f" → v{version}"
    if dropped:
        text += f" ({dropped} left out)"
    if proposal.get("glossary"):
        text += f"; glossary +{len(proposal['glossary'])}"
    done = [view[st.seg_key(i)] for i in changed_ids if view[st.seg_key(i)].get("status") in st.HUMAN_DONE]
    if done:  # Accept & confirm: the confirmed translations go into the project's TM
        from .edits import save_to_memory  # local: edits imports this module

        saved = await save_to_memory(view, done, "proposal")
        for i in saved:
            delta[st.seg_key(i)] = {**delta[st.seg_key(i)], "tm_saved": True}
        if saved:
            text += f"; {len(saved)} confirmed and saved to the TM"
    await session_service.append_event(session, activity_event(text, delta, artifact_delta))
    return {"version": version, "applied": len(changes), "dropped": dropped}


async def reject(session_service: BaseSessionService, session: Session) -> dict:
    proposal = st.get_proposal(session.state)
    if not proposal:
        raise ValueError("There is no pending proposal.")
    delta = {
        "doc:proposal": None,
        "doc:last_proposal": {"id": proposal["id"], "outcome": "rejected", "version": None, "at": time.time()},
    }
    n, g = len(proposal["changes"]), len(proposal.get("glossary") or {})
    parts = [f"{n} change{'s' if n != 1 else ''}"] if n else []
    parts += [f"{g} glossary entr{'ies' if g != 1 else 'y'}"] if g else []
    await session_service.append_event(session, activity_event(f"Rejected the proposal ({', '.join(parts)})", delta))
    return {"rejected": n}

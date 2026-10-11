"""Segment lifecycle + direct human edits in the grid."""

from __future__ import annotations

import asyncio
import json

import pytest
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService

from translator import proposals, segments
from translator import state as st

APP = "t"


def _seg(sid: str, target: str | None, status: str = "draft", translatable: bool = True, **extra) -> dict:
    return {"id": sid, "page": 1, "kind": "paragraph", "source": f"Quelle {sid} mit genug Wörtern hier",
            "target": target, "translatable": translatable, "status": status, "origin": "mt", **extra}


async def _doc(status: str = "ready", **segs: dict):
    sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
    session = await sessions.create_session(app_name=APP, user_id="u", state={
        "doc:status": status, "doc:seg_ids": list(segs), "doc:versions": [],
        **{st.seg_key(k): v for k, v in segs.items()}})
    return sessions, artifacts, session


async def _reload(sessions, session):
    return await sessions.get_session(app_name=APP, user_id="u", session_id=session.id)


def run(coro):
    return asyncio.run(coro)


def test_normalize_upgrades_old_segments():
    old = {"id": "p1.1", "source": "x", "target": "y", "translatable": True}
    assert st.normalize(old) | {} == {**old, "origin": "mt", "status": "draft", "locked": False, "ai_check": None, "qe": None,
                                      "flags": [], "comments": [], "updated_at": None}
    copy = st.normalize({"id": "p1.2", "source": "2026", "target": "2026", "translatable": False})
    assert (copy["status"], copy["origin"], copy["locked"]) == ("confirmed", "copy", True)


def test_human_edit_confirm_and_version():
    async def main():
        sessions, artifacts, s = await _doc(**{"p1.1": _seg("p1.1", "Old text", ai_check="passed"), "p1.2": _seg("p1.2", "Fine")})
        # Edit (draft), then confirm without changing the text.
        seg = await segments.edit_segment(sessions, s, "p1.1", target="New text", base_target="Old text")
        assert (seg["target"], seg["origin"], seg["status"]) == ("New text", "human", "draft")
        assert seg["ai_check"] is None  # the AI verdict was about the old text
        seg = await segments.edit_segment(sessions, s, "p1.1", confirm=True)
        assert seg["status"] == "confirmed" and seg["target"] == "New text"
        # Confirming without an edit is not a text change.
        await segments.edit_segment(sessions, s, "p1.2", confirm=True)
        s = await _reload(sessions, s)
        assert s.state["doc:human_dirty"] == ["p1.1"]
        assert st.status_counts(s.state) == {"new": 0, "draft": 0, "confirmed": 2, "reviewed": 0, "total": 2}

        version = await segments.flush_human_edits(sessions, artifacts, s)
        s = await _reload(sessions, s)
        assert version == 1 and s.state["doc:human_dirty"] == []
        entry = s.state["doc:versions"][-1]
        assert entry["note"] == "Human edits: 1 segment" and entry["changed"] == ["p1.1"]
        part = await artifacts.load_artifact(app_name=APP, user_id="u", session_id=s.id, filename=st.TRANSLATION_ARTIFACT)
        assert json.loads(part.text)["p1.1"] == "New text"
        assert await segments.flush_human_edits(sessions, artifacts, s) is None  # nothing pending

    run(main())


@pytest.mark.parametrize(
    "doc_status, seg_kwargs, base, message",
    [
        ("translating", {}, None, "still being processed"),
        ("ready", {"locked": True}, None, "locked"),
        ("ready", {}, "something else", "changed since you started"),
    ],
)
def test_edit_conflicts(doc_status, seg_kwargs, base, message):
    async def main():
        sessions, _, s = await _doc(doc_status, **{"p1.1": _seg("p1.1", "Text", **seg_kwargs)})
        with pytest.raises(segments.EditConflict, match=message):
            await segments.edit_segment(sessions, s, "p1.1", target="New", base_target=base)

    run(main())


def test_bulk_confirm_takes_ai_checked_drafts_then_reviewer_marks_reviewed():
    async def main():
        sessions, _, s = await _doc(**{
            "p1.1": _seg("p1.1", "A", ai_check="passed"), "p1.2": _seg("p1.2", "B"),
            "p1.3": _seg("p1.3", "C", ai_check="passed", locked=True),
            "p1.4": _seg("p1.4", "2026", "confirmed", translatable=False)})
        assert await segments.confirm_segments(sessions, s) == ["p1.1"]  # AI-checked drafts only
        assert await segments.confirm_segments(sessions, s, ["p1.2"]) == ["p1.2"]
        # The second-linguist step: confirmed → reviewed.
        assert await segments.confirm_segments(sessions, s, role="reviewer") == ["p1.1", "p1.2"]
        assert st.status_counts(s.state)["reviewed"] == 2

    run(main())


def test_reviewer_confirm_marks_reviewed_and_ai_never_does():
    async def main():
        sessions, _, s = await _doc(**{"p1.1": _seg("p1.1", "A", "confirmed", ai_check="passed")})
        seg = await segments.edit_segment(sessions, s, "p1.1", confirm=True, role="reviewer")
        assert seg["status"] == "reviewed"
        seg = await segments.edit_segment(sessions, s, "p1.1", target="A, revised", confirm=True, role="reviewer")
        assert (seg["status"], seg["origin"]) == ("reviewed", "human")

    run(main())


def test_lock_blocks_edits_and_proposals():
    async def main():
        sessions, artifacts, s = await _doc(**{"p1.1": _seg("p1.1", "A")})
        await segments.set_locked(sessions, s, "p1.1", True)
        with pytest.raises(segments.EditConflict):
            await segments.edit_segment(sessions, s, "p1.1", target="B")
        # A proposal made before the lock is not applied to the locked segment.
        s.state["doc:proposal"] = {"id": "p1", "notes": [], "glossary": {},
                                   "changes": [{"segment_id": "p1.1", "field": "target", "before": "A", "after": "Z"}]}
        result = await proposals.accept(sessions, artifacts, s)
        assert result["applied"] == 0 and st.get_segment(s.state, "p1.1")["target"] == "A"

    run(main())


def test_human_edit_drops_the_pending_agent_change_for_that_segment():
    async def main():
        sessions, _, s = await _doc(**{"p1.1": _seg("p1.1", "A"), "p1.2": _seg("p1.2", "B")})
        proposal = {"id": "p1", "notes": [], "glossary": {}, "changes": [
            {"segment_id": "p1.1", "field": "target", "before": "A", "after": "agent A"},
            {"segment_id": "p1.2", "field": "target", "before": "B", "after": "agent B"}]}
        s.state["doc:proposal"] = proposal
        await segments.edit_segment(sessions, s, "p1.1", target="human A")
        assert [c["segment_id"] for c in s.state["doc:proposal"]["changes"]] == ["p1.2"]
        await segments.edit_segment(sessions, s, "p1.2", target="human B")
        assert s.state["doc:proposal"] is None

    run(main())


def test_accepted_agent_change_is_a_draft_from_the_agent():
    async def main():
        sessions, artifacts, s = await _doc(**{"p1.1": _seg("p1.1", "A", "confirmed")})
        s.state["doc:proposal"] = {"id": "p1", "notes": ["formal"], "glossary": {},
                                   "changes": [{"segment_id": "p1.1", "field": "target", "before": "A", "after": "Formal A"}]}
        await proposals.accept(sessions, artifacts, s)
        seg = st.normalize(st.get_segment(s.state, "p1.1"))
        assert (seg["target"], seg["origin"], seg["status"]) == ("Formal A", "agent", "draft")

    run(main())

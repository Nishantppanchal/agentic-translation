"""Segment comments: stored apart from the segments, they follow their text through re-splits and retries."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.adk.sessions import InMemorySessionService

from translator.agents import editor, editor_tools
from translator.api import services
from translator.api.routes import segments as segment_routes
from translator.document import comments, edits, source_check
from translator.document import state as st

APP, USER = services.APP_NAME, services.USER


def _seg(sid: str, source: str, page: int = 1, **extra) -> dict:
    return {"id": sid, "page": page, "kind": "paragraph", "source": source, "target": f"EN {source}",
            "translatable": True, "status": "draft", "origin": "mt", **extra}


def _state(*segs: dict, **extra) -> dict:
    return {"doc:status": "ready", "doc:seg_ids": [s["id"] for s in segs], "doc:versions": [],
            **{st.seg_key(s["id"]): s for s in segs}, **extra}


def _apply(state: dict, delta: dict) -> dict:
    return {**state, **delta}


def test_add_resolve_delete_and_the_text_is_untouched():
    async def main():
        sessions = InMemorySessionService()
        s = await sessions.create_session(app_name="t", user_id="u", state=_state(_seg("p1.1", "Die Anlage ist abgenommen.")))
        seg = await edits.add_comment(sessions, s, "p1.1", "  Client prefers 'installation'  ", "reviewer")
        [c] = seg["comments"]
        assert (c["role"], c["text"], c["resolved"]) == ("reviewer", "Client prefers 'installation'", False)
        with pytest.raises(edits.EditConflict):
            await edits.add_comment(sessions, s, "p1.1", "  ")
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)  # persisted, not just in memory
        assert [x["text"] for x in s.state[comments.FIELD]] == ["Client prefers 'installation'"]
        seg = await edits.update_comment(sessions, s, "p1.1", c["id"], resolved=True)
        assert seg["comments"][0]["resolved"] and seg["target"] == "EN Die Anlage ist abgenommen."
        seg = await edits.update_comment(sessions, s, "p1.1", c["id"], delete=True)
        assert seg["comments"] == []
        with pytest.raises(KeyError):
            await edits.update_comment(sessions, s, "p1.1", "nope", resolved=True)

    asyncio.run(main())


def test_comments_kept_inside_segments_by_older_versions_are_migrated_on_the_first_write():
    old = _seg("p1.1", "Ergebnis", comments=[{"id": "c1", "role": "translator", "text": "Check this", "at": 1.0, "resolved": False}])
    state = _state(old, _seg("p1.2", "Fazit"))
    assert comments.for_segment(state, "p1.1")[0]["text"] == "Check this"  # read without migrating
    delta, _ = comments.add(state, "p1.2", "Second")
    assert [(c["seg_id"], c["text"]) for c in delta[comments.FIELD]] == [("p1.1", "Check this"), ("p1.2", "Second")]


def test_a_comment_follows_its_text_when_a_source_fix_re_splits_the_page():
    state = _state(_seg("p1.1", "Erster Absatz."), _seg("p1.2", "Die Kabelpritsche ist geerdet."), _seg("p2.1", "Seite zwei.", page=2))
    delta, _ = comments.add(state, "p1.2", "Is 'earthed' right here?")
    state = _apply(state, delta)
    # The page is read again with a paragraph inserted: the commented sentence is now p1.3.
    state = _apply(state, source_check.resegment(state, 1, "Erster Absatz.\n\nNeu eingefügt.\n\nDie Kabelpritsche ist geerdet."))
    placed, orphans = comments.place(state)
    assert [c["text"] for c in placed["p1.3"]] == ["Is 'earthed' right here?"] and "p1.2" not in placed and not orphans


def test_a_comment_whose_text_is_gone_is_an_orphan_and_can_still_be_deleted():
    state = _state(_seg("p1.1", "Erster Absatz."), _seg("p1.2", "Die Kabelpritsche ist geerdet."))
    delta, c = comments.add(state, "p1.2", "Earthed?")
    state = _apply(state, delta)
    state = _apply(state, source_check.resegment(state, 1, "Erster Absatz.\n\nGanz anderer Text auf dieser Seite."))
    placed, orphans = comments.place(state)
    assert not placed and [o["text"] for o in orphans] == ["Earthed?"]
    assert "(on text that has since changed) translator: Earthed?" in comments.open_text(state)
    state = _apply(state, comments.update(state, c["id"], delete=True))
    assert comments.place(state) == ({}, [])


def test_a_corrected_source_keeps_its_comments():
    state = _state(_seg("p1.1", "Die Kabelpritsche ist geerdt."))
    state = _apply(state, comments.add(state, "p1.1", "Typo in the scan")[0])
    state[st.seg_key("p1.1")] = _seg("p1.1", "Die Kabelpritsche ist geerdet.")  # the OCR typo fixed
    assert [c["text"] for c in comments.for_segment(state, "p1.1")] == ["Typo in the scan"]


def test_comments_survive_a_retry_that_reads_the_document_again():
    state = _state(_seg("p1.1", "Ergebnis"), _seg("p1.2", "Fazit"))
    state = _apply(state, comments.add(state, "p1.2", "Keep 'Conclusion'")[0])
    # Retry: the segments are rebuilt from a fresh reading (same text, here with a header line first).
    fresh = [_seg("p1.1", "Kopfzeile"), _seg("p1.2", "Ergebnis"), _seg("p1.3", "Fazit")]
    state = {**{k: v for k, v in state.items() if not k.startswith("seg:")}, **_state(*fresh)}
    assert [c["text"] for c in comments.for_segment(state, "p1.3")] == ["Keep 'Conclusion'"]


def test_the_editor_sees_open_comments_in_long_documents_and_in_its_reads():
    long = [_seg(f"p1.{i}", f"Satz Nummer {i} " + "mit vielen Wörtern " * 40) for i in range(1, 40)]
    state = _state(*long)
    state = _apply(state, comments.add(state, "p1.7", "Client wants 'plant', not 'facility'", "reviewer")[0])
    assert "only an outline is shown" in editor._document_view(state)
    ctx = SimpleNamespace(state=state, session=SimpleNamespace(events=[]), invocation_id="i")
    assert "[p1.7] reviewer: Client wants 'plant', not 'facility'" in editor.editor_instruction(ctx)

    class Ctx:
        def __init__(self, state):
            self.state = state

    view = editor_tools.get_segments(["p1.7"], Ctx(state))["segments"][0]
    assert view["open_comments"] == ["reviewer: Client wants 'plant', not 'facility'"]


def test_the_editor_tool_adds_an_agent_comment():
    state = _state(_seg("p1.1", "Ergebnis"))

    class Ctx:
        def __init__(self, state):
            self.state = state

    ctx = Ctx(dict(state))
    assert editor_tools.add_comment("p1.1", "Ambiguous: result or outcome?", ctx)["status"] == "added"
    assert editor_tools.add_comment("p9.9", "x", ctx)["status"] == "error"
    assert [(c["role"], c["text"]) for c in comments.for_segment(ctx.state, "p1.1")] == [("agent", "Ambiguous: result or outcome?")]


@pytest.fixture
def api(monkeypatch):
    sessions = InMemorySessionService()
    monkeypatch.setattr(services, "session_service", sessions)
    monkeypatch.setattr(segment_routes, "session_service", sessions)
    app = FastAPI()
    app.include_router(segment_routes.router)
    return TestClient(app), sessions


@pytest.mark.parametrize("status", ["awaiting_source_check", "awaiting_answers", "translating", "ready"])
def test_comments_can_be_added_in_any_status_when_nothing_is_running(api, status):
    client, sessions = api
    s = asyncio.run(sessions.create_session(app_name=APP, user_id=USER, state=_state(_seg("p1.1", "Ergebnis"), **{"doc:status": status})))
    r = client.post(f"/api/sessions/{s.id}/segments/p1.1/comments", json={"text": "Note", "role": "reviewer"})
    assert r.status_code == 200 and r.json()["segment"]["comments"][0]["text"] == "Note"


def test_comments_wait_while_a_run_is_active(api, monkeypatch):
    client, sessions = api
    s = asyncio.run(sessions.create_session(app_name=APP, user_id=USER, state=_state(_seg("p1.1", "Ergebnis"))))
    monkeypatch.setattr(services.runs, "is_running", lambda sid: True)
    r = client.post(f"/api/sessions/{s.id}/segments/p1.1/comments", json={"text": "Note"})
    assert r.status_code == 409

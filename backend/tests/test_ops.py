"""M6: tasks (rewrite with alternatives, consistency), proposals with choices, comments, multilingual
projects and the run queue."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.events import Event, EventActions
from google.adk.models import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import projects
from translator.agents import tasks
from translator.api.routes.projects import router
from translator.api.runs import RunManager
from translator.document import edits, proposals
from translator.document import state as st
from translator.models import structured
from translator.projects import ProjectStore


def _reply(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _prompt(llm_request) -> str:
    return "\n".join(p.text or "" for c in llm_request.contents for p in c.parts or [] if p.text)


def _seg(sid, source, target, status="draft", **extra):
    return {"id": sid, "page": 1, "kind": "paragraph", "source": source, "target": target, "translatable": True,
            "status": status, "origin": "mt", **extra}


SEGS = {
    "p1.1": _seg("p1.1", "Die Anlage ist abgenommen.", "The plant is accepted."),
    "p1.2": _seg("p1.2", "Die Kabelpritsche ist geerdet.", "The cable bridge is earthed."),
    "p1.3": _seg("p1.3", "Ergebnis", "Result", "confirmed"),
    "p2.1": _seg("p2.1", "Ergebnis", "Outcome"),
    "p2.2": _seg("p2.2", "Die Anlage ist abgenommen.", "The installation has been accepted."),
    "p2.3": _seg("p2.3", "Die Anlage ist abgenommen.", "The system is accepted."),
    "p2.4": _seg("p2.4", 'Die <g id="1">Frist</g> endet.', 'The <g id="1">deadline</g> ends.'),
    "p2.5": _seg("p2.5", "Gesperrt.", "Locked.", locked=True),
}


async def _ops_session(task: dict, **state):
    sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
    runner = Runner(app=App(name="t", root_agent=tasks.ops_workflow), session_service=sessions, artifact_service=artifacts)
    s = await sessions.create_session(app_name="t", user_id="u", state={
        "doc:status": "ready", "doc:seg_ids": list(SEGS), "doc:source_lang": "German", "doc:target_lang": "English",
        "doc:versions": [], "doc:task": task, **{st.seg_key(k): v for k, v in SEGS.items()}, **state})
    return sessions, artifacts, runner, s


async def _run(runner, sessions, s):
    events = [e async for e in runner.run_async(user_id="u", session_id=s.id,
                                                  new_message=types.Content(role="user", parts=[types.Part(text="task")]))]
    return events, await sessions.get_session(app_name="t", user_id="u", session_id=s.id)


def _said(events) -> list[str]:
    return [e.content.parts[0].text for e in events if e.content and e.content.parts and e.content.parts[0].text]


# --------------------------------------------------------------------------- #
# Proposals with alternatives
# --------------------------------------------------------------------------- #


def test_stage_alternatives_and_accept_a_choice():
    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:status": "ready", "doc:seg_ids": list(SEGS), "doc:versions": [], **{st.seg_key(k): v for k, v in SEGS.items()}})
        p = proposals.open_proposal(s.state, note="Rewrite: more formal")
        alts = [{"text": "The installation is hereby accepted.", "note": "formal"}, {"text": "Acceptance of the plant is confirmed.", "note": "nominal"},
                {"text": "The plant is accepted.", "note": "same as now"}]
        assert proposals.stage_change(p, s.state, "p1.1", "target", "", alts)
        change = p["changes"][0]
        assert change["after"] == alts[0]["text"] and [a["note"] for a in change["alternatives"]] == ["formal", "nominal"]  # unchanged option dropped
        assert not proposals.stage_change(p, s.state, "p2.5", "target", "x")  # locked
        s.state["doc:proposal"] = proposals.close_proposal(p)
        result = await proposals.accept(sessions, artifacts, s, None, {"p1.1|target": 1})
        assert result["applied"] == 1
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        assert st.get_segment(s.state, "p1.1")["target"] == "Acceptance of the plant is confirmed."

    asyncio.run(main())


# --------------------------------------------------------------------------- #
# Rewrite task
# --------------------------------------------------------------------------- #


def test_rewrite_with_alternatives_skips_locked_segments(monkeypatch):
    prompts_seen = []

    def fake(callback_context, llm_request):
        text = _prompt(llm_request)
        prompts_seen.append(text)
        ids = re.findall(r'<pair id="([^"]+)">', text)
        out = []
        for sid in ids:
            out += [f'<alt seg="{sid}" note="formal">Formal {sid}</alt>', f'<alt seg="{sid}" note="concise">Concise {sid}</alt>']
        return _reply("\n".join(out))

    monkeypatch.setattr(tasks.rewriter, "before_model_callback", fake)

    async def main():
        task = {"kind": "alternatives", "segment_ids": ["p1.1", "p2.4", "p2.5"], "instruction": "more formal", "n": 3}
        sessions, _, runner, s = await _ops_session(task)
        events, s = await _run(runner, sessions, s)
        assert "Request: more formal" in prompts_seen[0] and "3 alternative translations" in prompts_seen[0]
        assert all('<pair id="p2.5">' not in t for t in prompts_seen)  # locked: not even sent
        changes = {c["segment_id"]: c for c in s.state["doc:proposal"]["changes"]}
        assert [a["text"] for a in changes["p1.1"]["alternatives"]] == ["Formal p1.1", "Concise p1.1"]
        assert s.state["doc:proposal"]["notes"] == ["Rewrite: more formal"] and s.state["doc:task"] is None
        assert st.get_segment(s.state, "p1.1")["target"] == "The plant is accepted."  # nothing applied

    asyncio.run(main())


@pytest.mark.structured
def test_retranslate_one_result_with_json(monkeypatch):
    monkeypatch.setattr(structured, "enabled", lambda step: True)

    def fake(callback_context, llm_request):
        structured.inject_schema(callback_context, llm_request)
        assert llm_request.config.response_schema["title"] == "alternatives"
        return _reply(json.dumps({"segments": [{"id": "p1.1", "alternatives": [{"text": "The plant has been accepted.", "note": ""}]}]}))

    monkeypatch.setattr(tasks.rewriter, "before_model_callback", fake)

    async def main():
        sessions, _, runner, s = await _ops_session({"kind": "retranslate", "segment_ids": ["p1.1"], "instruction": "present perfect", "n": 1})
        _, s = await _run(runner, sessions, s)
        [change] = s.state["doc:proposal"]["changes"]
        assert (change["after"], change.get("alternatives")) == ("The plant has been accepted.", None)

    asyncio.run(main())


# --------------------------------------------------------------------------- #
# Consistency task
# --------------------------------------------------------------------------- #


def test_consistency_uses_confirmed_translations_asks_the_model_and_applies_terms(monkeypatch):
    pid = projects.get_store().create_project("P", "German")["id"]
    projects.get_store().upsert_term(pid, "Kabelpritsche", "cable tray", forbidden=["cable bridge"])
    calls = []

    def fake(callback_context, llm_request):
        text = _prompt(llm_request)
        calls.append(text)
        if "SAME source text" in text:
            ids = re.findall(r'<pair id="([^"]+)">', text)
            return _reply("\n".join(f'<seg id="{i}">The plant is accepted.</seg>' for i in ids))
        assert 'Termbase rule: Kabelpritsche → cable tray; never "cable bridge"' in text
        return _reply('<seg id="p1.2">The cable tray is earthed.</seg>')

    monkeypatch.setattr(tasks.consistency_fixer, "before_model_callback", fake)

    async def main():
        sessions, _, runner, s = await _ops_session({"kind": "consistency"}, **{"doc:project_id": pid})
        events, s = await _run(runner, sessions, s)
        changes = {c["segment_id"]: c["after"] for c in s.state["doc:proposal"]["changes"]}
        # "Ergebnis": a person confirmed "Result" (p1.3), so p2.1 follows it — no model call for that group.
        assert changes["p2.1"] == "Result" and "p1.3" not in changes
        assert changes["p2.2"] == changes["p2.3"] == "The plant is accepted." and "p1.1" not in changes  # unchanged
        assert changes["p1.2"] == "The cable tray is earthed."
        assert len(calls) == 2  # one same-source group + one term group
        assert any("aligned to your confirmed translation" in t for t in _said(events))

    asyncio.run(main())


def test_consistency_with_nothing_to_do():
    async def main():
        sessions, _, runner, s = await _ops_session({"kind": "consistency"})
        same = {k: {**SEGS[k], "target": SEGS[{"p2.1": "p1.3"}.get(k, "p1.1")]["target"]} for k in ("p2.1", "p2.2", "p2.3")}
        await sessions.append_event(s, Event(author="system", actions=EventActions(state_delta={st.seg_key(k): v for k, v in same.items()})))
        events, s = await _run(runner, sessions, s)
        assert any("nothing to fix" in t for t in _said(events)) and not s.state.get("doc:proposal")

    asyncio.run(main())


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #


def test_comments_add_resolve_and_delete():
    async def main():
        sessions = InMemorySessionService()
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:status": "ready", "doc:seg_ids": ["p1.1"], "doc:versions": [], st.seg_key("p1.1"): SEGS["p1.1"]})
        seg = await edits.add_comment(sessions, s, "p1.1", "  Client prefers 'installation'  ", "reviewer")
        [c] = seg["comments"]
        assert (c["role"], c["text"], c["resolved"]) == ("reviewer", "Client prefers 'installation'", False)
        with pytest.raises(edits.EditConflict):
            await edits.add_comment(sessions, s, "p1.1", "  ")
        seg = await edits.update_comment(sessions, s, "p1.1", c["id"], resolved=True)
        assert seg["comments"][0]["resolved"] and seg["target"] == "The plant is accepted."  # text untouched
        seg = await edits.update_comment(sessions, s, "p1.1", c["id"], delete=True)
        assert seg["comments"] == []
        with pytest.raises(KeyError):
            await edits.update_comment(sessions, s, "p1.1", "nope", resolved=True)

    asyncio.run(main())


# --------------------------------------------------------------------------- #
# English only (multilingual databases are migrated)
# --------------------------------------------------------------------------- #


def test_multilingual_databases_keep_only_english(tmp_path):
    """Projects from the multilingual version: English (and untagged) terms and TM units are kept, other
    target languages dropped; the per-language columns no longer show up."""
    db = tmp_path / "multi.db"
    con = sqlite3.connect(db)
    con.executescript("""
      create table projects (id text primary key, name text not null, source_lang text default '', target_lang text default '',
        instructions text default '', created_at real, auto_confirm_context integer default 1, lqa_threshold real default 90,
        target_langs text default '[]');
      create table project_documents (session_id text primary key, project_id text not null, created_at real);
      create table terms (id integer primary key, project_id text not null, target_lang text not null default '',
        source text not null, target text not null default '', note text default '', forbidden text default '[]',
        case_sensitive integer default 0, status text default 'approved', created_at real, updated_at real,
        unique(project_id, target_lang, source));
      create table tm_units (id integer primary key, project_id text not null, target_lang text not null default '',
        source text not null, target text not null, source_key text not null, prev_key text default '', origin text default '',
        created_at real, updated_at real, unique(project_id, target_lang, source_key, prev_key));
      insert into projects (id, name, source_lang, target_lang, instructions, created_at, target_langs)
        values ('p1', 'Old', 'German', 'English', 'Formal.', 1, '["English", "French"]');
      insert into terms (project_id, target_lang, source, target) values ('p1', 'English', 'Abnahme', 'acceptance');
      insert into terms (project_id, target_lang, source, target) values ('p1', 'French', 'Abnahme', 'réception');
      insert into terms (project_id, target_lang, source, target) values ('p1', 'French', 'Mangel', 'défaut');
      insert into tm_units (project_id, target_lang, source, target, source_key) values ('p1', 'English', 'Satz eins.', 'Sentence one.', 'satzeins');
      insert into tm_units (project_id, target_lang, source, target, source_key) values ('p1', 'French', 'Satz eins.', 'Phrase un.', 'satzeins');
    """)
    con.commit()
    con.close()
    store = ProjectStore(db)
    p = store.project("p1")
    assert "target_langs" not in p and "target_lang" not in p and p["terms"] == 1 and p["tm_units"] == 1
    assert [(t["source"], t["target"]) for t in store.terms("p1")] == [("Abnahme", "acceptance")]
    assert store.lookup("p1", "Satz eins.")[0]["target"] == "Sentence one."
    ProjectStore(db)  # opening again is a no-op


def test_project_api_is_english_only():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    pid = client.post("/api/projects", json={"name": "Acme", "source_lang": "German"}).json()["id"]
    client.post(f"/api/projects/{pid}/terms", json={"source": "Abnahme", "target": "acceptance"})
    assert client.get(f"/api/projects/{pid}/terms").json()[0]["target"] == "acceptance"
    assert "target_lang" not in client.get(f"/api/projects/{pid}").json()  # every project translates into English


# --------------------------------------------------------------------------- #
# Run queue
# --------------------------------------------------------------------------- #


def test_heavy_runs_are_queued_and_chat_turns_are_not():
    async def main():
        runs = RunManager(max_heavy=1)
        order: list[str] = []
        gate = asyncio.Event()

        def work(name: str, wait: bool = False):
            async def go(emit):
                order.append(f"start {name}")
                if wait:
                    await gate.wait()
                order.append(f"end {name}")
            return go

        runs.start("a", work("a", wait=True), heavy=True)
        runs.start("b", work("b"), heavy=True)
        runs.start("c", work("c"), heavy=False)
        await asyncio.sleep(0.05)
        assert order == ["start a", "start c", "end c"]  # b waits for a; the chat turn doesn't
        events = [e async for e in _take(runs.subscribe("b"), 1)]
        assert events[0]["type"] == "progress" and events[0]["progress"]["stage"] == "queued"
        gate.set()
        await asyncio.sleep(0.05)
        assert order[-2:] == ["end a", "start b"] or order[-3:] == ["end a", "start b", "end b"]

    async def _take(agen, n):
        i = 0
        async for item in agen:
            yield item
            i += 1
            if i >= n:
                break

    asyncio.run(main())

"""AI assist (agents/assist.py, api/routes/assist.py): suggested next prompts, Tab completions in the chat box and
the translation summary — model calls made straight from the API (a fake server here, never a real model), with
their tokens counted in projects.db — and the document's title and summary from the analysis."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.adk.events import Event
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import app_settings, exports, projects
from translator.agents import assist
from translator.agents.steps.analyse import _parse_analysis
from translator.api import services
from translator.api.routes import assist as assist_routes
from translator.api.routes import documents as document_routes
from translator.api.usage import summarize
from translator.document import notes
from translator.document import state as st
from translator.models import structured

from .fake_vllm import FakeVllm


def _models(url: str) -> dict:
    return {"defaults": {"retries": 0, "timeout": 10},
            "models": [{"id": "quick", "model_name": "vendor/quick", "url": url, "vision": True, "thinking": True}]}


def _state(**extra) -> dict:
    segs = [
        {"id": "p1.1", "page": 1, "kind": "heading", "source": "# Prüfbericht", "target": "# Inspection report",
         "translatable": True, "status": "confirmed"},
        {"id": "p1.2", "page": 1, "kind": "paragraph", "source": "Die Kabelpritsche ist nicht geerdet (3 Stück).",
         "target": "The cable tray is not earthed.", "translatable": True},
        {"id": "p1.3", "page": 1, "kind": "figure", "source": "Schaltbild", "target": "Circuit diagram", "translatable": True,
         "image": "figure-p1-1.png", "figure": 1},
    ]
    state = {
        "doc:filename": "pruefbericht.pdf", "doc:source_lang": "German", "doc:status": "ready",
        "doc:title": "Inspection report, Substation North", "doc:abstract": "A cable tray is not earthed.",
        "doc:brief": "Inspection report; formal.", "doc:seg_ids": [s["id"] for s in segs],
        "doc:versions": [{"version": 1, "note": "Draft translation", "artifact_version": 0}],
        "doc:glossary": {"Kabelpritsche": {"target": "cable tray", "note": ""}},
        "doc:questions": [
            {"id": "q1", "term": "Kabelpritsche", "status": "resolved", "answer": "cable tray", "answer_target": "cable tray",
             "segment_ids": ["p1.2"]},
            {"id": "q2", "term": "Erdung", "status": "open", "meaning": "earthing or grounding", "segment_ids": ["p1.2"]},
            {"id": "q3", "term": "Prüfer", "status": "dismissed", "guess": "inspector", "segment_ids": ["p1.1"]},
            {"id": "q4", "term": "Abgang", "status": "resolved", "answer": "applied in review", "answer_target": "feeder",
             "origin": "reviewer", "segment_ids": ["p1.2"]},
        ],
        "doc:key_terms": [{"term": "Anlage", "target": "installation", "meaning": "the plant", "decision": "ai"},
                          {"term": "Abnahme", "target": "acceptance", "meaning": "", "decision": "dictionary"}],
        "doc:comments": [{"id": "c1", "seg_id": "p1.2", "anchor": "", "role": "reviewer", "text": "Check the count", "at": 1,
                          "resolved": False}],
        "doc:office": {"not_translated": {"comments": 2}},
        **extra,
    }
    state.update({st.seg_key(s["id"]): s for s in segs})
    return state


def test_the_digest_has_decisions_assumptions_queries_and_quality():
    d = notes.digest(_state())
    assert {"term": "Kabelpritsche", "target": "cable tray", "note": "", "by": "the client's answer"} in d["decisions"]
    assert any(x["term"] == "Abnahme" and x["by"] == "the dictionary" for x in d["decisions"])
    # a skipped question, a reviewer's question settled without the client, the AI's own choice
    assert [x["term"] for x in d["assumptions"]] == ["Prüfer", "Abgang", "Anlage"]
    assert [x["term"] for x in d["answered"]] == ["Kabelpritsche"]
    assert [x["term"] for x in d["open_questions"]] == ["Erdung"]
    assert d["comments"] == [{"segment": "p1.2", "role": "reviewer", "text": "Check the count"}]
    assert any(x["check"] for x in d["qa_errors"])  # the number 3 is missing from the translation
    assert d["pictures"][0]["english"] == "Circuit diagram" and d["not_translated"] == {"comments": 2}
    text = notes.as_text(d)
    assert "Kabelpritsche → cable tray (decided by the client's answer)" in text and "Quality score (LQA): not run" in text
    assert "Terminology decisions" not in notes.as_text(d, for_notes=False)  # suggestions get the short version


@pytest.fixture
def api(use_models, fake_vllm, monkeypatch):
    use_models(_models(fake_vllm), {"default": {"model": "quick", "effort": "instant"}})
    sessions = InMemorySessionService()
    for module in (services, assist_routes, document_routes):
        monkeypatch.setattr(module, "session_service", sessions, raising=False)
    monkeypatch.setattr(assist, "_suggestions", assist._Lru(8))
    monkeypatch.setattr(assist, "_completions", assist._Lru(8))
    app = FastAPI()
    app.include_router(assist_routes.router)
    app.include_router(document_routes.router)

    def make(**state):
        return asyncio.run(sessions.create_session(app_name=services.APP_NAME, user_id=services.USER, state=_state(**state)))

    return TestClient(app), sessions, make


def _chat(sessions, session, *turns: tuple[str, str]):
    for author, text in turns:
        ev = Event(author=author, content=types.Content(role="user" if author == "user" else "model", parts=[types.Part(text=text)]))
        asyncio.run(sessions.append_event(session, ev))


def test_suggestions_follow_the_document_and_are_cached(api):
    client, sessions, make = api
    session = make()
    _chat(sessions, session, ("user", "Fix the QA errors"), ("editor", "Done. Shall I also check the terminology?"))
    FakeVllm.content = ('<suggestion label="Check terminology">Check that Kabelpritsche is translated as cable tray everywhere.'
                        '</suggestion>\n<suggestion label="Answer Erdung">Explain the term Erdung in p1.2.</suggestion>')
    r = client.post(f"/api/sessions/{session.id}/assist/suggestions").json()
    assert r == {"suggestions": [{"label": "Check terminology", "prompt": "Check that Kabelpritsche is translated as cable tray everywhere."},
                                 {"label": "Answer Erdung", "prompt": "Explain the term Erdung in p1.2."}], "cached": False}
    sent = FakeVllm.requests[-1]["body"]
    prompt = sent["messages"][-1]["content"]
    prompt = prompt if isinstance(prompt, str) else " ".join(p.get("text", "") for p in prompt)
    assert "Shall I also check the terminology?" in prompt and "Erdung" in prompt and sent["reasoning_effort"] == "none"
    again = client.post(f"/api/sessions/{session.id}/assist/suggestions").json()
    assert again["cached"] is True and len(FakeVllm.requests) == 1  # same last event: no new call
    usage = summarize([], projects.get_store().assist_usage(session.id))
    [row] = usage["rows"]
    assert (row["step"], row["model"], row["effort"], row["calls"], row["prompt_tokens"]) == ("Suggested prompts", "quick", "instant", 1, 7)


@pytest.mark.structured
def test_suggestions_in_json(api):
    client, _, make = api
    session = make()
    FakeVllm.content = json.dumps({"suggestions": [{"label": "Run the LQA", "prompt": "Score the translation quality."}] * 2})
    r = client.post(f"/api/sessions/{session.id}/assist/suggestions").json()
    assert r["suggestions"] == [{"label": "Run the LQA", "prompt": "Score the translation quality."}]  # duplicates dropped
    assert FakeVllm.requests[-1]["body"]["response_format"]["json_schema"]["schema"] == structured.suggestions_schema()


def test_no_suggestions_when_off_not_ready_or_failing(api):
    client, _, make = api
    assert client.post(f"/api/sessions/{make(**{'doc:status': 'translating'}).id}/assist/suggestions").json()["suggestions"] == []
    FakeVllm.fail_with = (500, {"message": "boom"})
    r = client.post(f"/api/sessions/{make().id}/assist/suggestions").json()
    assert r["suggestions"] == [] and "boom" in r["error"]
    FakeVllm.fail_with = None
    app_settings.save(app_settings.AppSettings(assist=False))
    assert client.post(f"/api/sessions/{make().id}/assist/suggestions").json() == {"suggestions": [], "disabled": True}
    assert client.post(f"/api/sessions/{make().id}/assist/complete", json={"text": "Explain the"}).json() == {"completion": ""}
    assert client.post("/api/sessions/nope/assist/suggestions").status_code == 404


def test_tab_completion(api):
    client, _, make = api
    session = make()
    url = f"/api/sessions/{session.id}/assist/complete"
    assert client.post(url, json={"text": "Exp"}).json() == {"completion": ""} and FakeVllm.requests == []  # too short
    FakeVllm.content = "<completion> the term Erdung in p1.2</completion>"
    assert client.post(url, json={"text": "Explain"}).json() == {"completion": " the term Erdung in p1.2"}
    assert FakeVllm.requests[-1]["body"]["max_completion_tokens"] == 48  # small, at Instant
    assert client.post(url, json={"text": "Explain"}).json()["completion"] == " the term Erdung in p1.2"
    assert len(FakeVllm.requests) == 1  # cached
    FakeVllm.fail_with = (500, {"message": "boom"})
    assert client.post(url, json={"text": "Make it shorter"}).json() == {"completion": ""}


@pytest.mark.parametrize("reply, typed, out", [
    ("<completion> the term in p1.2</completion>", "Explain", " the term in p1.2"),
    ("<completion>ain p1.2</completion>", "Expl", "ain p1.2"),  # finishing the word
    ("<completion> p1.2 please</completion>", "Explain ", "p1.2 please"),  # the space is typed already
    ("Explain the term in p1.2", "Explain", " the term in p1.2"),  # no tag, the whole message repeated
    ("<completion>more formal</completion>", "Shorter,", " more formal"),
    ("<completion></completion>", "Explain", ""),
    ("<completion> " + " ".join(["word"] * 20) + "</completion>", "Say", " " + " ".join(["word"] * 12)),
])
def test_completions_are_tidied(reply, typed, out):
    assert assist.tidy_completion(reply, typed) == out


def test_notes_for_the_client_are_stored_and_exported(api, monkeypatch):
    client, sessions, make = api
    session = make()
    formats = {f["id"]: f for f in exports.available(session)}
    assert formats["notes"]["available"] is False
    FakeVllm.content = "# Translation summary: Inspection report\n\n## Open queries\n\n- Erdung: earthing or grounding?"
    r = client.post(f"/api/sessions/{session.id}/assist/notes").json()
    assert r["stored"] is True and r["version"] == 1 and r["text"].startswith("# Translation summary")
    prompt = FakeVllm.requests[-1]["body"]["messages"][-1]["content"]
    prompt = prompt if isinstance(prompt, str) else " ".join(p.get("text", "") for p in prompt)
    assert "Prüfer → inspector (the question was skipped)" in prompt and "Check the count" in prompt
    s = asyncio.run(sessions.get_session(app_name=services.APP_NAME, user_id=services.USER, session_id=session.id))
    assert s.state["doc:client_notes"]["text"] == r["text"]
    assert {f["id"]: f for f in exports.available(s)}["notes"]["available"] is True
    content, media, name = asyncio.run(exports.build(None, s, "notes", None))
    assert content.decode() == r["text"] and media.startswith("text/markdown") and name == "pruefbericht.translation-summary.md"

    other = make()
    with pytest.raises(exports.ExportError):
        asyncio.run(exports.build(None, other, "notes", None))
    monkeypatch.setattr(services.runs, "is_running", lambda sid: True)  # a run started meanwhile: not stored
    assert client.post(f"/api/sessions/{other.id}/assist/notes").json()["stored"] is False
    empty = make(**{"doc:seg_ids": []})
    assert client.post(f"/api/sessions/{empty.id}/assist/notes").status_code == 409


def test_session_summary_has_the_title_and_retry_clears_it(api, monkeypatch):
    client, sessions, make = api
    session = make(**{"doc:status": "error", "doc:client_notes": {"text": "x"}})
    assert services.summary(session)["title"] == "Inspection report, Substation North"
    assert services.summary(session)["abstract"] == "A cable tray is not earthed."
    monkeypatch.setattr(document_routes, "start_run", lambda *a, **k: None)
    assert client.post(f"/api/sessions/{session.id}/retry").status_code == 200
    s = asyncio.run(sessions.get_session(app_name=services.APP_NAME, user_id=services.USER, session_id=session.id))
    assert (s.state["doc:title"], s.state["doc:abstract"], s.state["doc:client_notes"]) == (None, None, None)


def test_the_analysis_gives_a_title_and_summary():
    tags = ("<source_lang>German</source_lang>\n<brief>A report.</brief>\n<title>“Defect re-inspection report.”</title>\n"
            "<summary>Lists defects.\n  Two remain open.</summary>")
    a = _parse_analysis(tags)
    assert (a.lang, a.title, a.summary) == ("German", "Defect re-inspection report", "Lists defects.\n  Two remain open.")
    obj = json.dumps({"source_language": "German", "brief": "b", "terms": [], "title": "Inspection report", "summary": "S."})
    assert (_parse_analysis(obj).title, _parse_analysis(obj).summary) == ("Inspection report", "S.")
    assert _parse_analysis("<brief>only a brief</brief>").title is None
    schema = structured.analysis_schema(["p1.1"])
    assert {"title", "summary"} <= set(schema["required"])


def test_assist_usage_is_merged_into_the_documents_usage():
    store = projects.get_store()
    store.record_assist_usage("s1", "suggest", "quick", "instant", 10, 5, 0)
    store.record_assist_usage("s1", "suggest", "quick", "instant", 10, 5, 0)
    store.record_assist_usage("s1", "notes", "quick", None, 100, 50, 20)
    rows = {(r["step"], r["effort"]): r for r in summarize([], store.assist_usage("s1"))["rows"]}
    assert rows[("Suggested prompts", "instant")]["calls"] == 2 and rows[("Suggested prompts", "instant")]["tokens"] == 30
    assert rows[("Translation summary", None)]["reasoning_tokens"] == 20 and store.assist_usage("s2") == []


def test_assist_calls_leave_no_session_event(api):
    client, sessions, make = api
    session = make()
    FakeVllm.content = "<completion> the term</completion>"
    client.post(f"/api/sessions/{session.id}/assist/complete", json={"text": "Explain"})
    s = asyncio.run(sessions.get_session(app_name=services.APP_NAME, user_id=services.USER, session_id=session.id))
    assert s.events == []


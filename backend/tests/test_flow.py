"""Offline end-to-end smoke test: the real ADK workflow + editor with a scripted fake model.

Every worker agent gets a `before_model_callback` that returns canned output, so
the graph, HITL pause/resume, state, artifacts and versioning are exercised
without any network or local model.
"""

from __future__ import annotations

import asyncio
import json
import re

import pymupdf
import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.models import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import projects, proposals
from translator import state as st
from translator.agents import pipeline
from translator.agents.editor import editor_agent
from translator.timeline import history

APP = "translator"


def _reply(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _prompt(llm_request) -> str:
    return "\n".join(p.text or "" for c in llm_request.contents for p in c.parts or [] if p.text)


def fake_ocr(callback_context, llm_request):
    page = re.search(r"Transcribe page (\d+)", _prompt(llm_request)).group(1)
    if page == "1":
        return _reply("# Abnahmeprotokoll\n\nDie Kabelpritsche ist nicht geerdet.\n\n| Nr. | Frist |\n|---|---|\n| 1 | 30.04. |")
    return _reply("## Ergebnis\n\nDie Anlage wird abgenomen.")


def fake_ocr_check(callback_context, llm_request):
    text = _prompt(llm_request)
    if "abgenomen" in text:
        return _reply(
            "<verdict>fixed</verdict>\n<issues>\n- abgenomen → abgenommen\n</issues>\n"
            "<markdown>\n## Ergebnis\n\nDie Anlage wird abgenommen.\n</markdown>"
        )
    return _reply("<verdict>ok</verdict>")


TRANSLATE_PROMPTS: list[str] = []


def fake_translate(callback_context, llm_request):
    text = _prompt(llm_request)
    TRANSLATE_PROMPTS.append(text)
    segs = re.findall(r'<seg id="([^"]+)">\n(.*?)\n</seg>', text, re.S)
    clarified = "cable tray" in text
    out = []
    for sid, src in segs:
        en = src.replace("Abnahmeprotokoll", "Acceptance report").replace("Ergebnis", "Result")
        en = en.replace("Die Kabelpritsche ist nicht geerdet.", "The cable tray is not earthed." if clarified else "The cable bridge is not earthed.")
        en = en.replace("Die Anlage wird abgenommen.", "The system is accepted.")
        out.append(f'<seg id="{sid}">{en}</seg>')
    if any("Abnahmeprotokoll" in s for _, s in segs):
        out.append('<keep source="Abnahmeprotokoll">Acceptance report</keep>')
    if any("Kabelpritsche" in s for _, s in segs) and not clarified:
        out.append('<keep source="Kabelpritsche">cable bridge</keep>')  # unsure → must not be carried
        out.append('<term source="Kabelpritsche" guess="cable bridge" segs="p1.2">Unusual compound</term>')
    out.append("<source_lang>German</source_lang>")
    return _reply("\n".join(out))


def fake_review(callback_context, llm_request):
    text = _prompt(llm_request)
    if "| Nr. | Frist |" in text and "| No. |" not in text:
        return _reply('<issue seg="p1.3" severity="major">Table header not translated → | No. | Deadline |</issue>')
    return _reply("<none/>")


def fake_refine(callback_context, llm_request):
    return _reply('<seg id="p1.3">| No. | Deadline |\n|---|---|\n| 1 | 30.04. |</seg>')


class FakeEditor:
    """First call: tool calls (edit + glossary); second call: a text summary."""

    def __call__(self, callback_context, llm_request):
        contents = llm_request.contents
        if any(p.function_response for c in contents for p in c.parts or []):
            return _reply("I've proposed changing **p2.2** to “The plant is accepted.” — review the diff.")
        calls = [
            ("update_segment", {"segment_id": "p2.2", "new_translation": "The plant is accepted."}),
            ("set_glossary_term", {"source_term": "Abnahmeprotokoll", "translation": "acceptance certificate", "note": ""}),
        ]
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in calls],
            )
        )


@pytest.fixture(autouse=True)
def fake_models(monkeypatch):
    monkeypatch.setattr(pipeline.ocr_extractor, "before_model_callback", fake_ocr)
    monkeypatch.setattr(pipeline.figure_detector, "before_model_callback", lambda *_: _reply("<none/>"))
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", fake_ocr_check)
    monkeypatch.setattr(pipeline.translator, "before_model_callback", fake_translate)
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", fake_review)
    monkeypatch.setattr(pipeline.refiner, "before_model_callback", fake_refine)
    monkeypatch.setattr(editor_agent, "before_model_callback", FakeEditor())


def _pdf() -> bytes:
    doc = pymupdf.open()
    for text in ("Abnahmeprotokoll", "Ergebnis"):
        doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


async def _run(runner: Runner, sid: str, message: types.Content) -> list:
    return [ev async for ev in runner.run_async(user_id="u", session_id=sid, new_message=message)]


def test_ingest_clarify_review_and_edit():
    store = projects.get_store()
    pid = store.create_project("Acme", "German")["id"]

    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        ingest = Runner(app=App(name=APP, root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        editor = Runner(app=App(name=APP, root_agent=editor_agent), session_service=sessions, artifact_service=artifacts)

        session = await sessions.create_session(
            app_name=APP,
            user_id="u",
            state={
                "doc:filename": "test.pdf",
                "doc:source_artifact": "source.pdf",
                "doc:source_lang": "auto-detect",
                "doc:target_lang": "English",
                "doc:questions": [],
                "doc:versions": [],
                "doc:project_id": pid,
            },
        )
        await artifacts.save_artifact(
            app_name=APP, user_id="u", session_id=session.id, filename="source.pdf",
            artifact=types.Part.from_bytes(data=_pdf(), mime_type="application/pdf"),
        )

        # 1) Ingest runs OCR + translation, then pauses at `clarify`.
        TRANSLATE_PROMPTS.clear()
        events = await _run(ingest, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await sessions.get_session(app_name=APP, user_id="u", session_id=session.id)
        assert s.state["doc:status"] == "awaiting_answers"
        assert s.state["doc:detected_lang"] == "German"
        assert [r["ok"] for r in s.state["doc:ocr_report"]] == [True, False]
        assert st.get_segment(s.state, "p2.2")["source"] == "Die Anlage wird abgenommen."  # OCR fix applied
        assert st.get_segment(s.state, "p1.2")["target"] == "The cable bridge is not earthed."
        # Page by page, in order, with carried context + termbase.
        assert len(TRANSLATE_PROMPTS) == 2
        assert "Segments to translate (page 1)" in TRANSLATE_PROMPTS[0]
        assert "(start of document)" in TRANSLATE_PROMPTS[0]
        page2 = TRANSLATE_PROMPTS[1]
        assert "Segments to translate (page 2)" in page2
        assert "TRANSLATION: # Acceptance report" in page2  # previous page's translation carried
        assert "- Abnahmeprotokoll → Acceptance report" in page2  # termbase carried
        assert s.state["doc:termbase"] == {"Abnahmeprotokoll": "Acceptance report"}  # flagged guess not carried
        assert "cable bridge" not in page2.split("Previous text")[0]
        [q] = st.open_questions(s.state)
        assert q["term"] == "Kabelpritsche"
        interrupt = next(
            fc.id for ev in events for fc in ev.get_function_calls() if fc.name == "adk_request_input"
        )

        # 2) Resume with the answer → glossary, re-translation, review → refine loop → finalize.
        resume = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=interrupt, name="adk_request_input", response={"result": {q["id"]: "cable tray"}}))])
        await _run(ingest, session.id, resume)
        s = await sessions.get_session(app_name=APP, user_id="u", session_id=session.id)
        assert s.state["doc:status"] == "ready", s.state.get("doc:progress")
        assert s.state["doc:glossary"]["Kabelpritsche"]["note"] == "cable tray"
        # The answer also goes to the project termbase (as an explanation) for later documents.
        assert [(t["source"], t["target"], t["note"], t["status"]) for t in store.terms(pid)] == [
            ("Kabelpritsche", "", "cable tray", "note")]
        assert st.get_segment(s.state, "p1.2")["target"] == "The cable tray is not earthed."
        assert st.get_segment(s.state, "p1.3")["target"].startswith("| No. | Deadline |")
        notes = [v["note"] for v in s.state["doc:versions"]]
        assert notes == ["Draft translation", "Applied your clarifications", "AI review fixes"], notes
        assert [r["round"] for r in s.state["doc:review_report"]] == [1, 2]

        # 3) Chat edit → staged proposal (nothing applied yet) → accept → new version.
        before = st.get_segment(s.state, "p2.2")["target"]
        await _run(editor, session.id, types.Content(role="user", parts=[types.Part(text="Use 'plant' in p2.2")]))
        s = await sessions.get_session(app_name=APP, user_id="u", session_id=session.id)
        assert st.get_segment(s.state, "p2.2")["target"] == before  # not applied without approval
        proposal = s.state["doc:proposal"]
        assert [(c["segment_id"], c["before"], c["after"]) for c in proposal["changes"]] == [
            ("p2.2", before, "The plant is accepted.")
        ]
        assert proposal["notes"] == ["Use 'plant' in p2.2"]
        assert len(s.state["doc:versions"]) == 3

        result = await proposals.accept(sessions, artifacts, s)
        assert result == {"version": 4, "applied": 1, "dropped": 0}
        s = await sessions.get_session(app_name=APP, user_id="u", session_id=session.id)
        assert st.get_segment(s.state, "p2.2")["target"] == "The plant is accepted."
        assert s.state["doc:proposal"] is None
        assert s.state["doc:glossary"]["Abnahmeprotokoll"]["target"] == "acceptance certificate"
        assert {t["source"]: t["target"] for t in store.terms(pid)}["Abnahmeprotokoll"] == "acceptance certificate"
        assert s.state["doc:termbase"] == {}  # glossary supersedes the translator's own choice
        last = s.state["doc:versions"][-1]
        assert last["version"] == 4 and last["changed"] == ["p2.2"], last
        snap = await artifacts.load_artifact(
            app_name=APP, user_id="u", session_id=session.id, filename=st.TRANSLATION_ARTIFACT,
            version=last["artifact_version"],
        )
        assert json.loads(snap.text)["p2.2"] == "The plant is accepted."
        assert last["note"] == "Edit: Use 'plant' in p2.2"

        # 3b) Another proposal, rejected → nothing changes.
        await _run(editor, session.id, types.Content(role="user", parts=[types.Part(text="Undo that")]))
        s = await sessions.get_session(app_name=APP, user_id="u", session_id=session.id)
        assert s.state["doc:proposal"]["glossary"]  # re-proposed glossary entry (segment already matches)
        await proposals.reject(sessions, s)
        s = await sessions.get_session(app_name=APP, user_id="u", session_id=session.id)
        assert s.state["doc:proposal"] is None and s.state["doc:last_proposal"]["outcome"] == "rejected"
        assert len(s.state["doc:versions"]) == 4

        # 4) Timeline rebuilt from history has the user turn, tool call, versions and summaries.
        items = history(s.events)
        kinds = [i["kind"] for i in items]
        assert kinds.count("version") == 4
        activity = [i["text"] for i in items if i["kind"] == "activity"]
        assert "Accepted 1 change → v4; glossary +1" in activity
        assert "Rejected the proposal (1 glossary entry)" in activity
        assert "tool" in kinds and "user" in kinds and "assistant" in kinds
        assert not any(i.get("name") == "adk_request_input" for i in history(s.events))

    asyncio.run(main())


def test_noop_refine_skips_second_review(monkeypatch):
    """No flagged terms → no pause; a refiner that changes nothing ends the loop without re-review."""

    def translate_no_terms(callback_context, llm_request):
        reply = fake_translate(callback_context, llm_request)
        text = reply.content.parts[0].text
        return _reply("\n".join(line for line in text.splitlines() if not line.startswith("<term")))

    def echo_refine(callback_context, llm_request):
        pairs = re.findall(r'<pair id="([^"]+)">.*?TRANSLATION:\n(.*?)\n</pair>', _prompt(llm_request), re.S)
        return _reply("\n".join(f'<seg id="{sid}">{t}</seg>' for sid, t in pairs))

    reviews = []

    def counting_review(callback_context, llm_request):
        reviews.append(1)
        return fake_review(callback_context, llm_request)

    monkeypatch.setattr(pipeline.translator, "before_model_callback", translate_no_terms)
    monkeypatch.setattr(pipeline.refiner, "before_model_callback", echo_refine)
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", counting_review)

    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        ingest = Runner(app=App(name=APP, root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        session = await sessions.create_session(
            app_name=APP, user_id="u",
            state={"doc:filename": "t.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "German",
                   "doc:target_lang": "English", "doc:questions": [], "doc:versions": []},
        )
        await artifacts.save_artifact(
            app_name=APP, user_id="u", session_id=session.id, filename="source.pdf",
            artifact=types.Part.from_bytes(data=_pdf(), mime_type="application/pdf"),
        )
        await _run(ingest, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await sessions.get_session(app_name=APP, user_id="u", session_id=session.id)
        assert s.state["doc:status"] == "ready"
        assert [v["note"] for v in s.state["doc:versions"]] == ["Draft translation"]
        assert [r["round"] for r in s.state["doc:review_report"]] == [1]  # no re-review after a no-op refine
        assert len(reviews) == 2  # one review call per page

    asyncio.run(main())

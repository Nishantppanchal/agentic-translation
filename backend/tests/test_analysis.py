"""The workflow upgrades: whole-document analysis with questions before translating, answers someone
who doesn't read the source language can give (options + a recommendation), the OCR check skipped
only when the transcription and the text layer are the same text, per-page OCR caching for retries,
and the consistency polish before the document is handed over."""

from __future__ import annotations

import asyncio
import re

import pymupdf
import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.events import Event, EventActions
from google.adk.models import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import projects, qa
from translator import state as st
from translator.agents import pipeline
from translator.agents.ops import consistency_fixer
from translator.formats import parse_terms
from translator.timeline import pending_interrupt
from .fakes import fake_ocr

APP = "translator"
PAGE1 = "# Abnahmeprotokoll\n\nDie Kabelpritsche ist nicht geerdet."
PAGE2 = "## Ergebnis\n\nDie Anlage wird abgenommen."


def _reply(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _prompt(llm_request) -> str:
    return "\n".join(p.text or "" for c in llm_request.contents for p in c.parts or [] if p.text)


def _pdf(*pages: str) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


class Calls:
    def __init__(self):
        self.ocr: list[str] = []
        self.check: list[str] = []
        self.analyse: list[str] = []
        self.translate: list[str] = []


@pytest.fixture()
def calls(monkeypatch) -> Calls:
    c = Calls()

    def ocr(page):
        c.ocr.append(str(page.number))
        return PAGE1 if page.number == 1 else PAGE2

    def check(callback_context, llm_request):
        c.check.append(_prompt(llm_request))
        return _reply("<verdict>ok</verdict>")

    def analyse(callback_context, llm_request):
        c.analyse.append(_prompt(llm_request))
        return _reply(
            "<source_lang>German</source_lang>\n"
            "<brief>Acceptance report for a substation; a cable tray is not earthed.</brief>\n"
            '<term source="Abnahmeprotokoll" guess="Acceptance report" meaning="The formal record of an acceptance" '
            'gist="Acceptance report" ambiguous="no" segs="p1.1">standard</term>\n'
            '<term source="Kabelpritsche" guess="cable tray" alt="cable ladder | cable bridge" '
            'meaning="A metal tray that carries cables" gist="The cable tray is not earthed." ambiguous="yes" '
            'segs="p1.2">tray, ladder and bridge are different products</term>'
        )

    def translate(callback_context, llm_request):
        text = _prompt(llm_request)
        c.translate.append(text)
        segs = re.findall(r'<seg id="([^"]+)">\n(.*?)\n</seg>', text, re.S)
        tray = "cable ladder" if "Kabelpritsche → cable ladder" in text else "cable tray"
        out = []
        for sid, src in segs:
            en = src.replace("Abnahmeprotokoll", "Acceptance report").replace("Ergebnis", "Result")
            en = en.replace("Die Kabelpritsche ist nicht geerdet.", f"The {tray} is not earthed.")
            en = en.replace("Die Anlage wird abgenommen.", "The system is accepted.")
            out.append(f'<seg id="{sid}">{en}</seg>')
        # The analysis already settled this one: flagging it again must not ask the user twice.
        out.append('<term source="Abnahmeprotokoll" guess="Acceptance report" segs="p1.1">record or certificate?</term>')
        return _reply("\n".join(out))

    fake_ocr(monkeypatch, ocr)
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", check)
    monkeypatch.setattr(pipeline.analyst, "before_model_callback", analyse)
    monkeypatch.setattr(pipeline.translator, "before_model_callback", translate)
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", lambda *_: _reply("<none/>"))
    monkeypatch.setattr(pipeline.refiner, "before_model_callback", lambda *_: _reply(""))
    return c


async def _setup(data: bytes, pid: str | None = None):
    sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
    runner = Runner(app=App(name=APP, root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
    state = {"doc:filename": "t.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "auto-detect",
             "doc:target_lang": "English", "doc:questions": [], "doc:versions": []}
    if pid:
        state["doc:project_id"] = pid
    session = await sessions.create_session(app_name=APP, user_id="u", state=state)
    await artifacts.save_artifact(app_name=APP, user_id="u", session_id=session.id, filename="source.pdf",
                                  artifact=types.Part.from_bytes(data=data, mime_type="application/pdf"))
    return sessions, artifacts, runner, session


async def _run(runner, sid, message) -> list:
    return [ev async for ev in runner.run_async(user_id="u", session_id=sid, new_message=message)]


def _answer(interrupt: str, answers: dict) -> types.Content:
    return types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=interrupt, name="adk_request_input", response={"result": answers}))])


async def _get(sessions, sid):
    return await sessions.get_session(app_name=APP, user_id="u", session_id=sid)


@pytest.mark.analysis
def test_analysis_asks_before_translating_and_answers_shape_the_first_draft(calls):
    store = projects.get_store()
    pid = store.create_project("Acme", "German")["id"]

    async def main():
        sessions, _, runner, session = await _setup(_pdf("Abnahmeprotokoll", "Ergebnis"), pid)
        events = await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await _get(sessions, session.id)
        # Paused BEFORE any translation, with a question someone without German can answer.
        assert s.state["doc:status"] == "awaiting_answers" and calls.translate == []
        assert len(calls.analyse) == 1 and "Kabelpritsche" in calls.analyse[0] and "Ergebnis" in calls.analyse[0]  # whole doc
        [q] = st.open_questions(s.state)
        assert q["term"] == "Kabelpritsche" and q["origin"] == "analysis" and q["recommended"] == 0
        assert [o["target"] for o in q["options"]] == ["cable tray", "cable ladder", "cable bridge"]
        assert q["meaning"] == "A metal tray that carries cables" and q["gist"] == "The cable tray is not earthed."
        assert s.state["doc:brief"].startswith("Acceptance report") and s.state["doc:detected_lang"] == "German"
        assert s.state["doc:termbase"] == {"Abnahmeprotokoll": "Acceptance report"}  # the clear term is fixed
        assert [k["term"] for k in s.state["doc:key_terms"]] == ["Abnahmeprotokoll", "Kabelpritsche"]
        interrupt = pending_interrupt(s.events)
        assert interrupt == pipeline.ASK_INTERRUPT and interrupt == next(
            fc.id for ev in events for fc in ev.get_function_calls() if fc.name == "adk_request_input")

        # The person picks another option: the first draft uses it — no re-translation pass.
        await _run(runner, session.id, _answer(interrupt, {q["id"]: {"target": "cable ladder", "note": ""}}))
        s = await _get(sessions, session.id)
        assert s.state["doc:status"] == "ready"
        assert "Kabelpritsche → cable ladder" in calls.translate[0]  # glossary from the first page on
        assert "Acceptance report for a substation" in calls.translate[0]  # the brief is there up front
        assert st.get_segment(s.state, "p1.2")["target"] == "The cable ladder is not earthed."
        assert [v["note"] for v in s.state["doc:versions"]] == ["Draft translation"]
        assert st.open_questions(s.state) == []  # the translator's flag on a decided term was dropped
        assert s.state["doc:glossary"]["Kabelpritsche"] == {"target": "cable ladder", "note": ""}
        [term] = store.terms(pid)  # the decision is kept for the project, with the meaning as its note
        assert (term["source"], term["target"], term["status"], term["note"]) == (
            "Kabelpritsche", "cable ladder", "approved", "A metal tray that carries cables")
        assert pending_interrupt(s.events) is None

    asyncio.run(main())


@pytest.mark.analysis
def test_skipped_questions_keep_the_recommendation(calls):
    async def main():
        sessions, _, runner, session = await _setup(_pdf("Abnahmeprotokoll", "Ergebnis"))
        await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await _get(sessions, session.id)
        [q] = st.open_questions(s.state)
        await _run(runner, session.id, _answer(pending_interrupt(s.events), {q["id"]: None}))
        s = await _get(sessions, session.id)
        assert s.state["doc:termbase"]["Kabelpritsche"] == "cable tray"  # recommendation kept, unverified
        assert "Kabelpritsche" not in s.state["doc:glossary"]
        assert st.get_segment(s.state, "p1.2")["target"] == "The cable tray is not earthed."

    asyncio.run(main())


def test_analysis_off_goes_straight_to_translation(calls):
    async def main():
        sessions, _, runner, session = await _setup(_pdf("Abnahmeprotokoll", "Ergebnis"))
        await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await _get(sessions, session.id)
        assert calls.analyse == [] and calls.translate and s.state["doc:status"] == "awaiting_answers"
        [q] = st.open_questions(s.state)  # without the analysis, the translator's flag is asked after the draft
        assert q["origin"] == "translator" and q["term"] == "Abnahmeprotokoll"

    asyncio.run(main())


@pytest.mark.analysis
def test_a_failed_analysis_is_shown_and_translation_goes_on(calls, monkeypatch):
    from translator.llm import EndpointError

    def too_long(*_):
        raise EndpointError("translate model Qwen/Qwen3-32B at http://gpu:8100/v1: HTTP 400 ContextWindowExceededError: "
                            "This model's maximum context length is 32768 tokens.")

    monkeypatch.setattr(pipeline.analyst, "before_model_callback", too_long)

    async def main():
        sessions, _, runner, session = await _setup(_pdf("Abnahmeprotokoll", "Ergebnis"))
        events = await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        notes = [p.text for ev in events if ev.content for p in ev.content.parts or [] if p.text and "couldn't read" in p.text]
        assert len(notes) == 1 and "maximum context length is 32768" in notes[0] and "ANALYSIS_CHUNK_CHARS" in notes[0]
        s = await _get(sessions, session.id)
        assert calls.translate and not s.state.get("doc:key_terms")  # translated anyway, without the analysis

    asyncio.run(main())


def test_a_failed_run_reports_the_servers_error(calls, monkeypatch):
    from translator.llm import EndpointError, error_text

    message = "translate model Qwen/Qwen3-32B at http://gpu:8100/v1: InternalServerError: Cannot connect to host gpu:8100"

    def down(*_):
        raise EndpointError(message)

    monkeypatch.setattr(pipeline.translator, "before_model_callback", down)

    async def main():
        _, _, runner, session = await _setup(_pdf("Abnahmeprotokoll", "Ergebnis"))
        with pytest.raises(Exception) as err:
            await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        assert error_text(err.value) == message  # what the app shows (runs.py): the server's error as is

    asyncio.run(main())


def test_ocr_check_is_skipped_only_when_the_text_layer_says_the_same(calls):
    async def main():
        # Page 1's text layer is exactly what OCR reads; page 2's says something else (a misread word).
        pdf = _pdf(PAGE1.replace("# ", ""), "Ergebnis\nDie Anlage wird abgenomen.")
        sessions, _, runner, session = await _setup(pdf)
        await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await _get(sessions, session.id)
        report = {r["page"]: r for r in s.state["doc:ocr_report"]}
        assert report[1].get("checked") == "text layer" and report[1]["agreement"] == 100.0
        assert "checked" not in report[2] and len(calls.check) == 1 and "abgenommen" in calls.check[0]

    asyncio.run(main())


def test_layer_agreement_ignores_layout_but_not_words():
    md = "# Prüfbericht\n\n| Nr. | Frist |\n|---|---|\n| 1 | 30.04.2026 |\n\nDie Mängel sind zu besei-\ntigen."
    layer = "Prüfbericht\nNr.\nFrist\n1\n30.04.2026\nDie Mängel sind zu besei-\ntigen."
    assert pipeline.layer_agreement(md, layer) == 100
    assert pipeline.layer_agreement(md, layer.replace("30.04", "30.07")) < 100
    assert pipeline.layer_agreement(md, layer.replace("Mängel", "Mangel")) < 100
    assert pipeline.layer_agreement("ﬁnal", "final") == 100  # ligature in the text layer
    assert pipeline.layer_agreement(md, "") == 0
    # Numbered headings are content on both sides; a hyphen between letters may be a line-end break.
    assert pipeline.layer_agreement("## 1. Gegenstand\n\nDie USV-Anlage", "1. Gegenstand\nDie USV-\nAnlage") == 100
    assert pipeline.layer_agreement("## 1. Gegenstand", "Gegenstand") < 100
    assert pipeline.layer_agreement("Temperatur −20 °C", "Temperatur 20 °C") < 100  # a minus sign still counts


def test_retry_reuses_ocr_of_pages_already_read(calls):
    async def main():
        sessions, _, runner, session = await _setup(_pdf("Abnahmeprotokoll", "Ergebnis"))
        await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        assert sorted(calls.ocr) == ["1", "2"]
        # Retry: the same document read again (as `POST /retry` does after a failure).
        s = await _get(sessions, session.id)
        reset = {"doc:seg_ids": [], "doc:questions": [], "doc:versions": []}
        await sessions.append_event(s, Event(author="system", actions=EventActions(state_delta=reset)))
        await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Retry")]))
        s = await _get(sessions, session.id)
        assert sorted(calls.ocr) == ["1", "2"]  # no page was read twice
        assert all(r.get("cached") for r in s.state["doc:ocr_report"])
        assert st.get_segment(s.state, "p2.2")["source"] == "Die Anlage wird abgenommen."

    asyncio.run(main())


def test_polish_unifies_repeated_sentences_before_handing_over(calls, monkeypatch):
    def translate(callback_context, llm_request):
        text = _prompt(llm_request)
        segs = re.findall(r'<seg id="([^"]+)">\n(.*?)\n</seg>', text, re.S)
        # The same sentence comes out differently on each page.
        en = {"1": "The defects must be remedied.", "2": "Defects are to be rectified."}
        return _reply("\n".join(f'<seg id="{sid}">{en[sid[1]] if "Mängel" in src else "Heading"}</seg>' for sid, src in segs))

    fixer_prompts = []

    def fix(callback_context, llm_request):
        fixer_prompts.append(_prompt(llm_request))
        ids = re.findall(r'<pair id="([^"]+)">', _prompt(llm_request))
        return _reply("\n".join(f'<seg id="{i}">The defects must be remedied.</seg>' for i in ids))

    monkeypatch.setattr(pipeline.translator, "before_model_callback", translate)
    monkeypatch.setattr(consistency_fixer, "before_model_callback", fix)
    same = "Die Mängel sind zu beseitigen."
    fake_ocr(monkeypatch, lambda page: f"# Titel {page.number}\n\n{same}")

    async def main():
        sessions, _, runner, session = await _setup(_pdf("x", "y"))
        await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await _get(sessions, session.id)
        assert s.state["doc:status"] == "ready" and len(fixer_prompts) == 1
        assert {st.get_segment(s.state, i)["target"] for i in ("p1.2", "p2.2")} == {"The defects must be remedied."}
        last = s.state["doc:versions"][-1]
        assert last["note"] == "AI review fixes" and "p2.2" in last["changed"]

    asyncio.run(main())


def test_terms_in_the_tag_format_carry_options_and_meaning():
    [t] = parse_terms('<term source="五防" guess="five-prevention interlocking" alt="five defences" '
                      'meaning="Interlocks that stop five kinds of switching error" segs="p1.2">a utility term</term>')
    assert t["guess"] == "five-prevention interlocking" and [o["target"] for o in t["options"]] == [
        "five-prevention interlocking", "five defences"]
    assert t["meaning"].startswith("Interlocks") and t["segment_ids"] == ["p1.2"] and t["recommended"] == 0


def test_answers_accept_terms_notes_or_nothing():
    assert st.answer_of({"target": " cable tray ", "note": ""}) == {"target": "cable tray", "note": "", "recommended": False}
    assert st.answer_of("a metal tray for cables") == {"target": "", "note": "a metal tray for cables", "recommended": False}
    assert st.answer_of(None) is None and st.answer_of({"target": "", "note": " "}) is None
    accepted = st.answer_of({"target": "cable tray", "recommended": True})
    assert st.term_status(accepted) == "proposed" and st.term_status({**accepted, "recommended": False}) == "approved"
    assert st.term_status({"target": "", "note": "x", "recommended": False}) == "note"


def test_pending_interrupt_matches_calls_and_answers_by_count():
    def call(i):
        return Event(author="w", content=types.Content(role="model", parts=[
            types.Part(function_call=types.FunctionCall(id=i, name="adk_request_input", args={}))]))

    def answer(i):
        return Event(author="user", content=types.Content(role="user", parts=[
            types.Part(function_response=types.FunctionResponse(id=i, name="adk_request_input", response={}))]))

    assert pending_interrupt([call("ask")]) == "ask"
    assert pending_interrupt([call("ask"), answer("ask")]) is None
    # A retried document asks with the same id again: still pending.
    assert pending_interrupt([call("ask"), answer("ask"), call("ask")]) == "ask"
    assert pending_interrupt([call("ask"), answer("ask"), call("clarify")]) == "clarify"


@pytest.mark.analysis
def test_reviewer_does_not_re_ask_decided_terms(calls, monkeypatch):
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", lambda *_: _reply(
        '<term source="Abnahmeprotokoll" guess="acceptance certificate" segs="p1.1">record or certificate?</term>\n'
        '<term source="Kabelpritsche" guess="cable tray" segs="p1.2">answered already</term>\n'
        '<term source="geerdet" guess="bonded to earth" alt="earthed" segs="p1.2">earthed or bonded?</term>'))

    async def main():
        sessions, _, runner, session = await _setup(_pdf("Abnahmeprotokoll", "Ergebnis"))
        await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await _get(sessions, session.id)
        [q] = st.open_questions(s.state)
        await _run(runner, session.id, _answer(pending_interrupt(s.events), {q["id"]: {"target": "cable tray"}}))
        s = await _get(sessions, session.id)
        assert s.state["doc:status"] == "ready"
        # Only the new term is asked: the analysis's key term and the glossary term are settled.
        assert [(q["term"], q["origin"]) for q in st.open_questions(s.state)] == [("geerdet", "reviewer")]

    asyncio.run(main())


def test_reviewer_questions_that_only_confirm_are_dropped():
    batch = [{"id": "p1.2", "target": "The <g id=\"1\">main earthing grid</g> was tested."}]
    assert pipeline._already_used({"guess": "main earthing grid", "segment_ids": ["p1.2"]}, batch)
    assert not pipeline._already_used({"guess": "contact resistance", "segment_ids": ["p1.2"]}, batch)
    assert not pipeline._already_used({"guess": "", "segment_ids": ["p1.2"]}, batch)



@pytest.mark.analysis
def test_accepted_recommendations_are_only_proposed(calls):
    """Taking the agents' recommendation as it was isn't a person's decision: the project gets a proposed term,
    which prompts present as a suggestion, QA doesn't enforce, and later analyses may ask about again."""
    store = projects.get_store()
    pid = store.create_project("Acme", "German")["id"]

    async def main():
        sessions, _, runner, session = await _setup(_pdf("Abnahmeprotokoll", "Ergebnis"), pid)
        await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await _get(sessions, session.id)
        [q] = st.open_questions(s.state)
        await _run(runner, session.id, _answer(pending_interrupt(s.events), {q["id"]: {"target": "cable tray", "recommended": True}}))
        s = await _get(sessions, session.id)
        assert s.state["doc:status"] == "ready"
        assert s.state["doc:glossary"]["Kabelpritsche"]["target"] == "cable tray"  # still used in this document
        [term] = store.terms(pid)
        assert (term["source"], term["target"], term["status"]) == ("Kabelpritsche", "cable tray", "proposed")
        later = {"doc:project_id": pid, "doc:glossary": {}}
        assert "suggested, not confirmed" in projects.glossary_for(later, ["Die Kabelpritsche"])
        # QA: a different rendering of a proposed term is not flagged.
        seg = {"id": "p1.1", "source": "Die Kabelpritsche", "target": "The cable ladder", "translatable": True}
        assert not [i for i in qa.document_qa(later, [seg]) if i["check"] == "terminology"]
        # An accepted recommendation never overrides a term a person approved.
        store.upsert_term(pid, "Kabelpritsche", "cable ladder", status="approved")
        assert store.upsert_term(pid, "Kabelpritsche", "cable tray", status="proposed")["target"] == "cable ladder"
        assert [i["check"] for i in qa.document_qa(later, [{**seg, "target": "The cable tray"}])] == ["terminology"]

    asyncio.run(main())


def test_tm_exact_matches_are_only_refined_for_major_issues():
    segs = [{"id": "p1.1", "origin": "tm_exact"}, {"id": "p1.2", "origin": "mt"}]
    issues = [{"segment_id": "p1.1", "severity": "minor"}, {"segment_id": "p1.1", "severity": "major"},
              {"segment_id": "p1.2", "severity": "minor"}]
    assert pipeline.issues_to_fix(issues, segs, 1) == issues[1:]
    assert pipeline.issues_to_fix(issues, segs, 2) == [issues[1]]



@pytest.mark.analysis
def test_reviewer_questions_the_refiner_already_applied_are_closed(calls, monkeypatch):
    """The reviewer asks "use 'bonded to earth'?" and reports the issue; the refiner applies it. By the end the
    question asks nothing any more: it is closed instead of shown to the person."""
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", lambda cc, req: _reply(
        '<issue seg="p1.2" severity="minor" category="terminology">earthed → bonded to earth</issue>\n'
        '<term source="geerdet" guess="bonded to earth" alt="earthed" segs="p1.2">earthed or bonded?</term>'
        if "not earthed" in _prompt(req) else "<none/>"))
    monkeypatch.setattr(pipeline.refiner, "before_model_callback",
                        lambda *_: _reply('<seg id="p1.2">The cable tray is not bonded to earth.</seg>'))

    async def main():
        sessions, _, runner, session = await _setup(_pdf("Abnahmeprotokoll", "Ergebnis"))
        await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await _get(sessions, session.id)
        [q] = st.open_questions(s.state)
        await _run(runner, session.id, _answer(pending_interrupt(s.events), {q["id"]: {"target": "cable tray"}}))
        s = await _get(sessions, session.id)
        assert s.state["doc:status"] == "ready"
        assert st.get_segment(s.state, "p1.2")["target"] == "The cable tray is not bonded to earth."
        closed = next(q for q in s.state["doc:questions"] if q["term"] == "geerdet")
        assert closed["status"] == "resolved" and closed["answer"] == "applied in review"
        assert st.open_questions(s.state) == []

    asyncio.run(main())


@pytest.mark.analysis
def test_questions_carry_the_dictionarys_entries(calls, monkeypatch):
    from translator import dictionary
    from translator.config import get_settings

    monkeypatch.setattr(get_settings(), "dictionary_url", "http://dictionary.test/lookup")
    asked: list[tuple] = []

    async def lookup(terms, lang):
        asked.append((tuple(terms), lang))
        return {"Kabelpritsche": [{"translation": "cable rack", "definition": "A tray carrying cables.", "source": "IATE",
                                   "domain": "electrical installations", "url": "https://iate.europa.eu/entry/1"}]}

    monkeypatch.setattr(dictionary, "lookup", lookup)

    async def main():
        sessions, _, runner, session = await _setup(_pdf("Abnahmeprotokoll", "Ergebnis"))
        await _run(runner, session.id, types.Content(role="user", parts=[types.Part(text="Translate")]))
        s = await _get(sessions, session.id)
        [q] = st.open_questions(s.state)
        assert q["term"] == "Kabelpritsche" and q["dictionary"][0]["source"] == "IATE"
        assert [o["target"] for o in q["options"]][-1] == "cable rack"  # the dictionary's translation, as an option
        assert asked == [(("Abnahmeprotokoll", "Kabelpritsche"), "German")]  # one call for all key terms
        key = {k["term"]: k for k in s.state["doc:key_terms"]}
        assert key["Kabelpritsche"]["dictionary"][0]["translation"] == "cable rack" and key["Abnahmeprotokoll"]["dictionary"] == []

    asyncio.run(main())

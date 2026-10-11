"""Structured (JSON-schema) output: per-page schemas, injection, parsing, and the workflow in JSON mode."""

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

import pymupdf
import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.models import LlmRequest
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import prompts, structured
from translator import state as st
from translator.agents import pipeline

from .test_flow import _prompt, _reply

pytestmark = pytest.mark.structured


def _request(text: str) -> LlmRequest:
    return LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text=text)])], config=types.GenerateContentConfig())


def test_schema_ids_are_an_enum_of_the_page():
    schema = structured.translation_schema(["p2.1", "p2.2"])
    seg = schema["properties"]["segments"]["items"]
    assert seg["properties"]["id"]["enum"] == ["p2.1", "p2.2"]
    assert seg["additionalProperties"] is False and set(seg["required"]) == {"id", "translation"}
    assert set(schema["required"]) == {"segments", "terminology", "uncertain_terms", "brief", "source_language"}


def test_schema_is_injected_only_for_json_prompts():
    ctx = SimpleNamespace(agent_name="translator")
    req = _request(f'<seg id="p3.1">\nA\n</seg>\n<seg id="p3.2">\nB\n</seg>\n{prompts.TRANSLATE_FORMAT_JSON}')
    structured.inject_schema(ctx, req)
    assert req.config.response_schema["properties"]["segments"]["items"]["properties"]["id"]["enum"] == ["p3.1", "p3.2"]

    tags = _request(f'<seg id="p3.1">\nA\n</seg>{prompts.TRANSLATE_FORMAT_TAGS}')
    structured.inject_schema(ctx, tags)
    assert tags.config.response_schema is None  # tag-format prompt (model without structured outputs)

    review = _request(f'<pair id="p3.2">\nSOURCE:\nB\n</pair>{prompts.REVIEW_FORMAT_JSON}')
    structured.inject_schema(SimpleNamespace(agent_name="reviewer"), review)
    issue = review.config.response_schema["properties"]["issues"]["items"]["properties"]
    assert issue["segment_id"]["enum"] == ["p3.2"] and "accuracy" in issue["category"]["enum"]


def test_parse_json_tolerates_fences_and_prose():
    assert structured.parse_json('```json\n{"segments": []}\n```') == {"segments": []}
    assert structured.parse_json('Here you go: {"segments": [{"id": "p1.1", "translation": "Hi"}]}')["segments"]
    assert structured.parse_json("<seg id=\"p1.1\">Hi</seg>") is None


# --------------------------------------------------------------------------- #
# Workflow in JSON mode
# --------------------------------------------------------------------------- #

SCHEMAS: list[dict] = []


def _with_schema(reply):
    """Run the real schema injection first (as production would), record the schema, then reply."""

    def callback(callback_context, llm_request):
        assert structured.JSON_SENTINEL in _prompt(llm_request)
        structured.inject_schema(callback_context, llm_request)
        SCHEMAS.append(llm_request.config.response_schema)
        return _reply(json.dumps(reply(_prompt(llm_request)), ensure_ascii=False))

    return callback


def _translate(text: str) -> dict:
    ids = re.findall(r'<seg id="([^"]+)">', text)
    en = {"p1.1": "# Acceptance report", "p1.2": "The cable bridge is not earthed.", "p2.1": "## Result",
          "p2.2": "The plant is accepted with reservations."}
    return {
        "segments": [{"id": i, "translation": en[i]} for i in ids],
        "terminology": [{"source": "Abnahmeprotokoll", "target": "acceptance report"}] if "p1.1" in ids else [],
        "uncertain_terms": [{"source": "Kabelpritsche", "guess": "cable bridge", "segment_ids": ["p1.2"],
                             "reason": "cable tray or cable bridge?"}] if "p1.2" in ids else [],
        "brief": "Acceptance report; formal." if "p1.1" in ids else "Acceptance report; formal; result section.",
        "source_language": "German",
    }


def _review(text: str) -> dict:
    ids = re.findall(r'<pair id="([^"]+)">', text)
    issues = [{"segment_id": "p2.2", "severity": "major", "category": "accuracy",
               "problem": "'with reservations' loses 'subject to the defects'", "suggestion": "subject to the defects listed"}]
    return {"issues": [i for i in issues if i["segment_id"] in ids and "subject to" not in text], "uncertain_terms": []}


def _refine(text: str) -> dict:
    return {"segments": [{"id": "p2.2", "translation": "The plant is accepted subject to the defects listed."}]}


def _pdf() -> bytes:
    doc = pymupdf.open()
    for t in ("Seite eins", "Seite zwei"):
        doc.new_page().insert_text((72, 72), t)
    return doc.tobytes()


def test_workflow_with_structured_output(monkeypatch):
    SCHEMAS.clear()
    monkeypatch.setattr(structured, "enabled", lambda role: True)
    pages = iter(["# Abnahmeprotokoll\n\nDie Kabelpritsche ist nicht geerdet.", "## Ergebnis\n\nDie Anlage wird unter Vorbehalt der Mängel abgenommen."])
    monkeypatch.setattr(pipeline.ocr_extractor, "before_model_callback", lambda *_: _reply(next(pages)))
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))
    monkeypatch.setattr(pipeline.figure_detector, "before_model_callback", lambda *_: _reply("<none/>"))
    monkeypatch.setattr(pipeline.translator, "before_model_callback", _with_schema(_translate))
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", _with_schema(_review))
    monkeypatch.setattr(pipeline.refiner, "before_model_callback", _with_schema(_refine))

    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        runner = Runner(app=App(name="t", root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:filename": "a.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "auto-detect",
            "doc:target_lang": "English", "doc:questions": [], "doc:versions": []})
        await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename="source.pdf",
                                      artifact=types.Part.from_bytes(data=_pdf(), mime_type="application/pdf"))

        async def run(message):
            interrupt = None
            async for ev in runner.run_async(user_id="u", session_id=s.id, new_message=message):
                interrupt = next((fc.id for fc in ev.get_function_calls() if fc.name == "adk_request_input"), interrupt)
            return interrupt

        interrupt = await run(types.Content(role="user", parts=[types.Part(text="go")]))
        state = (await sessions.get_session(app_name="t", user_id="u", session_id=s.id)).state
        assert state["doc:detected_lang"] == "German"
        assert state["doc:termbase"] == {"Abnahmeprotokoll": "acceptance report"}
        assert state["doc:brief"] == "Acceptance report; formal; result section."
        [q] = st.open_questions(state)
        assert (q["term"], q["guess"], q["segment_ids"]) == ("Kabelpritsche", "cable bridge", ["p1.2"])

        await run(types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=interrupt, name="adk_request_input", response={"result": {}}))]))
        state = (await sessions.get_session(app_name="t", user_id="u", session_id=s.id)).state
        assert state["doc:status"] == "ready"
        segs = {x["id"]: x for x in st.get_segments(state)}
        assert segs["p2.2"]["target"] == "The plant is accepted subject to the defects listed."
        [issue] = state["doc:review_report"][0]["issues"]
        assert issue["category"] == "accuracy" and issue["severity"] == "major"
        # The AI reviewer's verdict is a separate marker; status stays draft until a person confirms.
        assert segs["p2.2"]["ai_check"] == "passed" and segs["p1.2"]["ai_check"] == "passed"
        assert {x["status"] for x in segs.values() if x["translatable"]} == {"draft"}

    asyncio.run(main())
    # Every call got a schema whose ids are exactly that call's segments.
    page_ids = [s["properties"]["segments"]["items"]["properties"]["id"]["enum"] for s in SCHEMAS if s["title"] == "page_translation"]
    assert page_ids == [["p1.1", "p1.2"], ["p2.1", "p2.2"]]

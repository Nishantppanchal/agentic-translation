"""The real layout MCP server (PP-DocLayoutV3) + the real workflow (LLM calls faked). Opt-in: RUN_LAYOUT_TESTS=1."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pymupdf
import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import layout
from translator import state as st
from translator.agents import pipeline
from translator.agents.editor import editor_agent
from google.adk.models import LlmResponse

from .fakes import fake_ocr
from .test_flow import _prompt, _reply

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
pytestmark = pytest.mark.layout


@pytest.fixture(autouse=True)
def fake_llms(monkeypatch):
    # The vision OCR writes [[FIGURE 1]] where PP-DocLayoutV3 found the picture (outlined in red on the page).
    fake_ocr(monkeypatch, "# Wartungsbericht\n\nIntro text here.\n\n[[FIGURE 1]]\n\nAbb. 1: Anlagenübersicht\n\nOutro text.",
             legends={1: "Schaltschrank"})
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))
    def translate(callback_context, llm_request):
        segs = re.findall(r'<seg id="([^"]+)">', _prompt(llm_request))
        return _reply("\n".join(f'<seg id="{sid}">English text {sid}</seg>' for sid in segs))

    monkeypatch.setattr(pipeline.translator, "before_model_callback", translate)
    monkeypatch.setattr(pipeline.refiner, "before_model_callback", translate)  # QA flags on the fake text ask for a fix
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", lambda *_: _reply("<none/>"))

    def editor(callback_context, llm_request):
        if any(p.function_response for c in llm_request.contents for p in c.parts or []):
            return _reply("Page 1 has a title, text and one figure.")
        call = types.FunctionCall(name="inspect_page_layout", args={"page_number": 1})
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))

    monkeypatch.setattr(editor_agent, "before_model_callback", editor)


def test_scanned_figure_found_by_pp_doclayout():
    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        runner = Runner(app=App(name="t", root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        s = await sessions.create_session(
            app_name="t", user_id="u",
            state={"doc:filename": "w.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "German",
                   "doc:target_lang": "English", "doc:questions": [], "doc:versions": []},
        )
        data = (SAMPLES / "wartungsbericht-scanned.pdf").read_bytes()
        await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename="source.pdf",
                                      artifact=types.Part.from_bytes(data=data, mime_type="application/pdf"))
        editor = Runner(app=App(name="t", root_agent=editor_agent), session_service=sessions, artifact_service=artifacts)
        try:
            async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")])):
                pass
            # The editor agent can call PP-DocLayout as a tool too.
            responses = []
            async for ev in editor.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="What is on page 1?")])):
                responses += ev.get_function_responses()
        finally:
            await layout.close()
        [resp] = [r for r in responses if r.name == "inspect_page_layout"]
        labels = [r["label"] for r in resp.response["regions"]]
        assert resp.response["status"] == "ok" and "image" in labels and "text" in labels, resp.response
        assert {x["kind"] for x in resp.response["segments_on_page"]} >= {"figure", "paragraph"}
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        [report] = s.state["doc:ocr_report"]
        assert report["figures"] == 1 and report["figure_source"] == "layout", report
        [fig] = [x for x in st.get_segments(s.state) if x["kind"] == "figure"]
        part = await artifacts.load_artifact(app_name="t", user_id="u", session_id=s.id, filename=fig["image"])
        w, h = pymupdf.Pixmap(part.inline_data.data).width, pymupdf.Pixmap(part.inline_data.data).height
        # The diagram is ~2:1 and roughly 2/3 of the page width at 150 dpi.
        assert 1.5 < w / h < 2.5 and w > 600, (w, h)

    asyncio.run(main())

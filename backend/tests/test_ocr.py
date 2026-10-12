"""Reading pages: the vision LLM transcribes each page, pictures are kept, the OCR check is guarded."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import state as st
from translator.agents import pipeline

from .test_figures import INTRO, OUTRO, _pdf
from .test_flow import _prompt, _reply

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
APP = "translator"


async def _read(pdf: bytes):
    """Run the workflow until it would translate (the translator isn't faked): these tests are about reading."""
    sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
    runner = Runner(app=App(name=APP, root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
    state = {"doc:filename": "a.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "Hebrew",
             "doc:target_lang": "English", "doc:questions": [], "doc:versions": []}
    s = await sessions.create_session(app_name=APP, user_id="u", state=state)
    await artifacts.save_artifact(app_name=APP, user_id="u", session_id=s.id, filename="source.pdf",
                                  artifact=types.Part.from_bytes(data=pdf, mime_type="application/pdf"))
    events = []
    with pytest.raises(AssertionError, match="translator"):
        async for ev in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            events.append(ev)
    return await sessions.get_session(app_name=APP, user_id="u", session_id=s.id), artifacts, events


HEBREW = "[[HEADER]] תחנת המשנה צפון · פרויקט UW-2291 · סודי\n\n# פרוטוקול מסירה\n\n## 1. היקף המסירה\n\n[[FOOTER]] עמוד 1 מתוך 1"


def test_a_document_read_by_the_vision_llm(monkeypatch):
    prompts: list[str] = []

    def vision(callback_context, llm_request):
        text = _prompt(llm_request)
        prompts.append(text)
        return _reply(HEBREW)

    monkeypatch.setattr(pipeline.ocr_reader, "before_model_callback", vision)
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))

    async def main():
        s, _, events = await _read((SAMPLES / "languages" / "acceptance-he-scanned.pdf").read_bytes())
        assert [x["kind"] for x in st.get_segments(s.state)] == ["header", "heading", "heading", "footer"]
        assert st.get_segments(s.state)[1]["source"] == "# פרוטוקול מסירה"
        [report] = s.state["doc:ocr_report"]
        assert report["ok"] and prompts[0].startswith("Transcribe page 1.")
        texts = [p.text for ev in events if ev.content for p in ev.content.parts or [] if p.text]
        assert any(t.startswith("Reading 1 page with vision OCR") for t in texts)

    asyncio.run(main())


def test_the_vision_engine_keeps_pictures_and_reads_their_text(monkeypatch):
    seen: list[str] = []

    def vision(callback_context, llm_request):
        text = _prompt(llm_request)
        seen.append(text)
        if "cropped from a document" in text:
            return _reply("Schaltschrank")  # the text inside the picture
        assert "outlined in red" in text  # the picture is marked on the page
        return _reply(f"{INTRO}\n\n[[FIGURE 1]]\n\n{OUTRO}")

    monkeypatch.setattr(pipeline.ocr_reader, "before_model_callback", vision)
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))

    async def main():
        s, artifacts, _ = await _read(_pdf())
        segs = st.get_segments(s.state)
        assert [x["kind"] for x in segs] == ["paragraph", "figure", "paragraph"]
        assert segs[1]["source"] == "Schaltschrank" and segs[1]["image"] == "figure-p1-1.png"
        assert s.state["doc:ocr_report"][0]["figure_source"] == "pdf"

    asyncio.run(main())


def test_the_check_is_guarded(monkeypatch):
    """A one-letter fix is applied, a rewording only listed."""
    monkeypatch.setattr(pipeline.ocr_reader, "before_model_callback",
                        lambda *_: _reply("Die Mängel sind zu beseitigen. Die Kabelprische ist nicht geerdet."))
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", lambda *_: _reply(
        "<verdict>fixed</verdict>\n<issues>\n- …\n</issues>\n<markdown>\n"
        "Die Mängel sind umgehend zu beheben. Die Kabelpritsche ist nicht geerdet.\n</markdown>"))

    async def main():
        s, _, _ = await _read((SAMPLES / "abnahmeprotokoll-scanned.pdf").read_bytes())
        report = s.state["doc:ocr_report"][0]
        assert report["issues"] == ["“Kabelprische” → “Kabelpritsche”"]
        assert "the checker reads more here: “umgehend”" in report["suggestions"]

    asyncio.run(main())


def test_a_page_is_read_again_only_when_its_settings_change():
    from translator.documents import load_pages

    [page] = load_pages((SAMPLES / "wartungsbericht-scanned.pdf").read_bytes(), "w.pdf")
    assert re.match(r"^[0-9a-f]{40}$", pipeline._ocr_signature(page))

"""The source check: PDFs and images pause after reading; the chat proposes page fixes; Continue translates."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.models import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import source_review
from translator import state as st
from translator.agents import editor_tools, pipeline

from .fakes import fake_ocr
from .test_flow import _reply

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
APP = "translator"

# Two columns read across, the way a model gets them wrong: the paragraph that runs from the bottom of the left
# column to the top of the right one is split, and the stamp's text sits inside it.
PAGE = ("[[HEADER]] Umspannwerk Nord · UW-2291\n\n# Prüfvermerk\n\n"
        "Die Kabeltrasse im Kellergeschoss wurde am 14.03.2026 begangen. Die Erdung der\n\n"
        "GEPRÜFT 14.03.2026 K. Albrecht Kabelpritsche fehlt weiterhin.\n\n[[FOOTER]] Seite 1 von 1")
FIXED = ("[[HEADER]] Umspannwerk Nord · UW-2291\n\n# Prüfvermerk\n\n"
         "Die Kabeltrasse im Kellergeschoss wurde am 14.03.2026 begangen. Die Erdung der Kabelpritsche fehlt weiterhin.\n\n"
         "GEPRÜFT 14.03.2026 K. Albrecht\n\n[[FOOTER]] Seite 1 von 1")


class Ctx:
    """Enough of a ToolContext for the page tools."""

    def __init__(self, state, source: bytes | None = None):
        self.state = state
        self._source = source

    async def load_artifact(self, name):
        return types.Part.from_bytes(data=self._source, mime_type="application/pdf") if self._source else None


async def _start(pdf: Path):
    sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
    runner = Runner(app=App(name=APP, root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
    s = await sessions.create_session(app_name=APP, user_id="u", state={
        "doc:filename": pdf.name, "doc:source_artifact": "source.pdf", "doc:source_lang": "German",
        "doc:target_lang": "English", "doc:questions": [], "doc:versions": []})
    await artifacts.save_artifact(app_name=APP, user_id="u", session_id=s.id, filename="source.pdf",
                                  artifact=types.Part.from_bytes(data=pdf.read_bytes(), mime_type="application/pdf"))
    events = [ev async for ev in runner.run_async(user_id="u", session_id=s.id,
                                                  new_message=types.Content(role="user", parts=[types.Part(text="go")]))]
    return sessions, runner, s.id, events


@pytest.mark.source_check
def test_a_scan_stops_after_reading_and_continue_translates(monkeypatch):
    fake_ocr(monkeypatch, PAGE)
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))

    async def main():
        sessions, runner, sid, events = await _start(SAMPLES / "wartungsbericht-scanned.pdf")
        s = await sessions.get_session(app_name=APP, user_id="u", session_id=sid)
        assert s.state["doc:status"] == "awaiting_source_check"  # read, not translated
        assert any(ev.get_function_calls() and ev.get_function_calls()[0].name == "adk_request_input" for ev in events)
        interrupt = next(fc.id for ev in events for fc in ev.get_function_calls() or [] if fc.name == "adk_request_input")
        resume = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=interrupt, name="adk_request_input", response={"result": {"continue": True}}))])
        with pytest.raises(AssertionError, match="translator"):  # it goes on to translate (the translator isn't faked)
            async for _ in runner.run_async(user_id="u", session_id=sid, new_message=resume):
                pass
        s = await sessions.get_session(app_name=APP, user_id="u", session_id=sid)
        assert s.state[source_review.CHECKED] is True

    asyncio.run(main())


def _state(status: str = "awaiting_source_check") -> dict:
    from translator.documents import segments_from_pages

    segs = segments_from_pages([(1, PAGE)])
    return {**{st.seg_key(s["id"]): st.normalize(s) for s in segs}, "doc:seg_ids": [s["id"] for s in segs],
            "doc:filename": "pruefvermerk.pdf", "doc:status": status}


def test_the_chat_proposes_a_page_fix_and_accepting_splits_the_page_again():
    state = _state()
    ctx = Ctx(state)
    assert editor_tools.get_page_source(1, ctx)["markdown"] == PAGE
    result = editor_tools.propose_page_source(1, FIXED, "Joined the paragraph; the stamp on its own line.", ctx)
    assert result["status"] == "proposed" and "word_changes" not in result  # structure only: no word changed
    fix = state[source_review.FIXES]["1"]
    assert fix["before"] == PAGE and fix["after"] == FIXED and fix["origin"] == "editor"
    state.update(source_review.resegment(state, 1, fix["after"]))
    sources = [s["source"] for s in st.get_segments(state)]
    assert "Die Kabeltrasse im Kellergeschoss wurde am 14.03.2026 begangen. Die Erdung der Kabelpritsche fehlt weiterhin." in sources
    assert "GEPRÜFT 14.03.2026 K. Albrecht" in sources


def test_a_page_fix_that_changes_words_says_so():
    state = _state()
    result = editor_tools.propose_page_source(1, FIXED.replace("weiterhin", "noch immer"), "joined", Ctx(state))
    assert result["status"] == "proposed" and result["word_changes"] and "warning" in result


def test_page_fixes_only_during_the_source_check():
    result = editor_tools.propose_page_source(1, FIXED, "joined", Ctx(_state("ready")))
    assert result["status"] == "error" and "fix_source_segment" in result["message"]


def test_reading_a_page_again_with_an_instruction(monkeypatch):
    from translator import llm

    seen = {}

    class FakeModel:
        async def generate_content_async(self, request):
            seen["text"] = "".join(p.text or "" for c in request.contents for p in c.parts or [])
            seen["image"] = any(p.inline_data for c in request.contents for p in c.parts or [])
            yield _reply(FIXED)

    monkeypatch.setattr(llm, "build_model", lambda role: FakeModel())
    state = _state()
    pdf = (SAMPLES / "wartungsbericht-scanned.pdf").read_bytes()
    result = asyncio.run(editor_tools.reread_page(1, "Two columns: left first. The stamp is separate.", Ctx(state, pdf)))
    assert result["status"] == "proposed" and state[source_review.FIXES]["1"]["origin"] == "reread"
    assert seen["image"] and "Two columns: left first." in seen["text"] and "<earlier_reading>" in seen["text"]


def test_reading_a_page_again_leaves_the_models_thinking_out(monkeypatch):
    """A reasoning model's thinking comes back as thought parts (OpenRouter's `reasoning`, vLLM's reasoning
    parser): it isn't part of the page."""
    from translator import llm

    class FakeModel:
        async def generate_content_async(self, request):
            yield LlmResponse(content=types.Content(role="model", parts=[
                types.Part(text="The user wants me to transcribe page 1. Let me be careful.", thought=True),
                types.Part(text=FIXED)]))

    monkeypatch.setattr(llm, "build_model", lambda role: FakeModel())
    state = _state()
    pdf = (SAMPLES / "wartungsbericht-scanned.pdf").read_bytes()
    asyncio.run(editor_tools.reread_page(1, "Read it again.", Ctx(state, pdf)))
    assert state[source_review.FIXES]["1"]["after"] == FIXED


def test_markup_isnt_a_word_change_but_a_dropped_picture_is():
    from translator.source_review import word_changes

    before = "Kopf\n\n# Titel\n\n[[FIGURE 1]]\n\nText."
    assert word_changes(before, "[[HEADER]] Kopf\n\n## Titel\n\n[[FIGURE 1]]\n\nText.") == []
    assert word_changes(before, "Kopf\n\n# Titel\n\nText.") == ["picture 1 removed"]
    assert word_changes("Die Erdung fehlt weiterhin.", "Die Erdung fehlt noch immer.") == [
        "removed: “weiterhin”", "added: “noch”, “immer”"]


def test_columns_stitched_the_wrong_way_round_keep_every_word_but_are_quoted_as_moved():
    from translator.source_review import moved_text, word_changes

    left = "Die Kabelpritsche verläuft auf einer Länge von etwa 48 m entlang der Nordwand."
    right = "Der Mangel ist sicherheitsrelevant, weil bei einem Isolationsfehler Spannung anstehen kann."
    wrong = f"{right}\n\n{left}"
    assert word_changes(f"{left}\n\n{right}", wrong) == []  # the word count can't see it
    assert moved_text(f"{left}\n\n{right}", wrong) == ["“Der Mangel ist sicherheitsrelevant, weil bei einem Isolation …”"]
    # Joining, marking a header or changing a word moves nothing.
    assert moved_text("Die Messung ergab 23 ms\n\nund ist gültig.", "Die Messung ergab 23 ms und ist gültig.") == []
    assert moved_text("Kopf\n\nText.", "[[HEADER]] Kopf\n\nText.") == []
    assert moved_text("Die Erdung fehlt weiterhin.", "Die Erdung fehlt noch immer.") == []
    # Chinese is quoted as written (a character is a word, but the quote keeps the text whole).
    zh = "一、工程概况\n\n本工程为北区变电站改造。\n\n二、存在问题\n\n电缆桥架未接地。"
    assert moved_text(zh, "二、存在问题\n\n电缆桥架未接地。\n\n一、工程概况\n\n本工程为北区变电站改造。") == ["“二、存在问题 电缆桥架未接地”"]


def test_a_page_fix_that_moves_text_tells_the_editor_to_have_the_order_checked():
    state = _state()
    paragraphs = FIXED.split("\n\n")
    result = editor_tools.propose_page_source(1, "\n\n".join(paragraphs[::-1]), "reordered", Ctx(state))
    assert result["status"] == "proposed" and result["moved"] and "order" in result["moved_note"]
    assert state[source_review.FIXES]["1"]["moved"] == result["moved"]

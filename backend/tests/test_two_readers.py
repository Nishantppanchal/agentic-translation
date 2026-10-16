"""Two readings of scanned pages and pictures (agents/steps/page.py, picture.py): two models read at once; where they
differ, the OCR check model settles it; a page too hard to read is marked and left as it is."""

from __future__ import annotations

import asyncio
import io
import re
from pathlib import Path

import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.genai import types
from PIL import Image

from translator.agents import pipeline, workers
from translator.document import state as st
from translator.ocr import second
from translator.quality import qa

from .fakes import fake_ocr
from .test_figures import _pdf
from .test_flow import _prompt, _reply

pytestmark = pytest.mark.second_reading
SAMPLES = Path(__file__).resolve().parents[2] / "samples"
SCAN = (SAMPLES / "abnahmeprotokoll-scanned.pdf").read_bytes()
APP = "translator"


async def _read(data: bytes, filename: str = "a.pdf", **state):
    """Run the workflow until it would translate (the translator isn't faked): these tests are about reading."""
    sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
    runner = Runner(app=App(name=APP, root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
    ext = filename.rsplit(".", 1)[-1]
    s = await sessions.create_session(app_name=APP, user_id="u", state={
        "doc:filename": filename, "doc:source_artifact": f"source.{ext}", "doc:source_lang": "German",
        "doc:target_lang": "English", "doc:questions": [], "doc:versions": [], **state})
    await artifacts.save_artifact(app_name=APP, user_id="u", session_id=s.id, filename=f"source.{ext}",
                                  artifact=types.Part.from_bytes(data=data, mime_type="application/pdf" if ext == "pdf" else f"image/{ext}"))
    with pytest.raises(AssertionError, match="translator"):
        async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            pass
    return await sessions.get_session(app_name=APP, user_id="u", session_id=s.id)


def _sources(s) -> str:
    return "\n".join(seg["source"] for seg in st.get_segments(s.state))


def _no_check(monkeypatch):
    def check(*_):
        raise AssertionError("the one-reading check ran on a page that had two readings")
    monkeypatch.setattr(workers.ocr_checker, "before_model_callback", check)


def test_two_readings_that_agree_need_nothing_else(monkeypatch):
    _no_check(monkeypatch)
    prompts = fake_ocr(monkeypatch, "# Abnahme\n\nDie Anlage wird abgenommen.")
    s = asyncio.run(_read(SCAN))
    report = s.state["doc:ocr_report"][0]
    assert (report["readers"], report["disagreements"], report["ok"]) == (2, 0, True)
    assert sum("Transcribe page 1" in p for p in prompts) == 2  # both readers; no arbiter, no check
    assert "Die Anlage wird abgenommen." in _sources(s)


def test_where_they_differ_the_check_model_says_which(monkeypatch):
    _no_check(monkeypatch)
    asked = []

    def arbiter(prompt):
        asked.append(prompt)
        assert "[A: Kabelprische | B: Kabelpritsche]" in prompt and "[A: 2026 | B: 2028]" in prompt
        return "1: Kabelpritsche\n2: 2026"  # the second reading's word, the first reading's year

    fake_ocr(monkeypatch, "Die Kabelprische ist nicht geerdet. Frist 30.04.2026.",
             second="Die Kabelpritsche ist nicht geerdet. Frist 30.04.2028.", arbiter=arbiter)
    s = asyncio.run(_read(SCAN))
    assert "Die Kabelprische" not in _sources(s) and len(asked) == s.state["doc:pages"] == 2  # once per page
    report = s.state["doc:ocr_report"][0]
    assert report["disagreements"] == 2 and report["settled"] == 2 and not report.get("suggestions")
    assert len(report["issues"]) == 1 and "Kabelpritsche" in report["issues"][0] and report["ok"] is False


def test_what_the_check_model_cant_settle_is_left_for_the_person(monkeypatch):
    _no_check(monkeypatch)
    fake_ocr(monkeypatch, "Frist bis 30.04.2026.", second="Frist bis 30.04.2028.", arbiter=lambda _: "1: ?")
    s = asyncio.run(_read(SCAN))
    report = s.state["doc:ocr_report"][0]
    assert "Frist bis 30.04.2026." in _sources(s)  # nothing changed
    [left] = report["suggestions"]
    assert "2026" in left and "2028" in left and "the two readings differ" in left


def test_a_page_too_hard_to_read_is_marked_and_left_as_it_is(monkeypatch):
    _no_check(monkeypatch)
    first = "eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf"
    fake_ocr(monkeypatch, first, second="eins zwie vier drei fümf sechs siben acht nein zehn elv zwölf")  # no arbiter
    s = asyncio.run(_read(SCAN))
    report = s.state["doc:ocr_report"][0]
    assert report["hard"] is True and report["disagreements"] >= 5 and len(report["suggestions"]) == report["disagreements"]
    assert first in _sources(s)  # nothing changed
    assert any("hard to read" in (e.content.parts[0].text or "") for e in s.events if e.content and e.content.parts)


def test_a_pdf_with_its_own_text_layer_gets_one_reading(monkeypatch):
    """The text layer is a second reading already: no second model, the check (skipped when they agree)."""
    def second_reader(*_):
        raise AssertionError("a second reading of a page with a text layer")
    monkeypatch.setattr(workers.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))
    fake_ocr(monkeypatch, "Die Anlage besteht aus einem Schaltschrank und einer Kabelpritsche im Keller.\n\n"
                          "Die Abnahme erfolgt nach Abschluss aller Restarbeiten an der Anlage.", legends={1: "Schaltschrank"})
    monkeypatch.setattr(workers.ocr_second_reader, "before_model_callback", second_reader)
    s = asyncio.run(_read(_pdf()))
    assert s.state["doc:ocr_report"][0]["readers"] == 1


def test_turned_off_for_a_document_the_check_amends(monkeypatch):
    """One reading: the OCR check lists amendments (never the whole page); small ones are applied, the rest listed."""
    def check(callback_context, llm_request):
        assert "never write out the whole page" in _prompt(llm_request)
        return _reply("<verdict>fixed</verdict>\n"
                      "<fix>\n<read>Die Kabelprische ist</read>\n<printed>Die Kabelpritsche ist</printed>\n</fix>\n"
                      "<fix>\n<read>zu beseitigen.</read>\n<printed>umgehend zu beheben.</printed>\n</fix>")
    monkeypatch.setattr(workers.ocr_checker, "before_model_callback", check)
    monkeypatch.setattr(workers.ocr_second_reader, "before_model_callback",
                        lambda *_: (_ for _ in ()).throw(AssertionError("second reading while it's off")))
    fake_ocr(monkeypatch, "Die Mängel sind zu beseitigen. Die Kabelprische ist nicht geerdet.")
    monkeypatch.setattr(workers.ocr_second_reader, "before_model_callback",
                        lambda *_: (_ for _ in ()).throw(AssertionError("second reading while it's off")))
    s = asyncio.run(_read(SCAN, **{second.DOC_KEY: False}))
    report = s.state["doc:ocr_report"][0]
    assert report["readers"] == 1 and report["issues"] == ["“Kabelprische” → “Kabelpritsche”"]
    assert any("umgehend" in x for x in report["suggestions"])
    assert "Die Mängel sind zu beseitigen. Die Kabelpritsche ist nicht geerdet." in _sources(s)


def test_a_figures_two_readings_are_settled_too(monkeypatch):
    monkeypatch.setattr(workers.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))

    def arbiter(prompt):
        assert "this picture" in prompt and "[A: fehit | B: fehlt]" in prompt
        return "1: fehlt"

    fake_ocr(monkeypatch, "Die Anlage besteht aus einem Schaltschrank.\n\n[[FIGURE 1]]\n\nDie Abnahme erfolgt.",
             legends={1: "Erdung fehit"}, second_legends={1: "Erdung fehlt"}, arbiter=arbiter)
    s = asyncio.run(_read(_pdf()))
    [figure] = [x for x in st.get_segments(s.state) if x["kind"] == "figure"]
    assert figure["source"] == "Erdung fehlt"
    assert any(i.startswith("Figure 1: ") for i in s.state["doc:ocr_report"][0]["issues"])


def _png(w: int, h: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(out, "PNG")
    return out.getvalue()


def test_small_page_images_are_enlarged_for_both_readers(monkeypatch):
    sizes = []

    def reader(callback_context, llm_request):
        png = next(p.inline_data.data for c in llm_request.contents for p in c.parts or [] if p.inline_data)
        sizes.append(Image.open(io.BytesIO(png)).size)
        return _reply("Die Anlage wird abgenommen.")

    fake_ocr(monkeypatch, "unused")
    monkeypatch.setattr(workers.ocr_reader, "before_model_callback", reader)
    monkeypatch.setattr(workers.ocr_second_reader, "before_model_callback", reader)
    s = asyncio.run(_read(_png(744, 1053), "foto.png"))
    assert sizes == [(1488, 2106), (1488, 2106)] and s.state["doc:ocr_report"][0]["enlarged"] is True


def test_office_picture_readings_that_stay_apart_are_a_quality_warning(monkeypatch):
    """A Word file's picture: no source check, so what the two readings disagree on is a Quality warning."""
    from translator import office
    from translator.agents.steps import extract as extract_step

    from .fixtures_office import docx_pictures

    fake_ocr(monkeypatch, "unused", legends={1: "Schaltbild Trafo", 2: "Firma GmbH"},
             second_legends={1: "Schaltbild Trato", 2: "Firma GmbH"}, arbiter=lambda _: "1: ?")

    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        runner = Runner(app=App(name=APP, root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        s = await sessions.create_session(app_name=APP, user_id="u", state={
            "doc:filename": "bilder.docx", "doc:source_artifact": "source.docx", "doc:source_lang": "German",
            "doc:target_lang": "English", "doc:questions": [], "doc:versions": []})
        await artifacts.save_artifact(app_name=APP, user_id="u", session_id=s.id, filename="source.docx",
                                      artifact=types.Part.from_bytes(data=docx_pictures(), mime_type=office.media_type("x.docx")))
        with pytest.raises(AssertionError, match="translator"):
            async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")])):
                pass
        return await sessions.get_session(app_name=APP, user_id="u", session_id=s.id)

    s = asyncio.run(main())
    assert extract_step.read_pictures.name == "read_pictures"
    figures = [x for x in st.get_segments(s.state) if x["kind"] == "figure"]
    flagged = [f for f in figures if f.get("reading_flags")]
    assert len(flagged) == 1 and "Trafo" in flagged[0]["reading_flags"][0] and "Trato" in flagged[0]["reading_flags"][0]
    issues = qa.run([{**f, "target": f.get("target") or "x"} for f in figures], [])
    assert [i["check"] for i in issues if i["check"] == "picture_reading"] == ["picture_reading"]
    assert any(re.search(r"two readings of 1 picture still differ", e.content.parts[0].text or "")
               for e in s.events if e.content and e.content.parts)

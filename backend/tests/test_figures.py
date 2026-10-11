"""Figures: detected (PDF images or vision boxes on scans), placed via [[FIGURE n]], kept in the output."""

from __future__ import annotations

import asyncio
import re

import pymupdf
import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import state as st
from translator.agents import pipeline
from translator.documents import assemble_markdown, box_from_percent, load_pages, place_figure_marker

from .test_flow import _prompt, _reply, fake_review, fake_translate

APP = "translator"
OCR_PROMPTS: list[str] = []


def _diagram_png() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.draw_rect(pymupdf.Rect(20, 20, 280, 180), color=(0, 0, 1), width=3)
    page.insert_text((40, 100), "Schaltschrank", fontsize=20)
    return page.get_pixmap(dpi=100).tobytes("png")


def _pdf(scanned: bool = False) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Die Anlage besteht aus einem Schaltschrank und einer Kabelpritsche im Keller.")
    page.insert_image(pymupdf.Rect(150, 150, 450, 350), stream=_diagram_png())
    page.insert_text((72, 420), "Die Abnahme erfolgt nach Abschluss aller Restarbeiten an der Anlage.")
    if not scanned:
        return doc.tobytes()
    scan = pymupdf.open()
    sp = scan.new_page(width=page.rect.width, height=page.rect.height)
    sp.insert_image(sp.rect, stream=page.get_pixmap(dpi=100).tobytes("png"))
    return scan.tobytes()


def fake_ocr(callback_context, llm_request):
    text = _prompt(llm_request)
    OCR_PROMPTS.append(text)
    if "cropped from a document" in text:  # text inside the figure
        return _reply("Schaltschrank")
    marker = "\n\n[[FIGURE 1]]\n\n" if "outlined in red" in text else "\n\n"
    return _reply(
        "Die Anlage besteht aus einem Schaltschrank und einer Kabelpritsche im Keller."
        + marker
        + "Die Abnahme erfolgt nach Abschluss aller Restarbeiten an der Anlage."
    )


@pytest.fixture(autouse=True)
def fake_models(monkeypatch):
    OCR_PROMPTS.clear()
    monkeypatch.setattr(pipeline.ocr_extractor, "before_model_callback", fake_ocr)
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))
    # Vision boxes as % of the page: the diagram sits at x 150–450 / 595pt, y 150–350 / 842pt.
    monkeypatch.setattr(
        pipeline.figure_detector,
        "before_model_callback",
        lambda *_: _reply('<figure box="25,17.8,75.6,41.6">diagram</figure>\n<figure box="0,0,100,100">page</figure>'),
    )

    def translate_no_terms(callback_context, llm_request):
        out = fake_translate(callback_context, llm_request).content.parts[0].text
        out = re.sub(r"<(term|keep)\b.*?</\1>", "", out, flags=re.S)
        out = out.replace("Die Anlage besteht aus einem", "The plant consists of a")
        out = out.replace("und einer Kabelpritsche im Keller.", "and a cable tray in the basement.")
        out = out.replace("Die Abnahme erfolgt nach Abschluss aller Restarbeiten an der Anlage.", "Acceptance follows completion of all remaining work on the plant.")
        return _reply(out.replace("Schaltschrank", "control cabinet"))

    monkeypatch.setattr(pipeline.translator, "before_model_callback", translate_no_terms)
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", fake_review)


def test_pdf_embedded_image_is_detected_exactly():
    [page] = load_pages(_pdf(), "a.pdf", dpi=72)
    [fig] = page.figures
    assert [round(v) for v in fig.box] == [150, 150, 450, 350] and not page.is_scan
    assert fig.anchor.startswith("Die Abnahme erfolgt")  # the text right below the figure
    [scan] = load_pages(_pdf(scanned=True), "a.pdf", dpi=72)
    assert scan.figures == [] and scan.is_scan  # full-page image = scan, not a figure


@pytest.mark.parametrize("scanned", [False, True])
def test_figures_are_kept_in_place_with_translated_legend(scanned):
    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        runner = Runner(app=App(name=APP, root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        s = await sessions.create_session(
            app_name=APP, user_id="u",
            state={"doc:filename": "a.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "German",
                   "doc:target_lang": "English", "doc:questions": [], "doc:versions": []},
        )
        await artifacts.save_artifact(
            app_name=APP, user_id="u", session_id=s.id, filename="source.pdf",
            artifact=types.Part.from_bytes(data=_pdf(scanned), mime_type="application/pdf"),
        )
        async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            pass
        s = await sessions.get_session(app_name=APP, user_id="u", session_id=s.id)
        assert s.state["doc:status"] == "ready"
        segs = st.get_segments(s.state)
        assert [x["kind"] for x in segs] == ["paragraph", "figure", "paragraph"]  # figure stays between the paragraphs
        fig = segs[1]
        assert fig["image"] == "figure-p1-1.png" and fig["source"] == "Schaltschrank"
        assert fig["target"] == "control cabinet"  # text inside the figure translated as a legend
        assert s.state["doc:ocr_report"][0]["figures"] == 1  # the full-page "box" was rejected
        part = await artifacts.load_artifact(app_name=APP, user_id="u", session_id=s.id, filename=fig["image"])
        assert part.inline_data.data[:4] == b"\x89PNG"
        assert any("outlined in red" in p for p in OCR_PROMPTS)
        assert "![Figure 1](figures/figure-p1-1.png)\n\n> control cabinet" in assemble_markdown(segs)

    asyncio.run(main())


def test_figure_marker_placement():
    md = "# Title\n\nIntro.\n\n*Abb. 1: Übersicht*\n\n[[FIGURE 1]]\n\nOutro."
    # PDF anchor (text right below the figure) wins over the model's placement after the caption.
    assert place_figure_marker(md, 1, "Abb. 1: Übersicht") == "# Title\n\nIntro.\n\n[[FIGURE 1]]\n\n*Abb. 1: Übersicht*\n\nOutro."
    # No usable anchor (scans): keep the model's placement; append if it forgot the marker.
    assert place_figure_marker(md, 1, None) == md
    assert place_figure_marker("A paragraph.", 2, None) == "A paragraph.\n\n[[FIGURE 2]]"
    # Missing marker but known anchor: inserted at the right spot.
    assert place_figure_marker("Intro.\n\nOutro text here.", 1, "Outro text here") == "Intro.\n\n[[FIGURE 1]]\n\nOutro text here."


def test_vision_boxes_are_validated_and_padded():
    assert box_from_percent([10, 20, 60, 50], 1000, 2000) == (100, 400, 600, 1000)
    assert box_from_percent([1, 20, 60, 99], 1000, 2000, pad=0.025) == pytest.approx((0, 350, 625, 2000))  # clamped
    assert box_from_percent([0, 0, 100, 100], 1000, 2000) is None  # whole page is not a figure
    assert box_from_percent([60, 20, 10, 50], 1000, 2000) is None  # inverted
    assert box_from_percent([10, 20, 12, 50], 1000, 2000) is None  # too thin

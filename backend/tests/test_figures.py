"""Figures: found by the page layout (PP-DocLayoutV3) or embedded in the PDF, placed via
[[FIGURE n]], kept in the output with the text inside them translated as a legend."""

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

from translator.agents import pipeline, workers
from translator.config import get_settings
from translator.document import state as st
from translator.document.pages import assemble_markdown, load_pages, place_figure_marker

from .fakes import fake_ocr
from .test_flow import _reply, fake_review, fake_translate

APP = "translator"
INTRO = "Die Anlage besteht aus einem Schaltschrank und einer Kabelpritsche im Keller."
OUTRO = "Die Abnahme erfolgt nach Abschluss aller Restarbeiten an der Anlage."


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


@pytest.fixture(autouse=True)
def fake_models(monkeypatch):
    # The reading: the paragraph, the picture (with the text inside it) and the next paragraph.
    fake_ocr(monkeypatch, f"{INTRO}\n\n[[FIGURE 1]]\n\n{OUTRO}", legends={1: "Schaltschrank"})
    monkeypatch.setattr(workers.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))

    def translate_no_terms(callback_context, llm_request):
        out = fake_translate(callback_context, llm_request).content.parts[0].text
        out = re.sub(r"<(term|keep)\b.*?</\1>", "", out, flags=re.S)
        out = out.replace("Die Anlage besteht aus einem", "The plant consists of a")
        out = out.replace("und einer Kabelpritsche im Keller.", "and a cable tray in the basement.")
        out = out.replace("Die Abnahme erfolgt nach Abschluss aller Restarbeiten an der Anlage.", "Acceptance follows completion of all remaining work on the plant.")
        return _reply(out.replace("Schaltschrank", "control cabinet"))

    monkeypatch.setattr(workers.translator, "before_model_callback", translate_no_terms)
    monkeypatch.setattr(workers.reviewer, "before_model_callback", fake_review)


def test_pdf_embedded_image_is_detected_exactly():
    [page] = load_pages(_pdf(), "a.pdf", dpi=72)
    [fig] = page.figures
    assert [round(v) for v in fig.box] == [150, 150, 450, 350] and not page.is_scan
    assert fig.anchor.startswith("Die Abnahme erfolgt")  # the text right below the figure
    [scan] = load_pages(_pdf(scanned=True), "a.pdf", dpi=72)
    assert scan.figures == [] and scan.is_scan  # full-page image = scan, not a figure


async def _run(pdf: bytes):
    sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
    runner = Runner(app=App(name=APP, root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
    s = await sessions.create_session(
        app_name=APP, user_id="u",
        state={"doc:filename": "a.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "German",
               "doc:target_lang": "English", "doc:questions": [], "doc:versions": []},
    )
    await artifacts.save_artifact(app_name=APP, user_id="u", session_id=s.id, filename="source.pdf",
                                  artifact=types.Part.from_bytes(data=pdf, mime_type="application/pdf"))
    async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")])):
        pass
    return await sessions.get_session(app_name=APP, user_id="u", session_id=s.id), artifacts


@pytest.mark.parametrize("scanned", [False, True])
def test_figures_are_kept_in_place_with_translated_legend(scanned, monkeypatch):
    if scanned:  # no embedded picture on a scan: PP-DocLayoutV3 finds it (the diagram at 150–450 × 150–350 pt)
        from translator.ocr import layout

        async def boxes(png, tool_context=None):
            return [(tuple(v * 150 / 72 for v in (150, 150, 450, 350)), "image")]

        monkeypatch.setattr(layout, "available", lambda: True)
        monkeypatch.setattr(layout, "figure_boxes", boxes)

    async def main():
        s, artifacts = await _run(_pdf(scanned))
        assert s.state["doc:status"] == "ready"
        segs = st.get_segments(s.state)
        assert [x["kind"] for x in segs] == ["paragraph", "figure", "paragraph"]  # figure stays between the paragraphs
        fig = segs[1]
        assert fig["image"] == "figure-p1-1.png" and fig["source"] == "Schaltschrank"
        assert fig["target"] == "control cabinet"  # text inside the figure translated as a legend
        [report] = s.state["doc:ocr_report"]
        assert report["figures"] == 1 and report["figure_source"] == ("layout" if scanned else "pdf")
        part = await artifacts.load_artifact(app_name="translator", user_id="u", session_id=s.id, filename=fig["image"])
        assert part.inline_data.data[:4] == b"\x89PNG"
        assert "![Figure 1](figures/figure-p1-1.png)\n\n> control cabinet" in assemble_markdown(segs)

    asyncio.run(main())


def test_a_pdf_picture_the_layout_missed_is_kept_before_the_text_below_it(monkeypatch):
    fake_ocr(monkeypatch, f"{INTRO}\n\n{OUTRO}")  # the layout model found no picture

    async def main():
        s, _ = await _run(_pdf())
        segs = st.get_segments(s.state)
        assert [x["kind"] for x in segs] == ["paragraph", "figure", "paragraph"]
        assert segs[1]["source"] == "" and s.state["doc:ocr_report"][0]["figure_source"] == "pdf"

    asyncio.run(main())


def test_figure_detection_off_keeps_only_the_text(monkeypatch):
    monkeypatch.setattr(get_settings(), "figure_detection", "off")

    async def main():
        s, _ = await _run(_pdf())
        assert [x["kind"] for x in st.get_segments(s.state)] == ["paragraph", "paragraph"]

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

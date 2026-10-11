"""Layout-preserving PDF for scans: OCR'd lines (faked here; the real server in the opt-in test),
background-colour erasing, figures as obstacles, positional placement, page images."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pymupdf
import pytest
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import exports, layout
from translator import state as st
from translator.filters import scan

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
LINES = [
    (pymupdf.Rect(72, 60, 400, 84), "Wartungsbericht Keller", 16),
    (pymupdf.Rect(72, 100, 500, 116), "Die Anlage im Kellergeschoss wurde vollständig geprüft.", 11),
    (pymupdf.Rect(72, 130, 500, 146), "Der Erdungsanschluss ist bis zum 30.04.2026 herzustellen.", 11),
    (pymupdf.Rect(72, 160, 500, 176), "Xqzv wrrt plmk zzt qrrw vbbn lmm.", 11),  # what OCR "read" for a line it garbled
    (pymupdf.Rect(72, 190, 500, 206), "Die Freigabe erfolgt durch die Netzleitstelle.", 11),
]
SEGMENTS = [
    {"id": "p1.1", "page": 1, "kind": "heading", "source": "# Wartungsbericht Keller", "translatable": True},
    {"id": "p1.2", "page": 1, "kind": "paragraph", "source": "Die Anlage im Kellergeschoss wurde vollständig geprüft.", "translatable": True},
    {"id": "p1.3", "page": 1, "kind": "paragraph", "source": "Der Erdungsanschluss ist bis zum 30.04.2026 herzustellen.", "translatable": True},
    {"id": "p1.4", "page": 1, "kind": "paragraph", "source": "Bis dahin nur im Bypass-Betrieb.", "translatable": True},
    {"id": "p1.5", "page": 1, "kind": "paragraph", "source": "Die Freigabe erfolgt durch die Netzleitstelle.", "translatable": True},
]
TARGETS = {
    "p1.1": "# Maintenance report basement",
    "p1.2": "The basement installation was fully inspected.",
    "p1.3": "The earth connection must be made by 30.04.2026.",
    "p1.4": "Until then, bypass operation only.",
    "p1.5": "Approval is given by the network control centre.",
}


def _scanned_pdf() -> bytes:
    """A page with text on a cream background, rasterised into an image-only PDF (a scan)."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(page.rect, color=None, fill=(0.98, 0.96, 0.9))
    for rect, text, size in LINES:
        if not text.startswith("Xq"):
            page.insert_text((rect.x0, rect.y1 - 3), text, fontsize=size)
        else:
            page.insert_text((rect.x0, rect.y1 - 3), "Bis dahin nur im Bypass-Betrieb.", fontsize=size)
    pix = page.get_pixmap(dpi=150)
    out = pymupdf.open()
    scan_page = out.new_page(width=595, height=842)
    scan_page.insert_image(scan_page.rect, stream=pix.tobytes("png"))
    return out.tobytes()


def _fake_ocr(png: bytes, script: str = "latin", tool_context=None) -> dict:
    s = scan.SCAN_DPI / 72
    lines = [{"box": [r.x0 * s, (r.y0 - 2) * s, r.x1 * s, (r.y1 + 2) * s], "text": t, "score": 0.99, "words": []} for r, t, _ in LINES]
    return {"width": round(595 * s), "height": round(842 * s), "lines": lines}


@pytest.fixture()
def fake_server(monkeypatch):
    monkeypatch.setattr(layout, "available", lambda: True)

    async def ocr(png, script="latin", tool_context=None):
        assert script == "latin"
        return _fake_ocr(png)

    async def regions(png, tool_context=None):
        s = scan.SCAN_DPI / 72
        return {"regions": [{"label": "image", "box": [72 * s, 600 * s, 300 * s, 760 * s]}]}

    monkeypatch.setattr(layout, "ocr_lines", ocr)
    monkeypatch.setattr(layout, "detect_layout", regions)


async def _session(filename: str, data: bytes):
    sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
    segs = {s["id"]: {**s, "target": TARGETS[s["id"]]} for s in SEGMENTS}
    s = await sessions.create_session(app_name="t", user_id="u", state={
        "doc:filename": filename, "doc:source_artifact": "source", "doc:source_lang": "German", "doc:target_lang": "English",
        "doc:layout_capable": False, "doc:seg_ids": list(segs), **{st.seg_key(k): v for k, v in segs.items()},
        "doc:versions": [{"version": 1, "note": "Draft", "changed": list(segs), "artifact_version": 0}]})
    await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename="source",
                                  artifact=types.Part.from_bytes(data=data, mime_type="application/octet-stream"))
    await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename=st.TRANSLATION_ARTIFACT,
                                  artifact=types.Part(text=json.dumps(TARGETS)))
    return sessions, artifacts, s


def test_scanned_pdf_gets_a_layout_preserving_translation(fake_server):
    async def main():
        _, artifacts, s = await _session("bericht.pdf", _scanned_pdf())
        assert exports.layout_capable(s, None)
        formats = {f["id"]: f["available"] for f in await exports.available(artifacts, s)}
        assert formats["pdf"]
        pdf, report = await exports.layout_pdf(artifacts, s, 1)
        out = pymupdf.open(stream=pdf, filetype="pdf")
        text = out[0].get_text()
        assert "Maintenance report basement" in text and "network control centre" in text
        assert len(out[0].get_images()) == 1  # the scan stays underneath
        fills = [d["fill"] for d in out[0].get_drawings() if d.get("fill")]
        assert fills and all(abs(f[0] - 0.98) < 0.03 and abs(f[2] - 0.9) < 0.03 for f in fills)  # paper colour, not white
        seg = report["segments"]
        assert {seg[i]["status"] for i in ("p1.1", "p1.2", "p1.3", "p1.5")} <= {"fit", "shrunk"}
        # OCR garbled p1.4's line; it sits between two aligned segments, so it is placed by position.
        assert seg["p1.4"]["matched"] == "position" and "bypass operation" in text
        assert report["summary"]["scanned_pages"] == 1 and report["summary"]["by_position"] == 1
        keys = await artifacts.list_artifact_keys(app_name="t", user_id="u", session_id=s.id)
        assert "scan-ocr-r1.json" in keys  # OCR is cached for the next version

    asyncio.run(main())


def test_page_image_becomes_a_translated_pdf(fake_server):
    async def main():
        page = pymupdf.open(stream=_scanned_pdf(), filetype="pdf")[0]
        png = page.get_pixmap(dpi=72).tobytes("png")
        _, artifacts, s = await _session("bericht.png", png)
        pdf, report = await exports.layout_pdf(artifacts, s, 1)
        assert "Maintenance report basement" in pymupdf.open(stream=pdf, filetype="pdf")[0].get_text()

    asyncio.run(main())


def test_lines_inside_figures_are_left_alone():
    result = {"width": 1240, "height": 1754, "lines": [
        {"box": [150, 1300, 500, 1330], "text": "Schaltschrank", "words": []},  # a label in the picture
        {"box": [150, 200, 900, 230], "text": "Ein Absatz.", "words": []},
    ]}
    doc = pymupdf.open(stream=_scanned_pdf(), filetype="pdf")
    pix = scan.render(doc[0])
    page = scan.lines_from_ocr(result, doc[0], pix, 1, [(100, 1200, 800, 1500)])
    assert [ln.text for ln in page.lines] == ["Ein Absatz."] and len(page.figures) == 1
    assert scan.script_for("zh-Hans") == "cjk" and scan.script_for("de") == "latin"


@pytest.mark.layout
def test_real_ocr_on_the_scanned_sample(monkeypatch):
    """The real PP-OCRv5 server on samples/abnahmeprotokoll-scanned.pdf. Opt-in: RUN_LAYOUT_TESTS=1."""
    data = (SAMPLES / "abnahmeprotokoll-scanned.pdf").read_bytes()

    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        segs = {
            "p1.1": {"id": "p1.1", "page": 1, "kind": "heading", "source": "# Abnahmeprotokoll – Umspannwerk Nord",
                     "target": "# Acceptance Report – Substation North", "translatable": True},
            "p1.4": {"id": "p1.4", "page": 1, "kind": "paragraph", "translatable": True,
                     "source": "Gegenstand der Abnahme ist die Erneuerung der 110-kV-Schaltanlage einschließlich der "
                               "Sekundärtechnik. Die Arbeiten wurden gemäß LV-Position 4.2.7 ausgeführt. Der Auftragnehmer "
                               "hat die Prüfprotokolle vollständig übergeben.",
                     "target": "The acceptance covers the renewal of the 110 kV switchgear including the secondary systems. "
                               "The work was carried out in accordance with LV item 4.2.7. The contractor has handed over "
                               "all test records."},
        }
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:filename": "a.pdf", "doc:source_artifact": "source", "doc:source_lang": "German", "doc:layout_capable": False,
            "doc:seg_ids": list(segs), **{st.seg_key(k): v for k, v in segs.items()},
            "doc:versions": [{"version": 1, "note": "Draft", "changed": list(segs), "artifact_version": 0}]})
        await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename="source",
                                      artifact=types.Part.from_bytes(data=data, mime_type="application/pdf"))
        await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename=st.TRANSLATION_ARTIFACT,
                                      artifact=types.Part(text=json.dumps({k: v["target"] for k, v in segs.items()})))
        try:
            pdf, report = await exports.layout_pdf(artifacts, s, 1)
        finally:
            await layout.close()
        assert {report["segments"][i]["status"] for i in segs} <= {"fit", "shrunk"}
        text = pymupdf.open(stream=pdf, filetype="pdf")[0].get_text()
        assert "Substation North" in text and "test records" in text

    monkeypatch.setattr(layout, "available", lambda: True)
    asyncio.run(main())

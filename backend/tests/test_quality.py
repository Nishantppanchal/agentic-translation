"""Untranslated / merged-segment detection, unit level and through the real workflow."""

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

from translator import qa
from translator import state as st
from translator.agents import pipeline

from .test_flow import _prompt, _reply

# --------------------------------------------------------------------------- #
# Unit checks
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source, target, expected",
    [
        ("Die Anlage wird unter Vorbehalt abgenommen.", "", True),  # dropped
        ("Die Anlage wird unter Vorbehalt abgenommen.", "Die Anlage wird unter Vorbehalt abgenommen.", True),  # echoed
        ("Die Anlage wird unter Vorbehalt abgenommen.", "The plant is accepted with reservations.", False),
        ("Projekt-Nr.: UW-2291", "Projekt-Nr.: UW-2291", False),  # codes / names may stay identical
        ("Dipl.-Ing. M. Weber", "Dipl.-Ing. M. Weber", False),
        ("设备在上述缺陷整改完成前有条件验收。", "设备在上述缺陷整改完成前有条件验收。", True),
    ],
)
def test_looks_untranslated(source, target, expected):
    assert qa.looks_untranslated(source, target) is expected


def _batch(*sources: str) -> list[dict]:
    return [{"id": f"p1.{i}", "source": s} for i, s in enumerate(sources, start=1)]


SOURCES = (
    "Die Arbeiten wurden gemäß der Leistungsbeschreibung vollständig ausgeführt.",
    "Der Auftragnehmer hat alle Prüfprotokolle fristgerecht übergeben.",
    "Die festgestellten Mängel sind bis zum Monatsende zu beseitigen.",
    "Eine Nachbegehung ist für die achtzehnte Kalenderwoche vorgesehen.",
)
GOOD = {
    "p1.1": "The work was fully carried out according to the specification.",
    "p1.2": "The contractor handed over all test reports on time.",
    "p1.3": "The identified defects must be remedied by the end of the month.",
    "p1.4": "A follow-up inspection is planned for calendar week eighteen.",
}


def test_well_formed_batch_is_not_suspected():
    assert qa.suspect_merges(_batch(*SOURCES), GOOD) == set()


def test_text_swallowed_by_a_neighbour_is_suspected():
    merged = {**GOOD, "p1.2": GOOD["p1.2"] + " " + GOOD["p1.3"], "p1.3": ""}
    assert qa.suspect_merges(_batch(*SOURCES), merged) == {"p1.2", "p1.3"}


def test_duplicated_neighbour_text_is_suspected():
    dup = {**GOOD, "p1.2": GOOD["p1.2"] + " " + GOOD["p1.3"]}
    assert qa.suspect_merges(_batch(*SOURCES), dup) == {"p1.2", "p1.3"}


def test_reported_terms_must_occur_in_the_source():
    segs = [{"source": "地下室电缆桥架未接地"}, {"source": "Die Kabelpritsche im Keller"}]
    assert qa.in_source("电缆桥架", segs) and qa.in_source("kabelpritsche", segs)
    assert not qa.in_source("p1.7 fragment (配电柜 / 接地连接 list)", segs)
    assert not qa.in_source("缺陷 / 整改", segs)


def test_flags_become_forced_major_issues():
    segs = [{"id": "p1.1", "flags": [qa.UNTRANSLATED]}, {"id": "p1.2", "flags": []}]
    [issue] = qa.flag_issues(segs)
    assert issue["segment_id"] == "p1.1" and issue["severity"] == "major" and issue["auto"]


# --------------------------------------------------------------------------- #
# Through the workflow (scripted model)
# --------------------------------------------------------------------------- #

PAGE_1 = "# Abnahmeprotokoll\n\n" + "\n\n".join(SOURCES)
PAGE_2 = "## Ergebnis\n\nDie Anlage wird unter Vorbehalt der genannten Mängel abgenommen und freigegeben."
EN = {**{s: GOOD[f"p1.{i}"] for i, s in enumerate(SOURCES, start=1)}, "# Abnahmeprotokoll": "# Acceptance report",
      "## Ergebnis": "## Result",
      "Die Anlage wird unter Vorbehalt der genannten Mängel abgenommen und freigegeben.":
          "The plant is accepted and released, subject to the defects listed."}
CALLS: list[str] = []


def _pdf() -> bytes:
    doc = pymupdf.open()
    for text in ("Seite eins", "Seite zwei"):
        doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def _segs(text: str) -> list[tuple[str, str]]:
    return re.findall(r'<seg id="([^"]+)">\n(.*?)\n</seg>', text, re.S)


def _translate(mode: str):
    """mode: 'merge-then-fix' | 'echo-then-refine'."""

    def callback(callback_context, llm_request):
        text = _prompt(llm_request)
        CALLS.append(text)
        out = []
        for sid, src in _segs(text):
            en = EN.get(src.strip(), src)
            if mode == "merge-then-fix" and "IMPORTANT: in an earlier attempt" not in text:
                # p1.1 is the heading, so the four sentences are p1.2–p1.5.
                if sid == "p1.4":
                    en = GOOD["p1.3"] + " " + GOOD["p1.4"]  # swallows the next segment…
                elif sid == "p1.5":
                    en = ""  # …which is left empty
            if mode == "echo-then-refine" and sid == "p2.2":
                en = src  # left in German
            out.append(f'<seg id="{sid}">{en}</seg>')
        if "Segments to translate (page 1)" in text:
            out.append("<brief>Acceptance report for a substation renewal; contractor vs. client; formal register.</brief>")
        return _reply("\n".join(out))

    return callback


def _refine(callback_context, llm_request):
    text = _prompt(llm_request)
    return _reply("\n".join(f'<seg id="{sid}">{EN[src.split("TRANSLATION:")[0].strip()]}</seg>'
                            for sid, src in re.findall(r'<pair id="([^"]+)">\nSOURCE:\n(.*?)\n</pair>', text, re.S)))


@pytest.fixture
def run_doc(monkeypatch):
    CALLS.clear()
    page = iter([PAGE_1, PAGE_2])
    monkeypatch.setattr(pipeline.ocr_extractor, "before_model_callback", lambda *_: _reply(next(page)))
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))
    monkeypatch.setattr(pipeline.figure_detector, "before_model_callback", lambda *_: _reply("<none/>"))
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", lambda *_: _reply("<none/>"))  # reviewer sees nothing wrong
    monkeypatch.setattr(pipeline.refiner, "before_model_callback", _refine)

    async def run(mode: str) -> dict:
        monkeypatch.setattr(pipeline.translator, "before_model_callback", _translate(mode))
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        runner = Runner(app=App(name="t", root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:filename": "a.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "German",
            "doc:target_lang": "English", "doc:questions": [], "doc:versions": []})
        await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename="source.pdf",
                                      artifact=types.Part.from_bytes(data=_pdf(), mime_type="application/pdf"))
        async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            pass
        return (await sessions.get_session(app_name="t", user_id="u", session_id=s.id)).state

    return lambda mode: asyncio.run(run(mode))


def test_merged_segments_are_retried_separately(run_doc):
    state = run_doc("merge-then-fix")
    assert any("IMPORTANT: in an earlier attempt" in c for c in CALLS)  # targeted retry happened
    segs = {s["id"]: s for s in st.get_segments(state)}
    assert segs["p1.4"]["target"] == GOOD["p1.3"] and segs["p1.5"]["target"] == GOOD["p1.4"]
    assert not any(s.get("flags") for s in segs.values())


def test_untranslated_segment_is_forced_through_refine(run_doc):
    state = run_doc("echo-then-refine")
    segs = {s["id"]: s for s in st.get_segments(state)}
    # The reviewer said nothing, but the flag forced a fix.
    assert segs["p2.2"]["target"].startswith("The plant is accepted") and not segs["p2.2"]["flags"]
    [round1] = state["doc:review_report"][:1]
    assert any(i.get("auto") and i["segment_id"] == "p2.2" for i in round1["issues"])
    assert [v["note"] for v in state["doc:versions"]] == ["Draft translation", "AI review fixes"]


def test_document_brief_is_carried_to_the_next_page(run_doc):
    state = run_doc("merge-then-fix")
    assert state["doc:brief"].startswith("Acceptance report for a substation renewal")
    page2 = next(c for c in CALLS if "Segments to translate (page 2)" in c)
    assert "Document brief so far" in page2 and "contractor vs. client" in page2

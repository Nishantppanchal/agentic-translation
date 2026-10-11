"""LQA: MQM arithmetic, word counts, the independent LQA run, and review scores + forced QA issues
in the pipeline."""

from __future__ import annotations

import asyncio
import json
import re

import pymupdf
import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.models import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import lqa, projects, structured
from translator import state as st
from translator.agents import pipeline
from translator.agents.lqa import lqa_reviewer, lqa_workflow
from translator.formats import parse_issues, parse_scores


def _reply(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _prompt(llm_request) -> str:
    return "\n".join(p.text or "" for c in llm_request.contents for p in c.parts or [] if p.text)


# --------------------------------------------------------------------------- #
# Arithmetic
# --------------------------------------------------------------------------- #


def test_word_count_ignores_markup_and_counts_cjk_by_characters():
    assert lqa.word_count("## 3. Ergebnis") == 2
    assert lqa.word_count("Die **Anlage** ist abgenommen.") == 4
    assert lqa.word_count("| Nr. | Frist |\n|---|---|\n| 1 | 30.04. |") == 4  # a date is one word
    assert lqa.word_count("本次验收合格") == 3  # 6 characters ÷ 2
    assert lqa.word_count("Dipl.-Ing. M. Weber") == 4
    assert lqa.word_count("Frist bis 30.04.2026, Spannung 1.500,5 V") == 6


def test_mqm_score():
    issues = [
        {"category": "accuracy", "severity": "major"},
        {"category": "fluency", "severity": "minor"},
        {"category": "fluency", "severity": "minor"},
        {"category": None, "severity": "critical"},
    ]
    card = lqa.scorecard(issues, words=1000, threshold=90)
    assert card["penalty"] == 5 + 1 + 1 + 25 and card["score"] == 68.0 and not card["passed"]
    assert card["matrix"]["fluency"]["minor"] == 2 and card["matrix"]["other"]["critical"] == 1
    assert card["counts"] == {"minor": 2, "major": 1, "critical": 1}
    card = lqa.scorecard(issues[:3], words=350, threshold=90)
    assert card["score"] == round(100 - 7 * 1000 / 350, 1) and not card["passed"]  # 80.0
    assert lqa.scorecard([], words=350)["score"] == 100 and "other" not in lqa.scorecard([], words=350)["matrix"]
    assert lqa.scorecard([{"category": "style", "severity": "critical"}] * 9, words=100)["score"] == 0  # clamped


def test_parsers_are_tolerant():
    text = """<error seg="p1.2" category="Linguistic conventions" severity="Major" span="is accepted">wrong tense → was accepted</error>
<error seg="p1.3" severity="weird">no category → fix</error>
<score seg="p1.2">72</score><score seg="p1.3">about 95.5</score><score seg="p1.4">n/a</score>"""
    errors = parse_issues(text, "error")
    assert [(e["segment_id"], e["category"], e["severity"], e["span"]) for e in errors] == [
        ("p1.2", "fluency", "major", "is accepted"), ("p1.3", None, "minor", "")]
    assert parse_scores(text) == {"p1.2": 72, "p1.3": 96}
    obj = {"errors": [{"segment_id": "p1.2", "category": "accuracy", "severity": "critical", "span": "", "problem": "x",
                       "suggestion": "y"}, {"segment_id": "", "problem": "dropped"}],
           "scores": [{"segment_id": "p1.2", "score": 140}, {"segment_id": "p1.3"}]}
    assert [e["severity"] for e in structured.issues_from(obj, "errors")] == ["critical"]
    assert structured.scores_from(obj) == {"p1.2": 100}


# --------------------------------------------------------------------------- #
# The LQA run
# --------------------------------------------------------------------------- #

SEGS = {
    "p1.1": {"id": "p1.1", "page": 1, "kind": "heading", "source": "## Ergebnis", "target": "## Result", "translatable": True,
             "status": "confirmed", "origin": "mt"},
    "p1.2": {"id": "p1.2", "page": 1, "kind": "paragraph", "source": "Die Anlage wird unter Vorbehalt abgenommen.",
             "target": "The plant is accepted.", "translatable": True, "status": "draft", "origin": "mt"},
    "p2.1": {"id": "p2.1", "page": 2, "kind": "paragraph", "source": "Die Frist endet am 30.04.2026.",
             "target": "The deadline ends on 30 April 2026.", "translatable": True, "status": "draft", "origin": "mt"},
    "p2.2": {"id": "p2.2", "page": 2, "kind": "footer", "source": "- 2 -", "target": "- 2 -", "translatable": False},
}


async def _lqa_session(**state):
    sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
    runner = Runner(app=App(name="t", root_agent=lqa_workflow), session_service=sessions, artifact_service=artifacts)
    s = await sessions.create_session(app_name="t", user_id="u", state={
        "doc:status": "ready", "doc:seg_ids": list(SEGS), "doc:source_lang": "German", "doc:target_lang": "English",
        "doc:versions": [{"version": 3, "note": "x", "changed": [], "artifact_version": 2}],
        **{st.seg_key(k): v for k, v in SEGS.items()}, **state})
    return sessions, runner, s


async def _run(runner, sessions, s):
    async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="LQA")])):
        pass
    return await sessions.get_session(app_name="t", user_id="u", session_id=s.id)


def test_lqa_run_scores_the_document_and_updates_qe(monkeypatch):
    prompts_seen: list[str] = []

    def fake(callback_context, llm_request):
        text = _prompt(llm_request)
        prompts_seen.append(text)
        out = []
        if '<pair id="p1.2">' in text:
            out.append('<error seg="p1.2" category="accuracy" severity="major" span="is accepted">"unter Vorbehalt" omitted → accepted with reservations</error>')
            out += ['<score seg="p1.1">100</score>', '<score seg="p1.2">60</score>']
        else:
            out.append('<error seg="p2.1" category="fluency" severity="minor" span="deadline ends">tautology → the deadline is</error>')
        return _reply("\n".join(out))  # no score for p2.1: tolerated

    monkeypatch.setattr(lqa_reviewer, "before_model_callback", fake)
    pid = projects.get_store().create_project("P", "German", "Use British spelling.", lqa_threshold=95)["id"]

    async def main():
        sessions, runner, s = await _lqa_session(**{"doc:project_id": pid})
        s = await _run(runner, sessions, s)
        result = s.state["doc:lqa"]
        assert len(prompts_seen) == 2 and "Use British spelling." in prompts_seen[0]  # one call per page, style guide
        assert "- 2 -" not in "".join(prompts_seen)  # non-translatable footer isn't assessed
        assert (result["version"], result["words"], result["penalty"], result["threshold"]) == (3, 12, 6, 95)
        assert result["score"] == 0 and not result["passed"]  # 6 points in 12 words: far below, clamped at 0
        assert result["scores"] == {"p1.1": 100, "p1.2": 60}
        assert st.get_segment(s.state, "p1.2")["qe"] == 60 and st.get_segment(s.state, "p1.2")["status"] == "draft"
        assert st.get_segment(s.state, "p1.2")["target"] == "The plant is accepted."  # LQA never edits
        assert st.get_segment(s.state, "p2.1").get("qe") is None
        last = [e for e in s.events if e.content and e.content.parts and e.content.parts[0].text][-1].content.parts[0].text
        assert last.startswith("LQA score 0") and "fail (threshold 95)" in last and "1 major, 1 minor in 12 words" in last

    asyncio.run(main())


@pytest.mark.structured
def test_lqa_run_with_json_output(monkeypatch):
    monkeypatch.setattr(structured, "enabled", lambda role: True)
    schemas = []

    def fake(callback_context, llm_request):
        schemas.append(llm_request.config.response_schema)
        ids = re.findall(r'<pair id="([^"]+)">', _prompt(llm_request))
        return _reply(json.dumps({"errors": [], "scores": [{"segment_id": i, "score": 98} for i in ids]}))

    monkeypatch.setattr(lqa_reviewer, "before_model_callback", lambda cc, req: (structured.inject_schema(cc, req), fake(cc, req))[1])

    async def main():
        sessions, runner, s = await _lqa_session()
        s = await _run(runner, sessions, s)
        assert s.state["doc:lqa"]["score"] == 100 and s.state["doc:lqa"]["passed"]
        assert s.state["doc:lqa"]["scores"] == {"p1.1": 98, "p1.2": 98, "p2.1": 98}
        assert schemas[0]["title"] == "lqa" and set(schemas[0]["properties"]) == {"errors", "scores"}

    asyncio.run(main())


# --------------------------------------------------------------------------- #
# Pipeline review: QA errors are forced issues; scores become qe
# --------------------------------------------------------------------------- #


def test_review_forces_qa_errors_and_records_scores(monkeypatch):
    page = "# Bericht\n\nDie Frist endet am 30.04.2026.\n\nDie Anlage ist geerdet."
    review_prompts, refine_prompts = [], []

    def fake_translate(callback_context, llm_request):
        segs = re.findall(r'<seg id="([^"]+)">\n(.*?)\n</seg>', _prompt(llm_request), re.S)
        en = {"# Bericht": "# Report", "Die Frist endet am 30.04.2026.": "The deadline ends soon.",  # date dropped
              "Die Anlage ist geerdet.": "The plant is earthed."}
        return _reply("\n".join(f'<seg id="{sid}">{en[src]}</seg>' for sid, src in segs))

    def fake_review(callback_context, llm_request):
        text = _prompt(llm_request)
        review_prompts.append(text)
        if "ends soon" in text:
            return _reply('<score seg="p1.1">100</score><score seg="p1.2">40</score><score seg="p1.3">95</score>')
        return _reply('<score seg="p1.2">97</score>')

    def fake_refine(callback_context, llm_request):
        refine_prompts.append(_prompt(llm_request))
        return _reply('<seg id="p1.2">The deadline ends on 30 April 2026.</seg>')

    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Bericht")
    monkeypatch.setattr(pipeline.ocr_extractor, "before_model_callback", lambda *_: _reply(page))
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))
    monkeypatch.setattr(pipeline.figure_detector, "before_model_callback", lambda *_: _reply("<none/>"))
    monkeypatch.setattr(pipeline.translator, "before_model_callback", fake_translate)
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", fake_review)
    monkeypatch.setattr(pipeline.refiner, "before_model_callback", fake_refine)

    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        runner = Runner(app=App(name="t", root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:filename": "a.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "German",
            "doc:target_lang": "English", "doc:questions": [], "doc:versions": []})
        await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename="source.pdf",
                                      artifact=types.Part.from_bytes(data=pdf.tobytes(), mime_type="application/pdf"))
        async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            pass
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        assert s.state["doc:status"] == "ready"
        # The missing date was a forced issue, told to the reviewer (not to repeat) and fixed by the refiner.
        assert "[p1.2] Automatic QA (numbers & dates): Date 30.04.2026" in review_prompts[0]
        round1 = s.state["doc:review_report"][0]["issues"]
        assert [(i["segment_id"], i["severity"], i["category"], i.get("auto")) for i in round1] == [("p1.2", "major", "accuracy", True)]
        assert "Date 30.04.2026" in refine_prompts[0]
        p12 = st.get_segment(s.state, "p1.2")
        assert p12["target"] == "The deadline ends on 30 April 2026." and p12["ai_check"] == "passed"
        assert (p12["qe"], st.get_segment(s.state, "p1.3")["qe"]) == (97, 95)  # re-scored after the fix

    asyncio.run(main())

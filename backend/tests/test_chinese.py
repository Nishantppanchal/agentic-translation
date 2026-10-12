"""Chinese (CJK) documents: segmentation, text layers, find/replace without spaces, download names,
and the full zh → en workflow (figure + clarify + termbase) with a scripted model."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import state as st
from translator.agents import pipeline
from translator.agents.editor_tools import replace_in_translation
from translator.documents import Page, load_pages, segments_from_pages, split_blocks
from translator.downloads import content_disposition

from .test_flow import _prompt, _reply
from .fakes import fake_ocr

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
ZH_PDF = SAMPLES / "yanshou-baogao.pdf"
ZH_SCAN = SAMPLES / "yanshou-baogao-scanned.pdf"


def test_chinese_markdown_is_segmented():
    md = (
        "# 设备验收报告\n\n日期：2026年3月14日\n\n## 一、验收范围\n\n本次验收范围为110千伏开关设备的更新改造。\n\n"
        "| 序号 | 描述 |\n|---|---|\n| 1 | 地下室电缆桥架未接地 |\n\n2026"
    )
    assert [b.kind for b in split_blocks(md)] == ["heading", "paragraph", "heading", "paragraph", "table", "paragraph"]
    segs = segments_from_pages([(1, md)])
    assert [s["translatable"] for s in segs] == [True, True, True, True, True, False]  # bare "2026" is copied


def test_chinese_pdf_text_layer_and_figure():
    [page] = load_pages(ZH_PDF.read_bytes(), ZH_PDF.name)
    assert page.has_text_layer and not page.is_scan
    [fig] = page.figures
    assert fig.anchor.startswith("图1")  # the caption right below the diagram
    [scan] = load_pages(ZH_SCAN.read_bytes(), ZH_SCAN.name)
    assert scan.is_scan and scan.figures == []


def test_short_chinese_text_counts_as_a_text_layer():
    # 23 characters of Chinese carry as much text as ~45 Latin characters.
    assert Page(1, b"", "image/png", "本次验收范围为开关设备的更新改造，包括二次系统").has_text_layer
    assert not Page(1, b"", "image/png", "Seite 1").has_text_layer


def _ctx(target: str):
    seg = {"id": "p1.1", "page": 1, "source": "x", "target": target, "translatable": True}
    return SimpleNamespace(state={"doc:seg_ids": ["p1.1"], st.seg_key("p1.1"): seg})


@pytest.mark.parametrize(
    "target, find, replace, expected",
    [
        # No spaces between Chinese words: a term must match inside a sentence.
        ("地下室电缆桥架未接地。电缆桥架应整改。", "电缆桥架", "电缆托架", "地下室电缆托架未接地。电缆托架应整改。"),
        # Latin acronym glued to Chinese text.
        ("UPS电源的直流母线", "UPS", "不间断电源", "不间断电源电源的直流母线"),
        # Latin whole-word matching still applies.
        ("cable glands and the cable gland", "cable gland", "cable tray", "cable glands and the cable tray"),
    ],
)
def test_replace_works_without_spaces(target, find, replace, expected):
    ctx = _ctx(target)
    replace_in_translation(find, replace, [], ctx)
    [change] = ctx.state["doc:proposal"]["changes"]
    assert change["after"] == expected


def test_download_name_with_chinese_characters():
    header = content_disposition("验收报告.English.md")
    header.encode("latin-1")  # HTTP headers must be latin-1 encodable
    assert "filename*=UTF-8''%E9%AA%8C%E6%94%B6%E6%8A%A5%E5%91%8A.English.md" in header
    assert 'filename="' in header  # ASCII fallback for old clients


# --------------------------------------------------------------------------- #
# Full zh → en workflow with a scripted model
# --------------------------------------------------------------------------- #

ZH_PAGE = """# 设备验收报告——北区变电站

日期：2026年3月14日 ｜ 项目编号：UW-2291

## 一、验收范围

本次验收范围为110千伏开关设备的更新改造，包括二次系统。

| 序号 | 描述 | 整改期限 |
|---|---|---|
| 1 | 地下室电缆桥架未接地 | 2026年4月30日 |

图1：地下室设备概览

[[FIGURE 1]]

## 三、结论

设备在上述缺陷整改完成前有条件验收。"""

EN = {
    "设备验收报告——北区变电站": "Equipment Acceptance Report – North Substation",
    "日期：2026年3月14日 ｜ 项目编号：UW-2291": "Date: 14 March 2026 | Project No.: UW-2291",
    "一、验收范围": "1. Scope of Acceptance",
    "本次验收范围为110千伏开关设备的更新改造，包括二次系统。": "This acceptance covers the renewal of the 110 kV switchgear, including the secondary systems.",
    "序号": "No.", "描述": "Description", "整改期限": "Deadline", "年": "-", "月": "-", "日": "",
    "地下室": "basement ", "未接地": " not grounded",
    "图1：地下室设备概览": "Figure 1: Basement equipment overview",
    "三、结论": "3. Conclusion",
    "设备在上述缺陷整改完成前有条件验收。": "The equipment is conditionally accepted until the above defects are rectified.",
    "配电柜": "Distribution cabinet", "UPS电源": "UPS power supply", "缺少接地连接": "Missing ground connection",
}


ZH_LEGEND = "缺少接地连接\n配电柜\nUPS电源\n电缆桥架"  # the text inside the picture


TRANSLATE_PROMPTS: list[str] = []


def fake_translate(callback_context, llm_request):
    text = _prompt(llm_request)
    TRANSLATE_PROMPTS.append(text)
    tray = "cable tray" if "电缆桥架: means" in text else "cable bridge"
    out = []
    for sid, src in re.findall(r'<seg id="([^"]+)">\n(.*?)\n</seg>', text, re.S):
        en = src.replace("电缆桥架", tray)
        for zh, e in sorted(EN.items(), key=lambda kv: -len(kv[0])):
            en = en.replace(zh, e)
        out.append(f'<seg id="{sid}">{en}</seg>')
        if "电缆桥架" in src and tray == "cable bridge":
            out.append(f'<term source="电缆桥架" guess="cable bridge" segs="{sid}">could be cable tray or cable bridge</term>')
        if "开关设备" in src:
            out.append('<keep source="开关设备">switchgear</keep>')
    out.append("<source_lang>Chinese (Simplified)</source_lang>")
    return _reply("\n".join(out))


@pytest.fixture(autouse=True)
def fake_models(monkeypatch):
    TRANSLATE_PROMPTS.clear()
    fake_ocr(monkeypatch, ZH_PAGE, legends={1: ZH_LEGEND})
    monkeypatch.setattr(pipeline.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))
    monkeypatch.setattr(pipeline.translator, "before_model_callback", fake_translate)
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", lambda *_: _reply("<none/>"))


def test_chinese_document_to_english():
    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        runner = Runner(app=App(name="t", root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        s = await sessions.create_session(
            app_name="t", user_id="u",
            state={"doc:filename": "验收报告.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "auto-detect",
                   "doc:target_lang": "English", "doc:questions": [], "doc:versions": []},
        )
        await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename="source.pdf",
                                      artifact=types.Part.from_bytes(data=ZH_PDF.read_bytes(), mime_type="application/pdf"))

        async def run(message):
            interrupt = None
            async for ev in runner.run_async(user_id="u", session_id=s.id, new_message=message):
                for fc in ev.get_function_calls():
                    if fc.name == "adk_request_input":
                        interrupt = fc.id
            return interrupt

        interrupt = await run(types.Content(role="user", parts=[types.Part(text="翻译")]))
        state = (await sessions.get_session(app_name="t", user_id="u", session_id=s.id)).state
        assert state["doc:status"] == "awaiting_answers"
        assert state["doc:detected_lang"] == "Chinese (Simplified)"
        assert state["doc:termbase"] == {"开关设备": "switchgear"}
        segs = st.get_segments(state)
        kinds = [x["kind"] for x in segs]
        # The PDF anchor puts the figure right above its caption, even though OCR placed it below.
        fig_at = kinds.index("figure")
        assert segs[fig_at + 1]["source"].startswith("图1")
        assert segs[fig_at]["source"] == "缺少接地连接\n配电柜\nUPS电源\n电缆桥架"
        [q] = st.open_questions(state)
        assert q["term"] == "电缆桥架"

        answer = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=interrupt, name="adk_request_input", response={"result": {q["id"]: "cable tray"}}))])
        await run(answer)
        state = (await sessions.get_session(app_name="t", user_id="u", session_id=s.id)).state
        assert state["doc:status"] == "ready"
        assert state["doc:glossary"]["电缆桥架"]["note"] == "cable tray"
        translations = {x["id"]: x["target"] for x in st.get_segments(state)}
        table = next(t for t in translations.values() if t and t.startswith("| No."))
        legend = translations[segs[fig_at]["id"]]
        assert "basement cable tray not grounded" in table
        assert "cable tray" in legend and "Missing ground connection" in legend  # figure legend re-translated too
        assert [v["note"] for v in state["doc:versions"]] == ["Draft translation", "Applied your clarifications"]

    asyncio.run(main())

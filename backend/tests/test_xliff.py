"""XLIFF 2.0 round trips and re-import rules; Word through the pipeline; code-safe edits."""

from __future__ import annotations

import asyncio
import io
import re

import pytest
from docx import Document
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.models import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types
from lxml import etree

from tests.fixtures_office import docx_full
from translator import exports, projects, proposals, segments
from translator import state as st
from translator.agents import pipeline
from translator.filters import xliff

SEGS = [
    {"id": "p1.1", "page": 1, "kind": "heading", "source": "## Ergebnis", "target": "## Result", "translatable": True, "status": "confirmed"},
    {"id": "p1.2", "page": 1, "kind": "paragraph", "source": 'Die <g id="1">Anlage</g> ist abgenommen.<x id="2"/>',
     "target": 'The <g id="1">plant</g> is accepted.<x id="2"/>', "translatable": True, "status": "draft", "where": "Body"},
    {"id": "p1.3", "page": 1, "kind": "paragraph", "source": "Neu", "target": None, "translatable": True, "status": "new"},
    {"id": "p1.4", "page": 1, "kind": "paragraph", "source": "2026", "target": "2026", "translatable": False, "status": "confirmed", "locked": True},
]
NS = {"x": xliff.NS}


def _export() -> bytes:
    return xliff.export(SEGS, src="de", tgt="en", original="a.docx", notes={"p1.2": ["QA: check the tense"]})


def test_export_structure_states_and_codes():
    root = etree.fromstring(_export())
    assert (root.get("version"), root.get("srcLang"), root.get("trgLang")) == ("2.0", "de", "en")
    units = {u.get("id"): u for u in root.iterfind(".//x:unit", NS)}
    assert [u for u in units] == ["p1.1", "p1.2", "p1.3", "p1.4"]
    seg = units["p1.2"].find("x:segment", NS)
    assert (seg.get("state"), seg.get("subState")) == ("translated", "at:draft")
    assert etree.tostring(seg.find("x:target", NS), encoding="unicode").count('<pc id="1">plant</pc>') == 1
    assert seg.find("x:source/x:ph", NS).get("id") == "2"
    assert [n.text for n in units["p1.2"].iterfind(".//x:note", NS)] == ["Location: Body", "QA: check the tense"]
    assert units["p1.1"].find("x:segment", NS).get("state") == "reviewed"  # confirmed by the translator
    assert units["p1.3"].find("x:segment", NS).get("state") == "initial" and units["p1.3"].find(".//x:target", NS) is None
    assert units["p1.4"].get("translate") == "no" and units["p1.4"].get(f"{{{xliff.AT}}}locked") == "yes"


def test_export_then_import_is_a_no_op():
    changes, report = xliff.import_changes(_export(), [st.normalize(s) for s in SEGS], src="de", tgt="en")
    assert changes == [] and report["unchanged"] == 4 and report["unknown"] == [] and report["source_changed"] == []


def _edited(**targets) -> bytes:
    data = _export().decode()
    for sid, (old, new, state) in targets.items():
        data = re.sub(rf'(<unit id="{re.escape(sid)}".*?<segment state=")[^"]*(")', rf"\g<1>{state}\2", data, flags=re.S)
        data = data.replace(old, new)
    return data.encode()


def test_import_rules():
    segs = [st.normalize(s) for s in SEGS]
    data = _edited(**{
        "p1.2": ("is accepted.", "has been accepted.", "translated"),
        "p1.1": ("## Result</target>", "## Outcome</target>", "translated"),  # confirmed here, not final there
    }).replace(b'<unit id="p1.3"', b'<unit id="p9.9"')
    changes, report = xliff.import_changes(data, segs, src="de-DE", tgt="en-GB")
    assert [(c["segment_id"], c["after"], c["status"]) for c in changes] == [
        ("p1.2", 'The <g id="1">plant</g> has been accepted.<x id="2"/>', "draft")]
    assert report["kept_confirmed"] == ["p1.1"] and report["unknown"] == ["p9.9"]
    final = _edited(**{"p1.1": ("## Result</target>", "## Outcome</target>", "final")})
    changes, _ = xliff.import_changes(final, segs, src="de", tgt="en")
    assert [(c["segment_id"], c["status"]) for c in changes] == [("p1.1", "reviewed")]  # a final unit wins


def test_import_rejects_wrong_languages_changed_sources_and_broken_codes():
    segs = [st.normalize(s) for s in SEGS]
    with pytest.raises(ValueError, match="de → fr"):
        xliff.import_changes(_export(), segs, src="de", tgt="fr")
    data = _export().replace(b"ist abgenommen.", b"ist nicht abgenommen.").replace(b"## Result</target>", b"## Outcome</target>")
    data = data.replace(b'<unit id="p1.1"', b'<unit id="p1.1"')
    changes, report = xliff.import_changes(data, segs, src="de", tgt="en")
    assert report["source_changed"] == ["p1.2"]
    broken = _export().replace(b'<pc id="1">plant</pc> is accepted', b"plant is now accepted")
    changes, report = xliff.import_changes(broken, segs, src="de", tgt="en")
    assert report["codes"] == ["p1.2"] and changes == []


OTHER_TOOL = b"""<?xml version="1.0" encoding="UTF-8"?>
<xliff xmlns="urn:oasis:names:tc:xliff:document:2.0" version="2.0" srcLang="de-DE" trgLang="en-US">
  <file id="f1" original="handbook.docx">
    <unit id="u1"><segment state="initial"><source>Die <pc id="1" dataRefStart="d1" dataRefEnd="d2">Anlage</pc> pr\xc3\xbcfen<ph id="2" dataRef="d3"/>.</source></segment></unit>
    <unit id="u2"><segment state="final"><source>Ergebnis</source><target>Result</target></segment>
      <segment state="translated"><source>Zweiter Satz.</source><target>Second sentence.</target></segment></unit>
    <unit id="u3" translate="no"><segment><source>ACME-42</source></segment></unit>
  </file>
</xliff>"""


def test_xliff_as_input_and_write_back_keeps_the_original_codes():
    segs, info = xliff.extract(OTHER_TOOL)
    rows = [(s["id"], s["source"], s.get("target"), s.get("status"), s["translatable"]) for s in segs]
    assert rows == [
        ("p1.1", 'Die <g id="1">Anlage</g> prüfen<x id="2"/>.', None, None, True),
        ("p1.2", "Ergebnis", "Result", "reviewed", True),
        ("p1.3", "Zweiter Satz.", "Second sentence.", "draft", True),
        ("p1.4", "ACME-42", "ACME-42", None, False),
    ]
    assert info["src"] == "de-DE" and info["pretranslated"] == 2
    segs[0]["target"] = 'Check the <g id="1">plant</g><x id="2"/>.'
    out, report = xliff.write_back(OTHER_TOOL, [st.normalize(s) for s in segs])
    assert report["written"] == 3 and not report["mismatch"]
    text = out.decode()
    assert '<target>Check the <pc id="1" dataRefStart="d1" dataRefEnd="d2">plant</pc><ph id="2" dataRef="d3"/>.</target>' in text
    assert 'subState="at:reviewed"' in text and 'state="final"' in text


# --------------------------------------------------------------------------- #
# A Word file through the pipeline
# --------------------------------------------------------------------------- #


def _reply(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _prompt(llm_request) -> str:
    return "\n".join(p.text or "" for c in llm_request.contents for p in c.parts or [] if p.text)


def test_word_document_through_the_pipeline(monkeypatch):
    prompts: list[str] = []

    def fake_translate(callback_context, llm_request):
        text = _prompt(llm_request)
        prompts.append(text)
        segs = re.findall(r'<seg id="([^"]+)">\n(.*?)\n</seg>', text, re.S)
        # Translate words only; escape one segment's tags the way models sometimes do.
        out = []
        for sid, src in segs:
            en = re.sub(r"(<[^>]+>)|([^<]+)", lambda m: m[1] or f"EN[{m[2]}]", src)
            if "Kabelpritsche" in src:
                en = en.replace('<g id="1">', "&lt;g id='1'&gt;").replace("</g>", "&lt;/g&gt;", 1)
            out.append(f'<seg id="{sid}">{en}</seg>')
        return _reply("\n".join(out))

    monkeypatch.setattr(pipeline.translator, "before_model_callback", fake_translate)
    monkeypatch.setattr(pipeline.reviewer, "before_model_callback", lambda *_: _reply(""))

    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        runner = Runner(app=App(name="t", root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:filename": "protokoll.docx", "doc:source_artifact": "source.docx", "doc:source_lang": "German",
            "doc:target_lang": "English", "doc:questions": [], "doc:versions": []})
        await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename="source.docx",
                                      artifact=types.Part.from_bytes(data=docx_full(), mime_type="application/octet-stream"))
        events = [e async for e in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")]))]
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        assert s.state["doc:status"] == "ready" and s.state["doc:format"] == "docx"
        said = [e.content.parts[0].text for e in events if e.content and e.content.parts and e.content.parts[0].text]
        assert any("contains 2 tracked changes" in t for t in said)  # the user is told
        assert "Inline codes:" in prompts[0]  # the translator gets the code rules
        segs = {x["id"]: x for x in st.get_segments(s.state)}
        p = next(x for x in segs.values() if "Kabelpritsche" in x["source"])
        assert p["target"].startswith('EN[Die ]<g id="1">EN[Kabelpritsche]</g>')  # escaped tags repaired
        assert not p["flags"]

        content, media, name = await exports.build(artifacts, s, "original", None)
        assert name == "protokoll.English.docx" and media.endswith("wordprocessingml.document")
        assert any("EN[Kabelpritsche]" in par.text for par in Document(io.BytesIO(content)).paragraphs)
        formats = {f["id"]: f for f in await exports.available(artifacts, s)}
        assert formats["original"]["available"] and formats["original"]["ext"] == "docx" and not formats["pdf"]["available"]
        assert formats["original"]["note"] == "2 tracked changes accepted — the file has no revision marks"
        xlf, _, xname = await exports.build(artifacts, s, "xliff", None)
        assert xname == "protokoll.de-en.xlf" and b'<pc id="1">EN[Kabelpritsche]</pc>' in xlf

        # A person's edit that drops a code is refused; one that moves it is fine.
        with pytest.raises(segments.EditConflict, match="Inline codes"):
            await segments.edit_segment(sessions, s, p["id"], target="The cable tray is earthed.")
        moved = '<x id="3"/>The <g id="2">un</g>earthed <g id="1">cable tray</g>. Deadline: 30.04.2026'
        assert (await segments.edit_segment(sessions, s, p["id"], target=moved))["target"] == moved

        # Re-importing our own XLIFF with an edit becomes a proposal.
        xlf, _, _ = await exports.build(artifacts, s, "xliff", None)
        edited = xlf.replace(b"EN[Abnahmeprotokoll]", b"Acceptance certificate")
        changes, report = xliff.import_changes(edited, [st.normalize(x) for x in st.get_segments(s.state)], src="de", tgt="en")
        assert [c["after"] for c in changes] == ["Acceptance certificate"] and report["source_changed"] == []
        s.state["doc:proposal"] = xliff.proposal(changes, "back.xlf")
        await proposals.accept(sessions, artifacts, s)
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        heading = next(x for x in st.get_segments(s.state) if x["source"] == "Abnahmeprotokoll")
        assert (heading["target"], heading["origin"]) == ("Acceptance certificate", "xliff")
        assert s.state["doc:versions"][-1]["note"] == "XLIFF import: back.xlf"

    asyncio.run(main())


def test_tm_exact_match_with_different_codes_is_only_a_reference():
    store = projects.get_store()
    pid = store.create_project("P", "German")["id"]
    store.add_unit(pid, "Die Anlage prüfen.", "Check the plant.")  # stored without codes (e.g. from a PDF)
    seg = {"id": "p1.1", "page": 1, "source": 'Die <g id="1">Anlage</g> prüfen.', "target": None, "translatable": True}
    delta, refs, stats = pipeline._tm_pass({"doc:project_id": pid}, [seg])
    assert delta == {} and refs["p1.1"]["score"] == 99 and stats["fuzzy"] == 1


# --------------------------------------------------------------------------- #
# XLIFF 1.2
# --------------------------------------------------------------------------- #

NS12 = {"x": xliff.NS12}


def test_xliff12_export_states_codes_and_round_trip():
    data = xliff.export(SEGS, src="de", tgt="en", original="a.docx", version="1.2")
    root = etree.fromstring(data)
    assert root.get("version") == "1.2" and root.find("x:file", NS12).get("target-language") == "en"
    units = {u.get("id"): u for u in root.iterfind(".//x:trans-unit", NS12)}
    assert units["p1.1"].get("approved") == "yes" and units["p1.1"].find("x:target", NS12).get("state") == "translated"
    assert units["p1.2"].find("x:target", NS12).get("state") == "needs-review-translation" and units["p1.2"].get("approved") is None
    assert etree.tostring(units["p1.2"].find("x:target", NS12), encoding="unicode").count('<g id="1">plant</g>') == 1
    assert units["p1.4"].get("translate") == "no"
    changes, report = xliff.import_changes(data, [st.normalize(s) for s in SEGS], src="de", tgt="en")
    assert changes == [] and report["unchanged"] == 4
    edited = data.replace(b"is accepted.", b"has been accepted.")
    changes, _ = xliff.import_changes(edited, [st.normalize(s) for s in SEGS], src="de", tgt="en")
    assert [(c["segment_id"], c["status"]) for c in changes] == [("p1.2", "draft")]


TRADOS_LIKE = """<?xml version="1.0" encoding="UTF-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file original="handbuch.docx" source-language="de-DE" target-language="en-GB" datatype="x-docx">
    <body>
      <trans-unit id="1">
        <source>Die Anlage prüfen. Danach <bpt id="1">&lt;b&gt;</bpt>freigeben<ept id="1">&lt;/b&gt;</ept>.</source>
        <seg-source><mrk mtype="seg" mid="1">Die Anlage prüfen.</mrk> <mrk mtype="seg" mid="2">Danach <bpt id="1">&lt;b&gt;</bpt>freigeben<ept id="1">&lt;/b&gt;</ept>.</mrk></seg-source>
        <target><mrk mtype="seg" mid="1">Check the plant.</mrk> <mrk mtype="seg" mid="2"></mrk></target>
      </trans-unit>
      <trans-unit id="2" approved="yes"><source>Ergebnis</source><target state="signed-off">Result</target></trans-unit>
    </body>
  </file>
</xliff>""".encode()


def test_xliff12_input_with_seg_source_and_native_codes():
    segs, info = xliff.extract(TRADOS_LIKE)
    rows = [(s["id"], s["source"], s.get("target"), s.get("status")) for s in segs]
    assert rows == [
        ("p1.1", "Die Anlage prüfen.", "Check the plant.", "draft"),
        ("p1.2", 'Danach <x id="1"/>freigeben<x id="1e"/>.', None, None),
        ("p1.3", "Ergebnis", "Result", "reviewed"),
    ]
    assert info["src"] == "de-DE" and info["tgt"] == "en-GB"
    segs[1]["target"] = 'Then <x id="1"/>approve<x id="1e"/> it.'
    out, report = xliff.write_back(TRADOS_LIKE, [st.normalize(s) for s in segs])
    assert report["written"] == 3 and not report["mismatch"]
    text = out.decode()
    # Both segments stay in their markers; the bold codes keep their native content.
    assert '<mrk mtype="seg" mid="1">Check the plant.</mrk> <mrk mtype="seg" mid="2">Then <bpt id="1">&lt;b&gt;</bpt>approve<ept id="1">&lt;/b&gt;</ept> it.</mrk>' in text
    assert 'state="needs-review-translation"' in text

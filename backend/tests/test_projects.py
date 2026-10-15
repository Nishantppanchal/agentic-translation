"""Projects: the SQLite store (termbase, TM scoring), the TM pass in the pipeline, TM write-back on
human confirmation, termbase write-through, and the project API."""

from __future__ import annotations

import asyncio
import re

import pymupdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.models import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types
from translator.api.routes.projects import router

from translator import projects
from translator.agents import pipeline, workers
from translator.document import edits, memory
from translator.document import state as st
from translator.projects import ProjectStore

from .fakes import fake_ocr


@pytest.fixture()
def store() -> ProjectStore:
    return projects.get_store()  # conftest gives every test a fresh in-memory store


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #


def test_project_crud_and_counts(store):
    p = store.create_project("Acme", "German", "Use British spelling.")
    assert p["name"] == "Acme" and p["documents"] == p["terms"] == p["tm_units"] == 0
    assert (p["auto_confirm_context"], p["lqa_threshold"]) == (True, 90)
    assert store.update_project(p["id"], auto_confirm_context=False, lqa_threshold=95)["auto_confirm_context"] is False
    store.attach("s1", p["id"])
    store.upsert_term(p["id"], "Abnahme", "acceptance")
    store.add_unit(p["id"], "Die Anlage ist abgenommen.", "The plant is accepted.")
    p = store.update_project(p["id"], instructions="US spelling.")
    assert (p["documents"], p["terms"], p["tm_units"], p["instructions"]) == (1, 1, 1, "US spelling.")
    assert store.project_of("s1") == p["id"]
    store.delete_project(p["id"])  # cascades
    assert store.project(p["id"]) is None and store.project_of("s1") is None and store.terms(p["id"]) == []


def test_term_upsert_merges_and_never_erases_a_target(store):
    pid = store.create_project("P")["id"]
    store.upsert_term(pid, "Kabelpritsche", "cable tray", forbidden=["cable bridge"])
    # A clarification answer (note only) must not wipe the approved target or downgrade the status.
    t = store.upsert_term(pid, "Kabelpritsche", "", "metal tray for cables", ["cable ladder"], status="note")
    assert (t["target"], t["note"], t["status"]) == ("cable tray", "metal tray for cables", "approved")
    assert t["forbidden"] == ["cable bridge", "cable ladder"]
    # A person editing the entry replaces fields.
    t = store.update_term(pid, t["id"], target="cable rack", forbidden=["cable tray "])
    assert t["target"] == "cable rack" and t["forbidden"] == ["cable tray"]


def test_terms_in_respects_word_boundaries_and_case(store):
    pid = store.create_project("P")["id"]
    store.upsert_term(pid, "LV", "BoQ", case_sensitive=True)
    store.upsert_term(pid, "Abnahme", "acceptance")
    store.upsert_term(pid, "验收", "acceptance")
    found = lambda text: {t["source"] for t in store.terms_in(pid, [text])}  # noqa: E731
    assert found("gemäß LV-Position 4.2") == {"LV"}
    assert found("die lv-position") == set()  # case-sensitive term
    assert found("Die ABNAHME erfolgt") == {"Abnahme"}
    assert found("Abnahmeprotokoll") == set()  # not a whole word
    assert found("本次验收范围") == {"验收"}  # CJK: no word boundaries


def test_tm_scores_context_exact_and_fuzzy(store):
    pid = store.create_project("P")["id"]
    store.add_unit(pid, "Die Anlage wird unter Vorbehalt abgenommen.", "The plant is accepted with reservations.",
                   prev_source="## Ergebnis")
    store.add_unit(pid, "Der Erdungsanschluss ist herzustellen.", "The earth connection must be made.")

    [m] = store.lookup(pid, "Die Anlage wird unter Vorbehalt abgenommen.", "## Ergebnis", limit=1)
    assert m["score"] == 101
    assert store.lookup(pid, "die anlage wird unter  Vorbehalt abgenommen.", "Other context")[0]["score"] == 100
    fuzzy = store.lookup(pid, "Die Anlage wird unter Vorbehalt nicht abgenommen.")[0]
    assert 75 <= fuzzy["score"] < 100 and fuzzy["target"].startswith("The plant")
    assert store.lookup(pid, "Völlig anderer Satz ohne Bezug.") == []


def test_tm_fuzzy_for_chinese_counts_characters(store):
    pid = store.create_project("P")["id"]
    store.add_unit(pid, "本次验收范围为110千伏开关设备的更新改造。", "The scope covers the upgrade of the 110 kV switchgear.")
    [m] = store.lookup(pid, "本次验收范围为220千伏开关设备的更新改造。")
    assert 75 <= m["score"] < 100


def test_tm_update_replaces_target_and_bulk_reports(store):
    pid = store.create_project("P")["id"]
    assert store.add_unit(pid, "Satz eins.", "Sentence one.", ref="a.pdf#p1.1") == "added"
    assert store.add_unit(pid, "Satz eins.", "Sentence 1.", ref="b.pdf#p2.1") == "updated"  # same source + context
    [m] = store.lookup(pid, "Satz eins.")
    assert (m["target"], m["ref"], m["approval"]) == ("Sentence 1.", "b.pdf#p2.1", "segment")
    assert store.add_unit(pid, "Satz eins.", "Sentence 1.", ref="c.pdf#p9.9") == "unchanged"
    assert store.lookup(pid, "Satz eins.")[0]["ref"] == "b.pdf#p2.1"  # confirming the same wording keeps where it came from
    statuses = store.add_units(pid, [{"source": "Satz eins.", "target": "S1", "approval": "bulk"},  # weaker: kept
                                     {"source": "Satz zwei.", "target": "S2"}, {"source": "", "target": "x"}])
    assert statuses == ["kept", "added", "skipped"]
    assert store.lookup(pid, "Satz eins.")[0]["target"] == "Sentence 1."
    assert store.add_unit(pid, "Satz zwei.", "S2", approval="review") == "unchanged"  # the approval rises
    assert store.lookup(pid, "Satz zwei.")[0]["approval"] == "review"
    assert [u["source"] for u in store.concordance(pid, "zwei")] == ["Satz zwei."]


def test_an_older_tm_database_is_migrated(tmp_path):
    import sqlite3

    path = tmp_path / "projects.db"
    db = sqlite3.connect(path)
    db.executescript("""
        create table projects (id text primary key, name text not null, source_lang text default '',
          instructions text default '', created_at real);
        create table tm_units (id integer primary key, project_id text not null, source text not null,
          target text not null, source_key text not null, prev_key text default '', origin text default '',
          created_at real, updated_at real, unique(project_id, source_key, prev_key));
        insert into projects (id, name) values ('p', 'P');
        insert into tm_units (project_id, source, target, source_key, prev_key, origin)
          values ('p', 'Satz eins.', 'Sentence one.', 'satzeins', '', 'a.pdf#p1.1'),
                 ('p', 'Satz zwei.', 'Sentence two.', 'satzzwei', '', 'import');""")
    db.commit()
    db.close()
    store = ProjectStore(path)
    assert [(m["ref"], m["approval"]) for m in (store.lookup("p", "Satz eins.")[0], store.lookup("p", "Satz zwei.")[0])] == [
        ("a.pdf#p1.1", "segment"), ("import", "import")]


# --------------------------------------------------------------------------- #
# Pipeline: TM pass + project prompts
# --------------------------------------------------------------------------- #

PAGE = (
    "# Abnahmeprotokoll\n\n"
    "Die Anlage wird unter Vorbehalt der genannten Mängel abgenommen.\n\n"
    "Der Erdungsanschluss der Kabelpritsche ist bis zum 30.04. herzustellen.\n\n"
    "Eine Nachbegehung findet am 12.05. statt."
)


def _reply(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _prompt(llm_request) -> str:
    return "\n".join(p.text or "" for c in llm_request.contents for p in c.parts or [] if p.text)


def _pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Abnahmeprotokoll")
    return doc.tobytes()


def test_pipeline_reuses_exact_matches_and_shows_fuzzy_ones(store, monkeypatch):
    pid = store.create_project("Acme", "German", "Write 'earthing', never 'grounding'.")["id"]
    store.add_unit(pid, "# Abnahmeprotokoll", "# Acceptance report")  # 100% (start of document, no context stored)
    store.add_unit(pid, "Die Anlage wird unter Vorbehalt der genannten Mängel abgenommen.",
                   "The plant is accepted subject to the listed defects.", prev_source="# Abnahmeprotokoll")  # 101%
    store.add_unit(pid, "Der Erdungsanschluss der Kabelpritsche ist bis zum 15.03. herzustellen.",
                   "The earthing connection of the cable tray must be made by 15.03.")  # fuzzy
    store.upsert_term(pid, "Kabelpritsche", "cable tray", forbidden=["cable bridge"])
    store.upsert_term(pid, "Schaltschrank", "control cabinet")  # not in the document → not in the prompt

    prompts: list[str] = []

    def fake_translate(callback_context, llm_request):
        text = _prompt(llm_request)
        prompts.append(text)
        segs = re.findall(r'<seg id="([^"]+)">\n(.*?)\n</seg>', text, re.S)
        return _reply("\n".join(f'<seg id="{sid}">EN {src}</seg>' for sid, src in segs))

    fake_ocr(monkeypatch, PAGE)
    monkeypatch.setattr(workers.ocr_checker, "before_model_callback", lambda *_: _reply("<verdict>ok</verdict>"))
    monkeypatch.setattr(workers.translator, "before_model_callback", fake_translate)
    monkeypatch.setattr(workers.reviewer, "before_model_callback", lambda *_: _reply("<none/>"))

    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        runner = Runner(app=App(name="t", root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:filename": "a.pdf", "doc:source_artifact": "source.pdf", "doc:source_lang": "German",
            "doc:target_lang": "English", "doc:questions": [], "doc:versions": [], "doc:project_id": pid})
        await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename="source.pdf",
                                      artifact=types.Part.from_bytes(data=_pdf(), mime_type="application/pdf"))
        async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            pass
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        assert s.state["doc:status"] == "ready"
        segs = {x["id"]: x for x in st.get_segments(s.state)}

        # 100% and 101% are reused without a model call; 101% counts as confirmed.
        assert (segs["p1.1"]["target"], segs["p1.1"]["origin"], segs["p1.1"]["match"], segs["p1.1"]["status"]) == (
            "# Acceptance report", "tm", 100, "draft")
        assert (segs["p1.2"]["origin"], segs["p1.2"]["match"], segs["p1.2"]["status"]) == ("tm", 101, "confirmed")
        [prompt] = prompts
        assert "Abnahmeprotokoll</seg>" not in prompt and "Mängel abgenommen.\n</seg>" not in prompt
        # The fuzzy match is a reference to adapt; the result records where it came from.
        assert "% · Der Erdungsanschluss der Kabelpritsche ist bis zum 15.03. herzustellen. → The earthing connection" in prompt
        # The adapted fuzzy match is machine translation, with the score of the match behind it.
        assert (segs["p1.3"]["origin"], segs["p1.3"]["target"]) == ("mt", "EN " + segs["p1.3"]["source"])
        assert 75 <= segs["p1.3"]["match"] < 100
        assert segs["p1.4"]["origin"] == "mt" and segs["p1.4"]["match"] is None
        assert s.state["doc:tm_stats"] == {"context": 1, "exact": 1, "fuzzy": 1, "words": 11}
        # With auto-confirm off, the 101% match is reused but left for a person to confirm.
        store.update_project(pid, auto_confirm_context=False)
        delta, _, _ = memory.prefill(s.state, [{**segs[k], "target": None, "status": "new", "origin": None} for k in ("p1.1", "p1.2")])
        assert delta[st.seg_key("p1.2")]["status"] == "draft" and delta[st.seg_key("p1.2")]["match"] == 101
        store.update_project(pid, auto_confirm_context=True)
        # Project style guide and only the relevant terms, with the forbidden variant.
        assert "Write 'earthing', never 'grounding'." in prompt
        assert "- Kabelpritsche → cable tray" in prompt and 'NEVER translate Kabelpritsche as "cable bridge"' in prompt
        assert "Schaltschrank" not in prompt

        # A person confirms p1.4 → it is written to the TM with its context; the next lookup is 101%.
        seg = await edits.edit_segment(sessions, s, "p1.4", target="A follow-up inspection takes place on 12.05.", confirm=True)
        assert seg["tm_saved"] and seg["match"] is None
        [m] = store.lookup(pid, segs["p1.4"]["source"], segs["p1.3"]["source"], limit=1)
        assert (m["score"], m["target"]) == (101, "A follow-up inspection takes place on 12.05.")
        # Unconfirmed drafts never reach the TM.
        assert store.lookup(pid, segs["p1.3"]["source"], limit=1)[0]["score"] < 100

    asyncio.run(main())


def test_no_project_means_no_project_prompt_sections(store):
    state = {"doc:glossary": {}}
    assert projects.glossary_for(state, ["Die Kabelpritsche"]) == "(empty)"
    assert projects.instructions_for(state) == "(none)"
    # A deleted project leaves a dangling id: prompts degrade to empty, writes are skipped.
    assert projects.project_id({"doc:project_id": "gone"}) is None
    assert projects.instructions_for({"doc:project_id": "gone"}) == "(none)"


# --------------------------------------------------------------------------- #
# Exchange formats
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client(store):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_project_api_crud(client, store):
    p = client.post("/api/projects", json={"name": "Acme DE→EN", "source_lang": "German", "target_lang": "English"}).json()
    pid = p["id"]
    assert client.get("/api/projects").json()[0]["id"] == pid
    assert client.patch(f"/api/projects/{pid}", json={"name": "", "instructions": "Formal."}).json()["name"] == "Acme DE→EN"

    t = client.post(f"/api/projects/{pid}/terms", json={"source": "Abnahme", "target": "acceptance"}).json()
    assert client.post(f"/api/projects/{pid}/terms", json={"source": " "}).status_code == 400
    client.post(f"/api/projects/{pid}/terms", json={"source": "Frist", "target": "deadline"})
    assert client.patch(f"/api/projects/{pid}/terms/{t['id']}", json={"source": "Frist"}).status_code == 409  # duplicate
    assert client.patch(f"/api/projects/{pid}/terms/{t['id']}", json={"forbidden": ["approval"]}).json()["forbidden"] == ["approval"]

    client.post(f"/api/projects/{pid}/terms", json={"source": "Mängel", "target": "defects"})
    assert client.get(f"/api/projects/{pid}/terms").json()[0]["forbidden"] == ["approval"]
    units = [{"source": "Satz eins.", "target": "Sentence one."}, {"source": "Satz zwei.", "target": "Sentence two."},
             {"source": " ", "target": "skipped: no source"}]
    assert client.post(f"/api/projects/{pid}/tm", json=units).json() == {"added": 2, "updated": 0, "unchanged": 0, "kept": 0}
    assert client.post(f"/api/projects/{pid}/tm", json=[{**units[0], "target": "Sentence 1."}]).json()["updated"] == 1
    # An import with the sentence before it gives context (101%) matches.
    client.post(f"/api/projects/{pid}/tm", json=[{"source": "Satz drei.", "target": "Sentence three.", "prev_source": "Satz zwei."}])
    assert store.lookup(pid, "Satz drei.", "Satz zwei.")[0]["score"] == 101
    tm = client.get(f"/api/projects/{pid}/tm", params={"q": "zwei"}).json()
    assert tm["total"] == 3 and [u["target"] for u in tm["units"]] == ["Sentence two."]
    client.delete(f"/api/projects/{pid}/tm/{tm['units'][0]['id']}")
    assert client.get(f"/api/projects/{pid}").json()["tm_units"] == 2

    assert client.delete(f"/api/projects/{pid}").json() == {"ok": True}
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_confirming_fills_the_tm_and_bulk_units_never_confirm_by_themselves(store):
    """Confirming saves to the TM, one by one or in bulk (as CAT tools do). A unit saved by a bulk click is tagged
    "bulk": a 101% match from it arrives as a draft, while one confirmed on its own starts confirmed. A deleted
    project is ignored."""
    pid = store.create_project("P", "German")["id"]

    def seg(sid, source, target, **extra):
        return {"id": sid, "page": 1, "kind": "paragraph", "source": source, "target": target, "translatable": True,
                "status": "draft", "origin": "mt", **extra}

    async def main():
        sessions = InMemorySessionService()
        segs = {"p1.1": seg("p1.1", "Erster Satz im Bericht.", "First sentence in the report.", ai_check="passed"),
                "p1.2": seg("p1.2", "Zweiter Satz im Bericht.", "Second sentence in the report.", ai_check="passed"),
                "p1.3": seg("p1.3", "Dritter Satz im Bericht.", "Third sentence.", ai_check="issues")}
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:status": "ready", "doc:seg_ids": list(segs), "doc:versions": [], "doc:project_id": pid,
            "doc:filename": "a.pdf", **{st.seg_key(k): v for k, v in segs.items()}})
        assert await edits.confirm_segments(sessions, s) == ["p1.1", "p1.2"]  # only what the AI check passed
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        assert st.get_segment(s.state, "p1.1")["tm_saved"]
        assert {(u["source"], u["approval"], u["ref"]) for u in store.units(pid)} == {
            ("Erster Satz im Bericht.", "bulk", "a.pdf#p1.1"), ("Zweiter Satz im Bericht.", "bulk", "a.pdf#p1.2")}
        await edits.edit_segment(sessions, s, "p1.3", target="The third sentence.", confirm=True)
        assert store.lookup(pid, "Dritter Satz im Bericht.", "Zweiter Satz im Bericht.")[0]["score"] == 101

        # The next document: 101% matches. The one-by-one unit starts confirmed, the bulk one as a draft.
        nxt = [seg("q1.1", "Erster Satz im Bericht.", None), seg("q1.2", "Zweiter Satz im Bericht.", None),
               seg("q1.3", "Dritter Satz im Bericht.", None)]
        delta, _, stats = memory.prefill({"doc:project_id": pid}, nxt)
        status = {k.removeprefix(st.SEG): v["status"] for k, v in delta.items()}
        assert status == {"q1.1": "draft", "q1.2": "draft", "q1.3": "confirmed"} and stats["context"] == 2

        store.delete_project(pid)
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        seg3 = await edits.edit_segment(sessions, s, "p1.3", target="The 3rd sentence.", confirm=True)  # no error
        assert seg3["tm_saved"] is False

    asyncio.run(main())


def test_accept_and_confirm_saves_the_agents_change_to_the_tm(store):
    from google.adk.artifacts import InMemoryArtifactService

    from translator.document import proposals

    pid = store.create_project("P", "German")["id"]
    seg = {"id": "p1.1", "page": 1, "kind": "paragraph", "source": "Die Anlage ist abgenommen.", "target": "The plant is accepted.",
           "translatable": True, "status": "draft", "origin": "mt"}

    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:status": "ready", "doc:seg_ids": ["p1.1"], "doc:versions": [], "doc:project_id": pid, "doc:filename": "a.pdf",
            st.seg_key("p1.1"): seg, "doc:proposal": {"id": "x", "notes": [], "glossary": {}, "changes": [
                {"segment_id": "p1.1", "field": "target", "before": seg["target"], "after": "The installation has been accepted."}]}})
        await proposals.accept(sessions, artifacts, s, confirm=True)
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        new = st.get_segment(s.state, "p1.1")
        assert (new["status"], new["origin"], new["tm_saved"]) == ("confirmed", "agent", True)
        [unit] = store.units(pid)
        assert (unit["target"], unit["approval"]) == ("The installation has been accepted.", "proposal")

    asyncio.run(main())


def test_the_tm_context_is_the_same_everywhere():
    segs = [{"id": "p1.1", "source": "# Titel"}, {"id": "p1.2", "source": "2026", "translatable": False},
            {"id": "p1.3", "source": "Satz."}]
    assert memory.context_map(segs) == {"p1.1": "", "p1.3": "# Titel"}  # a copied page number isn't context

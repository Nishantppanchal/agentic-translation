"""References for terminology (references.py): the TM and the dictionary weighed against the AI's guess, the
evidence the translator and reviewer get, the chat's lookup tools, and lookups shown in the chat."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from google.adk import Runner
from google.adk.apps import App
from google.adk.artifacts import InMemoryArtifactService
from google.adk.events import Event
from google.adk.models import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types

from translator import projects, references
from translator.agents import pipeline, workers
from translator.agents.reference_tools import MAX_PER_TURN, ReferenceToolset, look_up_termbase, search_tm, tm_concordance
from translator.api.timeline import event_items, history
from translator.config import get_settings
from translator.document import state as st
from translator.integrations import dictionary


def _term(guess: str, *, dictionary_senses: list[str] = (), tm: list[tuple[str, str]] = (), ambiguous=False, options=None):
    return {"term": "Kabelpritsche", "guess": guess, "ambiguous": ambiguous, "options": options or [],
            "dictionary": [{"translation": d, "source": "IATE", "definition": f"def of {d}"} for d in dictionary_senses],
            "tm": [{"source": s, "target": t, "ref": "a.pdf#p1.1"} for s, t in tm]}


def test_the_translation_memory_wins():
    t = _term("cable bridge", dictionary_senses=["cable tray"], tm=[("Die Kabelpritsche ist geerdet.", "The cable tray is earthed.")])
    assert references.reconcile(t, True) == "tm" and t["guess"] == "cable tray"


def test_a_plural_in_the_tm_still_backs_the_term():
    t = _term("defect", tm=[("发现的缺陷", "Defects found")])
    assert references.reconcile(t, True) == "tm" and t["guess"] == "defect"


def test_the_dictionary_agreeing_backs_the_guess():
    t = _term("the cable tray", dictionary_senses=["cable trays"])
    assert references.reconcile(t, True) == "dictionary" and t["guess"] == "the cable tray"


def test_the_dictionary_disagreeing_becomes_a_question():
    t = _term("cable bridge", dictionary_senses=["cable tray"])
    assert references.reconcile(t, True) == "asked"
    assert [o["target"] for o in t["options"]] == ["cable bridge", "cable tray"] and t["recommended"] == 1
    assert t["ambiguous"] and t["reason"].startswith("Dictionary disagrees: IATE gives cable tray")


def test_without_room_to_ask_one_dictionary_sense_wins_and_several_leave_the_guess():
    one = _term("cable bridge", dictionary_senses=["cable tray"])
    assert references.reconcile(one, False) == "dictionary" and one["guess"] == "cable tray" and "cable bridge" in one["note"]
    several = _term("cable bridge", dictionary_senses=["cable tray", "cable ladder"])
    assert references.reconcile(several, False) == "conflict" and several["guess"] == "cable bridge"


def test_a_question_recommends_what_the_tm_used_and_no_evidence_is_the_ais():
    t = _term("cable tray", ambiguous=True, options=[{"target": "cable tray"}, {"target": "cable ladder"}],
              tm=[("Kabelpritsche montieren", "Install the cable ladder")])
    assert references.reconcile(t, True) == "asked" and t["recommended"] == 1
    assert references.reconcile(_term("cable tray"), True) == "ai"


def test_evidence_for_the_translator_and_badges_in_the_termbase():
    state = {"doc:glossary": {"Abnahme": {"target": "acceptance"}}, "doc:termbase": {"Kabelpritsche": "cable tray"},
             "doc:key_terms": [
                 {"term": "Kabelpritsche", "target": "cable tray", "decision": "dictionary",
                  "dictionary": [{"translation": "cable tray", "source": "IATE", "definition": "a tray for cables"}], "tm": []},
                 {"term": "Abnahme", "target": "acceptance", "decision": "ai", "dictionary": [{"translation": "approval"}], "tm": []}]}
    batch = [{"id": "p1.1", "source": "Die Kabelpritsche und die Abnahme."}]
    text = references.evidence_text(state, batch)
    assert text == "- Kabelpritsche: dictionary: cable tray (a tray for cables) [IATE]"  # the glossary term isn't repeated
    assert references.evidence_text(state, [{"id": "p2.1", "source": "Ergebnis"}]) == "(none)"
    assert st.termbase_text(state) == "- Kabelpritsche → cable tray  (the dictionary agrees: IATE)"


def test_the_analysis_weighs_the_tm_and_the_dictionary(monkeypatch):
    """Two clear terms: the TM settles one (and its wording wins), the dictionary disagrees with the other, which
    becomes a question. Both lookups show in the chat."""
    store = projects.get_store()
    pid = store.create_project("P", "German")["id"]
    store.add_unit(pid, "Die Erdung fehlt.", "The earthing is missing.")
    monkeypatch.setattr(get_settings(), "analysis_enabled", True)
    monkeypatch.setattr(get_settings(), "dictionary_url", "http://dictionary.invalid/lookup")

    async def lookup(terms, lang):
        return {"Kabelpritsche": [{"translation": "cable tray", "source": "IATE", "definition": "metal tray"}],
                "Erdung": [{"translation": "grounding", "source": "IATE"}]}

    monkeypatch.setattr(dictionary, "lookup", lookup)
    monkeypatch.setattr(workers.analyst, "before_model_callback", lambda *_: LlmResponse(content=types.Content(role="model", parts=[types.Part(text=(
        "<source_lang>German</source_lang>\n<brief>An inspection note.</brief>\n"
        '<term source="Kabelpritsche" guess="cable bridge" meaning="a carrier for cables" ambiguous="no" segs="p1.1">x</term>\n'
        '<term source="Erdung" guess="earth connection" alt="earthing" meaning="connection to earth" ambiguous="no" segs="p1.1">y</term>'))])))

    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        runner = Runner(app=App(name="t", root_agent=pipeline.ingest_workflow), session_service=sessions, artifact_service=artifacts)
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:filename": "n.md", "doc:source_artifact": "source.md", "doc:source_lang": "German", "doc:target_lang": "English",
            "doc:questions": [], "doc:versions": [], "doc:project_id": pid})
        await artifacts.save_artifact(app_name="t", user_id="u", session_id=s.id, filename="source.md",
                                      artifact=types.Part.from_bytes(data="Die Kabelpritsche hat keine Erdung.".encode(), mime_type="text/markdown"))
        async for _ in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            pass
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        decisions = {k["term"]: (k["decision"], k["target"]) for k in s.state["doc:key_terms"]}
        assert decisions == {"Kabelpritsche": ("asked", "cable bridge"), "Erdung": ("tm", "earthing")}
        [q] = st.open_questions(s.state)
        assert q["term"] == "Kabelpritsche" and q["reason"].startswith("Dictionary disagrees")
        assert s.state["doc:termbase"]["Erdung"] == "earthing"
        lookups = [i for i in history(s.events) if i["kind"] == "lookup"]
        assert [(i["source"], i["hits"]) for i in lookups] == [("tm", 1), ("dictionary", 2)]
        assert lookups[1]["results"][0]["outcome"] in ("asked you", "as in the TM")

    asyncio.run(main())


# --------------------------------------------------------------------------- #
# The chat's lookup tools
# --------------------------------------------------------------------------- #


def test_the_tools_a_document_gets(monkeypatch):
    toolset = ReferenceToolset()
    names = lambda state: sorted(t.name for t in asyncio.run(toolset.get_tools(SimpleNamespace(state=state))))  # noqa: E731
    assert names({}) == ["look_up_termbase"]
    pid = projects.get_store().create_project("P", "German")["id"]
    assert names({"doc:project_id": pid}) == ["look_up_termbase", "search_tm", "tm_concordance"]
    monkeypatch.setattr(get_settings(), "dictionary_url", "http://dictionary.invalid/lookup")
    assert "look_up_dictionary" in names({"doc:project_id": pid})
    assert "look_up_dictionary" not in names({"doc:project_id": pid, "doc:dictionary": False})


def test_tm_and_termbase_lookups():
    store = projects.get_store()
    pid = store.create_project("P", "German")["id"]
    store.add_unit(pid, "Die Kabelpritsche ist geerdet.", "The cable tray is earthed.", ref="a.pdf#p1.2")
    store.upsert_term(pid, "Kabelpritsche", "cable tray", forbidden=["cable bridge"])
    ctx = SimpleNamespace(state={"doc:project_id": pid, "doc:glossary": {"Erdung": {"target": "earthing"}},
                                 "doc:termbase": {"Abnahme": "acceptance"}})
    found = search_tm("Die Kabelpritsche ist nicht geerdet.", ctx)
    assert found["status"] == "found" and found["results"][0]["target"] == "The cable tray is earthed."
    assert 75 <= found["results"][0]["score"] < 100 and found["results"][0]["ref"] == "a.pdf#p1.2"
    assert tm_concordance("cable tray", ctx)["hits"] == 1
    term = look_up_termbase("Kabelpritsche", ctx)["results"][0]
    assert (term["target"], term["badge"], term["forbidden"]) == ("cable tray", "project · approved", ["cable bridge"])
    assert look_up_termbase("Erdung", ctx)["results"][0]["badge"] == "your answer"
    assert look_up_termbase("Abnahme", ctx)["results"][0]["badge"].startswith("chosen by the translator")
    assert search_tm("x", SimpleNamespace(state={}))["status"] == "unavailable"


def test_lookups_per_turn_are_capped():
    ctx = SimpleNamespace(state={})
    statuses = [look_up_termbase("Kabelpritsche", ctx)["status"] for _ in range(MAX_PER_TURN + 1)]
    assert statuses[-1] == "limit" and "limit" not in statuses[:-1]


def test_a_lookup_shows_in_the_chat_while_it_runs_and_when_it_answers():
    call = Event(author="editor", content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
        id="fc1", name="search_tm", args={"sentence": "Die Kabelpritsche"}))]))
    answer = Event(author="editor", content=types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id="fc1", name="search_tm", response={"source": "tm", "query": "Die Kabelpritsche", "status": "found", "hits": 1,
                                              "results": [{"target": "The cable tray", "score": 87}]}))]))
    [pending] = event_items(call)
    assert (pending["kind"], pending["status"], pending["source"]) == ("lookup", "pending", "tm")
    [done] = [i for i in event_items(answer) if i["kind"] == "lookup"]
    assert done["id"] == "fc1" and done["status"] == "done" and done["results"][0]["entries"][0]["score"] == 87
    [item] = history([call, answer])
    assert item["status"] == "done"  # the answer replaces the call, in its place


@pytest.fixture(autouse=True)
def _no_dictionary_cache():
    dictionary._cache.clear()
    yield
    dictionary._cache.clear()

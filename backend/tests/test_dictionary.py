"""The dictionary service (DICTIONARY_URL): the contract, against the dummy server in dictionary-server/."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import socket
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from translator.config import get_settings
from translator.integrations import dictionary

SERVER = Path(__file__).resolve().parents[2] / "dictionary-server" / "server.py"
_spec = importlib.util.spec_from_file_location("dummy_dictionary", SERVER)
dummy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dummy)


@pytest.fixture
def dictionary_server(monkeypatch):
    calls: list[dict] = []

    class Counting(dummy.Handler):
        def do_POST(self):  # noqa: N802
            calls.append({"auth": self.headers.get("Authorization"), "x": self.headers.get("X-Client")})
            super().do_POST()

    Counting.key = "dict-key"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Counting)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    s = get_settings()
    monkeypatch.setattr(s, "dictionary_url", f"http://127.0.0.1:{server.server_address[1]}/lookup")
    monkeypatch.setattr(s, "dictionary_api_key", "dict-key")
    monkeypatch.setattr(s, "dictionary_headers", {"X-Client": "translator"})
    dictionary._cache.clear()
    yield calls
    server.shutdown()
    server.server_close()
    dictionary._cache.clear()


def test_terms_are_looked_up_in_one_call_and_cached(dictionary_server):
    found = asyncio.run(dictionary.lookup(["réceptionnée avec réserves", "ASI", "inconnu"], "French"))
    assert set(found) == {"réceptionnée avec réserves", "ASI"}  # an unknown term is left out
    [entry] = found["réceptionnée avec réserves"]  # an inflected form finds its entry
    assert entry["translation"] == "acceptance with reservations" and entry["domain"] == "construction law"
    assert entry["source"] == "Dummy dictionary (demo data)" and entry["term"] == "réception avec réserves"
    assert dictionary_server == [{"auth": "Bearer dict-key", "x": "translator"}]
    asyncio.run(dictionary.lookup(["ASI"], "fr"))  # cached: no second call
    assert len(dictionary_server) == 1


def test_a_failing_dictionary_never_blocks(dictionary_server, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "dictionary_api_key", "wrong")
    with caplog.at_level(logging.WARNING, logger="translator.integrations.dictionary"):
        assert asyncio.run(dictionary.lookup(["ASI"], "fr")) == {}
    assert "HTTP 401" in caplog.text and "missing or wrong API key" in caplog.text and "wrong" not in caplog.text.split("HTTP 401")[0]
    with socket.socket() as sock:  # nothing listening
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setattr(get_settings(), "dictionary_url", f"http://127.0.0.1:{port}/lookup")
    assert asyncio.run(dictionary.lookup(["SAI"], "es")) == {}


def test_without_a_dictionary_nothing_is_called(monkeypatch):
    monkeypatch.setattr(get_settings(), "dictionary_url", "")
    assert not dictionary.enabled() and asyncio.run(dictionary.lookup(["ASI"], "fr")) == {}


def test_a_dictionary_translation_the_analysis_missed_becomes_an_option():
    from translator.references import add_dictionary_options as _add_dictionary_options

    term = {"term": "réception avec réserves", "guess": "acceptance subject to reservations",
            "options": [{"target": "acceptance subject to reservations", "note": ""}],
            "dictionary": [{"translation": "acceptance with reservations", "definition": "Acceptance with a snag list.",
                            "source": "IATE"}, {"translation": "Acceptance subject to reservations", "source": "X"}]}
    _add_dictionary_options(term)
    assert [o["target"] for o in term["options"]] == ["acceptance subject to reservations", "acceptance with reservations"]
    assert term["options"][1]["note"] == "IATE: Acceptance with a snag list."


def test_the_editor_can_look_terms_up(dictionary_server):
    from translator.agents.reference_tools import look_up_dictionary

    class Ctx:
        state = {"doc:source_lang": "Chinese (Simplified)"}

    result = asyncio.run(look_up_dictionary("三措一案", Ctx()))
    assert result["status"] == "found" and result["results"][0]["target"] == "three measures and one plan"
    assert asyncio.run(look_up_dictionary("不存在", Ctx()))["status"] == "not found"
    Ctx.state = {**Ctx.state, "doc:dictionary": False}  # turned off for this document
    assert asyncio.run(look_up_dictionary("三措一案", Ctx()))["status"] == "off"
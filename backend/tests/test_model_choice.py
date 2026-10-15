"""Choosing models and reasoning levels: models.yaml `thinking`, the standard `reasoning_effort` on the wire,
the app's Settings and a document's own choice (models/routing.py), and the settings API."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.adk.sessions import InMemorySessionService

from translator import app_settings
from translator.agents import workers
from translator.api import services
from translator.api.routes import documents as document_routes
from translator.api.routes import settings as settings_routes
from translator.api.usage import summarize
from translator.models import llm, routing
from translator.models.config import ChoiceError, ConfigError

from .fake_vllm import FakeVllm as _FakeVllm
from .fake_vllm import call as _call
from .fake_vllm import request as _request


def _two(url: str = "http://127.0.0.1:9/v1") -> dict:
    return {"defaults": {"retries": 0, "timeout": 10, "temperature": 0.2},
            "models": [{"id": "fast", "model_name": "vendor/fast-vl", "url": url, "vision": True},
                       {"id": "deep", "model_name": "vendor/deep-thinker", "url": url, "thinking": True},
                       {"id": "deep-vl", "model_name": "vendor/deep-vl", "url": url, "vision": True, "thinking": True}]}


def test_reasoning_levels_go_out_as_reasoning_effort(use_models, fake_vllm):
    use_models(_two(fake_vllm), {"default": "fast", "steps": {"translate": {"model": "deep", "effort": "high"},
                                                               "review": {"model": "deep", "effort": "instant"}}})
    _call(llm.build_model("translate"), _request())
    _call(llm.build_model("review"), _request())
    _call(llm.build_model("analyse"), _request())
    high, instant, plain = (r["body"] for r in _FakeVllm.requests)
    assert high["reasoning_effort"] == "high" and "temperature" not in high  # thinking on: no default temperature
    assert instant["reasoning_effort"] == "none" and instant["temperature"] == 0.2  # Instant: thinking off (vLLM: enable_thinking=false)
    assert "reasoning_effort" not in plain and plain["model"] == "vendor/fast-vl"


def test_a_server_that_refuses_reasoning_effort_gets_the_call_again_without_it(use_models, fake_vllm):
    use_models(_two(fake_vllm), {"default": "fast", "steps": {"translate": {"model": "deep", "effort": "low"}}})
    _FakeVllm.refuse_effort = True
    model = llm.build_model("translate")
    (reply,) = _call(model, _request())
    first, retry = (r["body"] for r in _FakeVllm.requests)
    assert first["reasoning_effort"] == "low" and "reasoning_effort" not in retry
    assert reply.custom_metadata == {"model_id": "deep", "effort": None}  # what was actually sent
    _call(model, _request())
    assert "reasoning_effort" not in _FakeVllm.requests[-1]["body"]  # not sent again


def test_litellm_passes_reasoning_effort_to_our_servers():
    from litellm.llms.hosted_vllm.chat.transformation import HostedVLLMChatConfig

    assert "reasoning_effort" in HostedVLLMChatConfig().get_supported_openai_params("vendor/deep-thinker")


def test_a_level_needs_a_thinking_model(use_models):
    with pytest.raises(ConfigError, match="thinking: true"):
        use_models(_two(), {"default": "fast", "steps": {"translate": {"model": "fast", "effort": "low"}}})
    cfg = use_models(_two(), {"default": "fast"})
    with pytest.raises(ChoiceError, match="doesn't think"):
        cfg.check_choice("translate", "fast", "high")
    with pytest.raises(ChoiceError, match="doesn't read images"):
        cfg.check_choice("ocr", "deep", None)
    with pytest.raises(ChoiceError, match="not a model"):
        cfg.check_choice("translate", "gpt-9", None)
    assert cfg.check_choice("ocr", "deep-vl", "medium").id == "deep-vl"


def test_default_is_a_real_level(use_models, fake_vllm):
    """A thinking model always gets a level: pipeline.yaml's for the step (on its own model), else the model's
    `effort` in models.yaml, else medium — and the settings view says which one "Default" stands for."""
    models = _two(fake_vllm)
    models["models"][2]["effort"] = "low"  # deep-vl
    cfg = use_models(models, {"default": "fast", "steps": {"translate": {"model": "deep", "effort": "high"}, "review": "deep",
                                                           "ocr": "deep-vl"}})
    assert cfg.default_effort("translate", "deep") == ("high", "pipeline.yaml")
    assert cfg.default_effort("analyse", "deep") == ("medium", "built-in")  # not that step's pipeline.yaml model
    assert cfg.default_effort("ocr", "deep-vl") == ("low", "models.yaml")
    assert cfg.default_effort("ocr", "fast") == (None, None)  # doesn't think
    assert (cfg.step("review").effort, cfg.step("ocr").effort, cfg.step("analyse").effort) == ("medium", "low", None)
    _call(llm.build_model("review"), _request())
    assert _FakeVllm.requests[-1]["body"]["reasoning_effort"] == "medium"  # "Default" is sent, not left to the server
    state = {routing.DOC_MODELS: {"analyse": {"model": "deep-vl", "effort": None}}}
    assert routing.resolve("analyse", state).effort == "low"
    with pytest.raises(ConfigError, match="thinking: true"):
        use_models({**_two(), "models": [{**_two()["models"][0], "effort": "low"}]}, {"default": "fast"})


def test_models_are_described_for_people():
    from translator.models.catalog import describe, label, vendor
    from translator.models.config import ModelSpec

    def spec(name, url="http://127.0.0.1:9/v1", **kw):
        return ModelSpec(id="x", model_name=name, url=url, **kw)

    assert label(spec("anthropic/claude-haiku-5.5")) == "Claude Haiku 5.5"
    assert label(spec("Qwen/Qwen3-VL-8B-Instruct")) == "Qwen3 VL 8B Instruct"
    assert label(spec("openai/gpt-5-mini", label="GPT mini")) == "GPT mini"
    assert [vendor(spec(n)) for n in ("anthropic/claude-haiku-5.5", "qwen/qwen3.8-flash", "Qwen/Qwen3-VL-8B", "gpt-oss-20b",
                                      "meta-llama/llama-4", "my-model")] == ["anthropic", "qwen", "qwen", "openai", "meta", None]
    assert vendor(spec("my-model", vendor="Mistral")) == "mistral"
    d = describe(spec("anthropic/claude-haiku-5.5", url="https://user:pw@openrouter.ai/api/v1", thinking=True))
    assert (d["server"], d["where"], d["default_effort"]) == ("openrouter", "OpenRouter", "medium")
    own = describe(spec("q", url="http://gpu-7.internal:8100/v1"))
    assert (own["server"], own["where"]) == ("custom", "own server") and "gpu-7" not in json.dumps(own) and "pw" not in json.dumps(d)


def test_the_pipeline_diagram_has_every_step():
    from translator.models.catalog import flow
    from translator.models.config import STEPS

    f = flow()
    ids = {n["id"] for n in f["nodes"]}
    assert sorted(n["step"] for n in f["nodes"] if n.get("step")) == sorted(STEPS)
    assert all(a in ids and b in ids for a, b, _label in f["edges"])
    linked = {x for a, b, _label in f["edges"] for x in (a, b)}
    assert {n["step"] for n in f["nodes"] if n.get("step") and n["id"] not in linked} == {"editor", "rewrite", "lqa", "suggest", "complete", "notes"}
    assert len({(n["row"], n["col"]) for n in f["nodes"]}) == len(f["nodes"])  # no two nodes on one spot


def test_pipeline_then_settings_then_the_document(use_models):
    use_models(_two(), {"default": "fast"})
    assert routing.resolve("translate").id == "fast"
    app_settings.save(app_settings.AppSettings(models={"translate": {"model": "deep", "effort": "medium"}}))
    assert (routing.resolve("translate").id, routing.resolve("translate").effort) == ("deep", "medium")
    state = {routing.DOC_MODELS: {"translate": {"model": "deep", "effort": "instant"}, "ocr": {"model": "deep"}}}
    assert routing.resolve("translate", state).effort == "instant"
    assert routing.resolve("ocr", state).id == "fast"  # a choice that can't read pages falls back (with a warning)
    snap = routing.snapshot({"review": {"model": "deep", "effort": "low"}})
    assert snap["translate"] == {"model": "deep", "effort": "medium"} and snap["review"] == {"model": "deep", "effort": "low"}
    assert snap["ocr"] == {"model": "fast", "effort": None}


def test_a_documents_choice_reaches_the_server(use_models, fake_vllm):
    """The translator agent on one document asks for its model per call and gets the document's choice: that
    model's name goes out, and the response says which model answered (for usage)."""
    use_models(_two(fake_vllm), {"default": "fast"})
    ctx = SimpleNamespace(state={routing.DOC_MODELS: {"translate": {"model": "deep", "effort": "low"}}})
    model = asyncio.run(workers.translator.canonical_model_async(ctx))
    (reply,) = _call(model, _request())
    assert _FakeVllm.requests[-1]["body"]["model"] == "vendor/deep-thinker"
    assert reply.custom_metadata == {"model_id": "deep", "effort": "low"}
    other = asyncio.run(workers.translator.canonical_model_async(SimpleNamespace(state={})))
    assert other.model.endswith("vendor/fast-vl")


def test_usage_by_model_and_level():
    def ev(author, model_id, effort, prompt, completion, thoughts=0):
        usage = SimpleNamespace(prompt_token_count=prompt, candidates_token_count=completion, thoughts_token_count=thoughts)
        return SimpleNamespace(author=author, usage_metadata=usage, partial=False, model_version="srv/name",
                               custom_metadata={"model_id": model_id, "effort": effort} if model_id else None)

    out = summarize([ev("translator", "deep", "high", 100, 50, 30), ev("translator", "deep", "high", 10, 5, 2),
                     ev("translator", "fast", None, 10, 5), ev("reviewer", None, None, 1, 1)])
    rows = {(r["step"], r["model"], r["effort"]): r for r in out["rows"]}
    assert rows[("Translation", "deep", "high")]["reasoning_tokens"] == 32 and rows[("Translation", "deep", "high")]["calls"] == 2
    assert ("Review", "srv/name", None) in rows  # an event from before: the server's model name


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


@pytest.fixture
def api(use_models, monkeypatch):
    use_models({**_two(), "models": [{**m, "api_key": "secret-key", "headers": {"X-Token": "secret-header"}} for m in _two()["models"]]},
               {"default": "fast"})
    sessions = InMemorySessionService()
    for module in (services, settings_routes, document_routes):
        monkeypatch.setattr(module, "session_service", sessions, raising=False)
    app = FastAPI()
    app.include_router(settings_routes.router)
    return TestClient(app), sessions


def test_the_models_list_holds_no_secrets(api):
    client, _ = api
    body = client.get("/api/models").json()
    assert [(m["id"], m["vision"], m["thinking"]) for m in body] == [("fast", True, False), ("deep", False, True), ("deep-vl", True, True)]
    text = json.dumps(body)
    assert "secret" not in text and "127.0.0.1" not in text
    assert {m["id"]: m["where"] for m in body} == {"fast": "this computer", "deep": "this computer", "deep-vl": "this computer"}


def test_settings_are_validated_saved_and_reset(api):
    client, _ = api
    view = client.get("/api/settings").json()
    assert view["models"]["translate"] == {"model": "fast", "effort": None} and view["dictionary"]["available"] is False
    assert [g["id"] for g in view["groups"]] == ["reading", "translating", "reviewing", "chat", "assist"]
    assert next(g for g in view["groups"] if g["id"] == "assist")["steps"] == ["suggest", "complete", "notes"]
    assert view["defaults"]["translate"] == {"deep": {"effort": "medium", "from": "built-in"},
                                             "deep-vl": {"effort": "medium", "from": "built-in"}}
    assert "fast" not in view["defaults"]["translate"] and view["flow"]["rows"]
    bad = client.put("/api/settings", json={"models": {"ocr": {"model": "deep"}, "translate": {"model": "fast", "effort": "high"}}})
    assert bad.status_code == 422 and {e["loc"][-1] for e in bad.json()["detail"]} == {"ocr", "translate"}
    assert client.put("/api/settings", json={"dictionary": True}).status_code == 422  # no dictionary service set up
    view = client.put("/api/settings", json={"models": {"translate": {"model": "deep", "effort": "high"}}}).json()
    assert view["models"]["translate"] == {"model": "deep", "effort": "high"} and view["overridden"] == ["translate"]
    view = client.put("/api/settings", json={"models": {"translate": None}}).json()  # back to pipeline.yaml
    assert view["models"]["translate"]["model"] == "fast" and view["overridden"] == []


def test_a_documents_settings_change_from_its_next_run(api, monkeypatch):
    client, sessions = api
    s = asyncio.run(sessions.create_session(app_name=services.APP_NAME, user_id=services.USER, state={
        "doc:status": "ready", routing.DOC_MODELS: routing.snapshot()}))
    r = client.patch(f"/api/sessions/{s.id}/settings", json={"models": {"review": {"model": "deep", "effort": "low"}}})
    assert r.status_code == 200 and r.json()["models"]["review"] == {"model": "deep", "effort": "low"}
    s = asyncio.run(sessions.get_session(app_name=services.APP_NAME, user_id=services.USER, session_id=s.id))
    assert s.state[routing.DOC_MODELS]["review"]["model"] == "deep"
    assert "Review → deep (low)" in s.events[-1].content.parts[0].text  # the change shows in the chat history
    monkeypatch.setattr(services.runs, "is_running", lambda sid: True)
    assert client.patch(f"/api/sessions/{s.id}/settings", json={"models": {"review": None}}).status_code == 409


def test_an_upload_keeps_its_own_choice(api, monkeypatch):
    client, sessions = api
    from google.adk.artifacts import InMemoryArtifactService

    monkeypatch.setattr(document_routes, "artifact_service", InMemoryArtifactService(), raising=False)
    monkeypatch.setattr(document_routes, "start_run", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(document_routes.router)
    up = TestClient(app)
    files = {"file": ("note.txt", "Die Anlage ist abgenommen.".encode(), "text/plain")}
    bad = up.post("/api/sessions", files=files, data={"source_lang": "German", "models": json.dumps({"ocr": {"model": "deep"}})})
    assert bad.status_code == 422
    r = up.post("/api/sessions", files=files, data={"source_lang": "German",
                                                    "models": json.dumps({"translate": {"model": "deep", "effort": "high"}})})
    assert r.status_code == 200, r.text
    s = asyncio.run(sessions.get_session(app_name=services.APP_NAME, user_id=services.USER, session_id=r.json()["id"]))
    assert s.state[routing.DOC_MODELS]["translate"] == {"model": "deep", "effort": "high"}
    assert s.state[routing.DOC_MODELS]["review"] == {"model": "fast", "effort": None}  # the rest: the defaults then
    assert s.state["doc:dictionary"] is False  # no dictionary service is set up in tests

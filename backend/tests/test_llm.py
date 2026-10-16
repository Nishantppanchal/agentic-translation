"""Models: config/models.yaml lists them (any OpenAI-compatible server), config/pipeline.yaml says which one does
each step. Each call goes to its model's server with its key, headers and extra body; calls retry and time out."""

import asyncio
import logging
import socket
from pathlib import Path

import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from translator.config import CONFIG_DIR
from translator.models import config as model_config
from translator.models import llm, structured
from translator.models.config import ConfigError, load

from .fake_vllm import FakeVllm as _FakeVllm
from .fake_vllm import call as _call
from .fake_vllm import request as _request


def _write(tmp_path: Path, models: str, pipeline: str) -> tuple[Path, Path]:
    (tmp_path / "models.yaml").write_text(models)
    (tmp_path / "pipeline.yaml").write_text(pipeline)
    return tmp_path / "models.yaml", tmp_path / "pipeline.yaml"


def test_each_step_calls_the_model_pipeline_yaml_gives_it(use_models):
    use_models(
        {"defaults": {"headers": {"X-Gateway-Token": "t-default", "X-Team": "mt"}, "timeout": 60, "retries": 3},
         "models": [
             {"id": "vl", "model_name": "Qwen/Qwen3-VL-8B-Instruct", "url": "http://gpu-1:8100/v1", "api_key": "k-1",
              "headers": {"X-Team": "ocr"}, "extra_body": {"top_k": 20}, "vision": True},
             {"id": "text", "model_name": "anthropic/claude-haiku-5.5", "url": "https://openrouter.ai/api/v1",
              "api_key": "or-key", "timeout": 30, "temperature": 0.4, "vision": True},
         ]},
        {"default": "text", "steps": {"ocr": "vl", "ocr_check": "vl",
                                      "review": {"model": "vl", "extra_body": {"thinking_token_budget": 2000},
                                                 "temperature": 0.0}}},
    )
    ocr = llm.build_model("ocr")
    assert ocr.model == "hosted_vllm/Qwen/Qwen3-VL-8B-Instruct"  # the served name, through LiteLLM's OpenAI-compatible provider
    args = ocr._additional_args
    assert args["api_base"] == "http://gpu-1:8100/v1" and args["api_key"] == "k-1"
    assert args["extra_headers"] == {"X-Gateway-Token": "t-default", "X-Team": "ocr"}  # defaults + the model's own (it wins)
    assert args["extra_body"] == {"top_k": 20} and args["timeout"] == 60 and args["num_retries"] == 3

    review = llm.build_model("review")  # the step's extra body is added to the model's
    assert review._additional_args["extra_body"] == {"top_k": 20, "thinking_token_budget": 2000}
    assert model_config.step_model("review").temperature == 0.0

    translate = llm.build_model("translate")  # not listed: the default
    assert translate.model == "hosted_vllm/anthropic/claude-haiku-5.5"
    assert translate._additional_args["api_base"] == "https://openrouter.ai/api/v1"
    assert translate._additional_args["timeout"] == 30 and "extra_body" not in translate._additional_args
    assert model_config.step_model("translate").temperature == 0.4
    assert llm.model_name("editor") == "anthropic/claude-haiku-5.5"
    assert "or-key" not in repr(model_config.step_model("translate"))  # keys stay out of logs


def test_the_yaml_files_take_secrets_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GATEWAY_KEY", "s3cret")
    models, pipeline = _write(tmp_path, """
defaults:
  headers: {X-Gateway-Token: "${TEST_GATEWAY_KEY}"}
  forward_headers: [X-Request-Id]
models:
  - id: local
    model_name: Qwen/Qwen3-VL-8B-Instruct
    url: http://localhost:8100/v1
    api_key: ${TEST_UNSET_KEY:-}
    vision: true
""", "default: local\n")
    cfg = load(models, pipeline)
    step = cfg.step("translate")
    assert step.headers == {"X-Gateway-Token": "s3cret"} and step.api_key is None  # ${NAME:-}: may be unset
    assert cfg.forward_headers == ("X-Request-Id",)

    models.write_text(models.read_text().replace("${TEST_UNSET_KEY:-}", "${TEST_UNSET_KEY}"))
    with pytest.raises(ConfigError, match="TEST_UNSET_KEY is not set"):
        load(models, pipeline)


@pytest.mark.parametrize(("models", "pipeline", "problem"), [
    ("models: [{id: a, model_name: m, url: u, vision: true}]", "steps: {ocr: a}", "no model for the step 'ocr_second'"),
    ("models: [{id: a, model_name: m, url: u, vision: true}]", "default: b", "uses 'b', which is not an id in models.yaml (a)"),
    ("models: [{id: a, model_name: m, url: u, vision: true}, {id: a, model_name: n, url: u}]", "default: a", "two models have the id 'a'"),
    ("models: [{id: a, model_name: m, url: u, vision: true, api_kye: x}]", "default: a", "models.0.api_kye: Extra inputs"),
    ("models: [{id: a, model_name: m, url: u, vision: true}]", "default: a\nsteps: {translation: a}", "steps.translation"),
    ("models: [{id: a, model_name: m, url: u, vision: true}, {id: t, model_name: n, url: u}]", "default: a\nsteps: {editor: t}",
     "step 'editor' looks at page images, so it needs a vision model, but 't' is not marked `vision: true`"),
])
def test_a_wrong_config_says_which_file_and_what(tmp_path, models, pipeline, problem):
    with pytest.raises(ConfigError, match=problem.replace("(", r"\(").replace(")", r"\)")):
        load(*_write(tmp_path, models, pipeline))


def test_a_missing_models_yaml_points_to_the_example(tmp_path):
    (tmp_path / "models.example.yaml").write_text("models: []")
    with pytest.raises(ConfigError, match="copy models.example.yaml to models.yaml"):
        load(tmp_path / "models.yaml", tmp_path / "pipeline.yaml")


def test_the_shipped_example_and_pipeline_are_valid(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy")
    cfg = load(CONFIG_DIR / "models.example.yaml", CONFIG_DIR / "pipeline.yaml")
    assert set(cfg.steps) == set(model_config.STEPS)
    assert cfg.step("ocr").model_name and cfg.step("translate").url.startswith("http")


@pytest.mark.structured
def test_structured_output_is_a_model_setting(use_models):
    use_models({"models": [{"id": "a", "model_name": "m", "url": "http://x/v1", "vision": True},
                           {"id": "b", "model_name": "n", "url": "http://x/v1", "structured_output": False}]},
               {"default": "a", "steps": {"review": "b"}})
    assert structured.enabled("translate") and not structured.enabled("review")


def _endpoint(url: str, **model) -> dict:
    return {"defaults": {"retries": 0, "timeout": 10},
            "models": [{"id": "m", "model_name": "Qwen/Qwen3-32B", "url": url, "vision": True, **model}]}


def test_the_request_reaches_the_server_as_configured(use_models, fake_vllm):
    """What actually goes over the wire (a local stand-in server, not a real model)."""
    use_models(_endpoint(fake_vllm, api_key="k-123", headers={"X-Gateway-Token": "t-456", "CF-Access-Client-Id": "id.access"},
                         extra_body={"chat_template_kwargs": {"enable_thinking": False}, "top_k": 20}))
    request = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="Translate: Abnahme")])])
    request.config.response_schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    replies = _call(llm.build_model("translate"), request)

    assert replies[-1].content.parts[0].text == '{"ok": true}'
    (sent,) = _FakeVllm.requests
    headers = {k.lower(): v for k, v in sent["headers"].items()}
    assert sent["path"] == "/v1/chat/completions"
    assert sent["body"]["model"] == "Qwen/Qwen3-32B"  # the served name, without LiteLLM's provider prefix
    assert headers["authorization"] == "Bearer k-123"
    assert headers["x-gateway-token"] == "t-456" and headers["cf-access-client-id"] == "id.access"
    assert sent["body"]["chat_template_kwargs"] == {"enable_thinking": False} and sent["body"]["top_k"] == 20
    assert sent["body"]["response_format"]["type"] == "json_schema"
    assert sent["body"]["response_format"]["json_schema"]["schema"]["properties"] == {"ok": {"type": "boolean"}}


def test_a_runs_headers_reach_every_model_request_it_makes(use_models, fake_vllm):
    use_models(_endpoint(fake_vllm, headers={"X-Gateway-Token": "t"}))
    model = llm.build_model("translate")
    with llm.request_headers({"X-Request-Id": "req-1"}), llm.request_headers({"X-Tenant-Id": "acme"}):
        _call(model, _request())
    _call(model, _request())  # outside the block: the model's own headers only
    inside, outside = ({k.lower(): v for k, v in r["headers"].items()} for r in _FakeVllm.requests)
    assert inside["x-request-id"] == "req-1" and inside["x-tenant-id"] == "acme" and inside["x-gateway-token"] == "t"
    assert "x-request-id" not in outside and outside["x-gateway-token"] == "t"


def test_the_api_forwards_the_configured_request_headers_to_the_runs_it_starts(use_models):
    from translator.api.main import ForwardHeaders

    use_models({"defaults": {"forward_headers": ["X-Request-Id", "X-Tenant-Id"]},
                "models": [{"id": "m", "model_name": "n", "url": "http://x/v1", "vision": True}]})
    seen = {}

    async def endpoint(scope, receive, send):  # an endpoint that starts a run in the background
        async def run():
            seen["run"] = llm._run_headers.get()

        await asyncio.create_task(run())

    scope = {"type": "http", "headers": [(b"x-request-id", b"r-9"), (b"authorization", b"Bearer user-token")]}
    asyncio.run(ForwardHeaders(endpoint)(scope, None, None))
    assert seen["run"] == {"X-Request-Id": "r-9"}  # only the named ones: never the caller's credentials


def test_thinking_written_into_the_answer_is_split_off(use_models, fake_vllm):
    """A reasoning model on a server without a reasoning parser: its thinking ends with `</think>` inside the
    answer (the opening tag is in the chat template). It becomes a thought part, as with a parser."""
    use_models(_endpoint(fake_vllm))
    _FakeVllm.content = "The user wants me to transcribe page 2. Let me be careful.\n</think>\n\n[[HEADER]] Kopf\n\nText."
    (reply,) = _call(llm.build_model("ocr"), _request())
    thought, answer = reply.content.parts
    assert thought.thought and thought.text == "The user wants me to transcribe page 2. Let me be careful."
    assert not answer.thought and answer.text == "[[HEADER]] Kopf\n\nText."
    _FakeVllm.content = "<think>short</think>Text."  # with the opening tag too
    assert [p.text for p in _call(llm.build_model("ocr"), _request())[0].content.parts] == ["short", "Text."]
    _FakeVllm.content = "Plain answer."  # no thinking: untouched
    assert [p.text for p in _call(llm.build_model("ocr"), _request())[0].content.parts] == ["Plain answer."]


def test_a_server_without_a_reasoning_parser_gets_the_review_without_a_budget(use_models, fake_vllm):
    use_models(_endpoint(fake_vllm, extra_body={"top_k": 20}),
               {"default": "m", "steps": {"review": {"model": "m", "extra_body": {"thinking_token_budget": 2000}}}})
    _FakeVllm.reasoning_parser = False
    reviewer = llm.build_model("review")
    replies = _call(reviewer, _request())
    assert replies[-1].content.parts[0].text == '{"ok": true}'
    first, retry = _FakeVllm.requests
    assert first["body"]["thinking_token_budget"] == 2000
    assert "thinking_token_budget" not in retry["body"] and retry["body"]["top_k"] == 20  # the rest is kept
    _call(reviewer, _request())  # and the reviewer stops sending it
    assert len(_FakeVllm.requests) == 3 and "thinking_token_budget" not in _FakeVllm.requests[2]["body"]


def test_a_server_with_a_reasoning_parser_gets_the_budget(use_models, fake_vllm):
    use_models(_endpoint(fake_vllm), {"default": "m", "steps": {"review": {"model": "m", "extra_body": {"thinking_token_budget": 2000}}}})
    _call(llm.build_model("review"), _request())
    (sent,) = _FakeVllm.requests
    assert sent["body"]["thinking_token_budget"] == 2000


def test_a_model_error_is_printed_with_the_step_model_endpoint_and_server_message(use_models, fake_vllm, caplog):
    use_models(_endpoint(fake_vllm, api_key="k-secret", headers={"X-Gateway-Token": "h-secret"}))
    message = "This model's maximum context length is 32768 tokens. However, you requested 40000 tokens."
    _FakeVllm.fail_with = (400, {"object": "error", "message": message, "type": "BadRequestError", "param": None, "code": 400})
    with caplog.at_level(logging.ERROR, logger="translator.models.llm"), pytest.raises(llm.EndpointError) as err:
        _call(llm.build_model("translate"), _request())
    expected = f"translate model Qwen/Qwen3-32B at {fake_vllm}: HTTP 400 ContextWindowExceededError: {message}"
    assert str(err.value) == expected  # what the run shows in the app
    assert f"vLLM error — {expected}" in caplog.text  # and the backend log
    assert "secret" not in caplog.text and "secret" not in str(err.value)


def test_an_unreachable_endpoint_is_printed_without_credentials(use_models, caplog):
    with socket.socket() as sock:  # a port with nothing listening
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    use_models(_endpoint(f"http://127.0.0.1:{port}/v1?token=q-secret"))
    with caplog.at_level(logging.ERROR, logger="translator.models.llm"), pytest.raises(llm.EndpointError) as err:
        _call(llm.build_model("ocr_check"), _request())
    assert str(err.value).startswith(f"ocr_check model Qwen/Qwen3-32B at http://127.0.0.1:{port}/v1: ")
    assert "connect" in str(err.value).lower() and "secret" not in caplog.text
    assert llm.safe_url("https://user:pw@gpu-1.internal:8100/v1?token=x") == "https://gpu-1.internal:8100/v1"

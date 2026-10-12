"""Model endpoints: every role calls its own OpenAI-compatible server (vLLM) directly, with its API key,
extra headers and extra body fields; calls retry on rate limits and time out instead of hanging."""

import asyncio
import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import types
from pydantic import ValidationError

from translator import llm, structured
from translator.config import Settings, get_settings


@pytest.fixture
def settings(monkeypatch):
    """The live settings, restored after the test."""
    s = get_settings()

    def set_(**values):
        for k, v in values.items():
            monkeypatch.setattr(s, k, v)
        return s

    return set_


def test_model_calls_retry_and_time_out():
    for role in ("ocr_check", "translate", "review", "editor", "lqa"):
        model = llm.build_model(role)
        if isinstance(model, str):  # a native Gemini model: ADK's own client
            continue
        assert model._additional_args["num_retries"] == get_settings().model_retries
        assert model._additional_args["timeout"] == get_settings().model_timeout


def test_a_role_calls_its_vllm_endpoint_with_key_headers_and_extra_body(settings):
    settings(
        model="Qwen/Qwen3-VL-8B-Instruct",
        model_api_base="http://gpu-1:8100/v1",
        model_api_key="k-default",
        model_headers={"X-Gateway-Token": "t-default"},
        model_extra_body=None,
        translate_model="Qwen/Qwen3-32B",
        translate_api_base="http://gpu-2:8100/v1",
        review_extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    ocr = llm.build_model("ocr_check")
    assert ocr.model == "hosted_vllm/Qwen/Qwen3-VL-8B-Instruct"  # the served name, through LiteLLM's vLLM provider
    assert ocr._additional_args["api_base"] == "http://gpu-1:8100/v1"
    assert ocr._additional_args["api_key"] == "k-default"
    assert ocr._additional_args["extra_headers"] == {"X-Gateway-Token": "t-default"}
    assert "extra_body" not in ocr._additional_args

    translate = llm.build_model("translate")  # its own server; key and headers inherited
    assert translate.model == "hosted_vllm/Qwen/Qwen3-32B"
    assert translate._additional_args["api_base"] == "http://gpu-2:8100/v1"
    assert translate._additional_args["extra_headers"] == {"X-Gateway-Token": "t-default"}

    review = llm.build_model("review")
    budget = {"thinking_token_budget": get_settings().review_reasoning_tokens}
    assert review._additional_args["extra_body"] == {**budget, "chat_template_kwargs": {"enable_thinking": False}}
    assert llm.build_model("lqa")._additional_args["extra_body"] == review._additional_args["extra_body"]  # LQA = review
    assert llm.model_name("translate") == "Qwen/Qwen3-32B"


def test_a_role_can_replace_or_drop_the_default_headers(settings):
    settings(model_headers={"X-Gateway-Token": "t"}, ocr_check_headers={"X-Other": "o"}, editor_headers={})
    assert get_settings().endpoint("ocr_check").headers == {"X-Other": "o"}  # replaced, not merged
    assert get_settings().endpoint("editor").headers == {}
    assert "extra_headers" not in llm.build_model("editor")._additional_args
    assert get_settings().endpoint("translate").headers == {"X-Gateway-Token": "t"}


def test_reviewer_thinking_is_capped_with_vllms_budget(settings):
    settings(model_api_base="http://localhost:8100/v1", model_extra_body=None, review_reasoning_tokens=1500)
    for role in ("review", "lqa"):
        assert llm.build_model(role)._additional_args["extra_body"] == {"thinking_token_budget": 1500}
    for role in ("ocr_check", "translate", "editor"):  # the translator thinks as it likes
        assert "extra_body" not in llm.build_model(role)._additional_args
    settings(review_extra_body={"thinking_token_budget": 500})  # the role's own extra body wins
    assert llm.build_model("review")._additional_args["extra_body"] == {"thinking_token_budget": 500}
    settings(review_extra_body=None, review_reasoning_tokens=0)
    assert "extra_body" not in llm.build_model("review")._additional_args
    settings(model_api_base="", review_model="anthropic/claude-haiku-5-5", review_reasoning_tokens=1500)
    assert "extra_body" not in llm.build_model("review")._additional_args  # a hosted provider: not a vLLM field


def test_an_explicit_vllm_prefix_isnt_doubled(settings):
    settings(model="hosted_vllm/my-model", model_api_base="http://localhost:8100/v1")
    assert llm.build_model("translate").model == "hosted_vllm/my-model"
    assert llm.model_name("translate") == "my-model"


def test_a_hosted_openai_compatible_service_is_just_another_endpoint(settings):
    """OpenRouter (or any OpenAI-compatible service): the role's URL, model name and key, nothing special."""
    settings(translate_model="anthropic/claude-haiku-5.5", translate_api_base="https://openrouter.ai/api/v1",
             translate_api_key="or-key", translate_headers={})
    model = llm.build_model("translate")
    assert model.model == "hosted_vllm/anthropic/claude-haiku-5.5"
    assert model._additional_args["api_base"] == "https://openrouter.ai/api/v1" and model._additional_args["api_key"] == "or-key"
    assert llm.model_name("translate") == "anthropic/claude-haiku-5.5"


def test_headers_and_extra_body_are_read_from_the_environment_as_json(monkeypatch):
    monkeypatch.setenv("MODEL_HEADERS", '{"X-Gateway-Token": "abc", "CF-Access-Client-Id": "id"}')
    monkeypatch.setenv("REVIEW_EXTRA_BODY", '{"chat_template_kwargs": {"enable_thinking": false}}')
    monkeypatch.setenv("OCR_CHECK_HEADERS", "")  # empty: send none (and don't inherit)
    s = Settings()
    assert s.endpoint("translate").headers == {"X-Gateway-Token": "abc", "CF-Access-Client-Id": "id"}
    assert s.endpoint("ocr_check").headers == {}
    assert s.endpoint("review").extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert "abc" not in repr(s)  # header values may be credentials

    monkeypatch.setenv("MODEL_HEADERS", '{"X-Gateway-Token": "secret-value"')  # broken JSON
    with pytest.raises(ValidationError) as err:
        Settings()
    assert "model_headers" in str(err.value) and "secret-value" not in str(err.value)
    monkeypatch.setenv("MODEL_HEADERS", '["not", "an object"]')
    with pytest.raises(ValidationError, match="JSON object"):
        Settings()


@pytest.mark.structured
def test_endpoint_models_get_structured_output(settings):
    settings(structured_output="auto", model_api_base="http://localhost:8100/v1")
    structured.enabled.cache_clear()
    try:
        assert structured.enabled("translate")  # vLLM's guided decoding follows the JSON schema
    finally:
        structured.enabled.cache_clear()


class _FakeVllm(BaseHTTPRequestHandler):
    """An OpenAI-compatible /v1/chat/completions that records each request. With `reasoning_parser` off it
    answers a thinking budget the way vLLM does."""

    requests: list[dict] = []
    reasoning_parser = True
    fail_with: tuple[int, dict] | None = None  # (status, body) to answer every request with
    content = '{"ok": true}'  # the answer's text

    def _send(self, status: int, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeVllm.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if _FakeVllm.fail_with:
            return self._send(*_FakeVllm.fail_with)
        if "thinking_token_budget" in body and not _FakeVllm.reasoning_parser:
            message = ("thinking_token_budget is set but reasoning_config is not configured. "
                       "Please set --reasoning-parser and/or --reasoning-config to use thinking_token_budget.")
            return self._send(400, {"object": "error", "message": message, "type": "BadRequestError", "param": None, "code": 400})
        reply = {
            "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": _FakeVllm.content}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        }
        self._send(200, reply)

    def log_message(self, *_args):
        pass


def _call(model, request: LlmRequest) -> list:
    async def run():
        return [r async for r in model.generate_content_async(request)]

    return asyncio.run(run())


def _request() -> LlmRequest:
    return LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="Review: Abnahme → acceptance")])])


@pytest.fixture
def fake_vllm():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeVllm)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _FakeVllm.requests, _FakeVllm.reasoning_parser, _FakeVllm.fail_with = [], True, None
    _FakeVllm.content = '{"ok": true}'
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()
    server.server_close()


def test_the_request_reaches_the_server_as_configured(settings, fake_vllm):
    """What actually goes over the wire (a local stand-in server, not a real model)."""
    settings(
        model="Qwen/Qwen3-32B",
        model_api_base=fake_vllm,
        model_api_key="k-123",
        model_headers={"X-Gateway-Token": "t-456", "CF-Access-Client-Id": "id.access"},
        model_extra_body={"chat_template_kwargs": {"enable_thinking": False}, "top_k": 20},
        model_retries=0,
    )
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


def test_a_server_without_a_reasoning_parser_gets_the_review_without_a_budget(settings, fake_vllm):
    settings(model_api_base=fake_vllm, model_extra_body={"top_k": 20}, review_reasoning_tokens=2000, model_retries=0)
    _FakeVllm.reasoning_parser = False
    reviewer = llm.build_model("review")
    replies = _call(reviewer, _request())
    assert replies[-1].content.parts[0].text == '{"ok": true}'
    first, retry = _FakeVllm.requests
    assert first["body"]["thinking_token_budget"] == 2000
    assert "thinking_token_budget" not in retry["body"] and retry["body"]["top_k"] == 20  # the rest is kept
    _call(reviewer, _request())  # and the reviewer stops sending it
    assert len(_FakeVllm.requests) == 3 and "thinking_token_budget" not in _FakeVllm.requests[2]["body"]


def test_thinking_written_into_the_answer_is_split_off(settings, fake_vllm):
    """A reasoning model on a server without a reasoning parser: its thinking ends with `</think>` inside the
    answer (the opening tag is in the chat template). It becomes a thought part, as with a parser."""
    settings(ocr_model="Qwen/Qwen3-VL-8B-Thinking", ocr_api_base=fake_vllm, model_retries=0)
    _FakeVllm.content = "The user wants me to transcribe page 2. Let me be careful.\n</think>\n\n[[HEADER]] Kopf\n\nText."
    (reply,) = _call(llm.build_model("ocr"), _request())
    thought, answer = reply.content.parts
    assert thought.thought and thought.text == "The user wants me to transcribe page 2. Let me be careful."
    assert not answer.thought and answer.text == "[[HEADER]] Kopf\n\nText."
    _FakeVllm.content = "<think>short</think>Text."  # with the opening tag too
    assert [p.text for p in _call(llm.build_model("ocr"), _request())[0].content.parts] == ["short", "Text."]
    _FakeVllm.content = "Plain answer."  # no thinking: untouched
    assert [p.text for p in _call(llm.build_model("ocr"), _request())[0].content.parts] == ["Plain answer."]


def test_a_server_with_a_reasoning_parser_gets_the_budget(settings, fake_vllm):
    settings(model_api_base=fake_vllm, model_extra_body=None, review_reasoning_tokens=2000, model_retries=0)
    _call(llm.build_model("review"), _request())
    (sent,) = _FakeVllm.requests
    assert sent["body"]["thinking_token_budget"] == 2000


def test_a_vllm_error_is_printed_with_the_role_model_endpoint_and_server_message(settings, fake_vllm, caplog):
    settings(model="Qwen/Qwen3-32B", model_api_base=fake_vllm, model_api_key="k-secret",
             model_headers={"X-Gateway-Token": "h-secret"}, model_retries=0)
    message = "This model's maximum context length is 32768 tokens. However, you requested 40000 tokens."
    _FakeVllm.fail_with = (400, {"object": "error", "message": message, "type": "BadRequestError", "param": None, "code": 400})
    with caplog.at_level(logging.ERROR, logger="translator.llm"), pytest.raises(llm.EndpointError) as err:
        _call(llm.build_model("translate"), _request())
    expected = f"translate model Qwen/Qwen3-32B at {fake_vllm}: HTTP 400 ContextWindowExceededError: {message}"
    assert str(err.value) == expected  # what the run shows in the app
    assert f"vLLM error — {expected}" in caplog.text  # and the backend log
    assert "secret" not in caplog.text and "secret" not in str(err.value)


def test_an_unreachable_endpoint_is_printed_without_credentials(settings, caplog):
    with socket.socket() as sock:  # a port with nothing listening
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings(model_api_base=f"http://127.0.0.1:{port}/v1?token=q-secret", model_retries=0, model_timeout=5)
    with caplog.at_level(logging.ERROR, logger="translator.llm"), pytest.raises(llm.EndpointError) as err:
        _call(llm.build_model("ocr_check"), _request())
    assert str(err.value).startswith(f"ocr_check model {get_settings().model} at http://127.0.0.1:{port}/v1: ")
    assert "connect" in str(err.value).lower() and "secret" not in caplog.text
    assert llm.safe_url("https://user:pw@gpu-1.internal:8100/v1?token=x") == "https://gpu-1.internal:8100/v1"

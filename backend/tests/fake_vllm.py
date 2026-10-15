"""A stand-in for an OpenAI-compatible model server (vLLM, OpenRouter…) that records each request: tests check
what goes over the wire without a real model. The `fake_vllm` fixture (conftest) runs one."""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler

from google.adk.models.llm_request import LlmRequest
from google.genai import types


class FakeVllm(BaseHTTPRequestHandler):
    """An OpenAI-compatible /v1/chat/completions that records each request. With `reasoning_parser` off it
    answers a thinking budget the way vLLM does."""

    requests: list[dict] = []
    reasoning_parser = True
    fail_with: tuple[int, dict] | None = None  # (status, body) to answer every request with
    refuse_effort = False  # an older server that doesn't know `reasoning_effort`
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
        FakeVllm.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if FakeVllm.fail_with:
            return self._send(*FakeVllm.fail_with)
        if "reasoning_effort" in body and FakeVllm.refuse_effort:
            return self._send(400, {"object": "error", "message": "reasoning_effort: Extra inputs are not permitted",
                                    "type": "BadRequestError", "param": None, "code": 400})
        if "thinking_token_budget" in body and not FakeVllm.reasoning_parser:
            message = ("thinking_token_budget is set but reasoning_config is not configured. "
                       "Please set --reasoning-parser and/or --reasoning-config to use thinking_token_budget.")
            return self._send(400, {"object": "error", "message": message, "type": "BadRequestError", "param": None, "code": 400})
        reply = {
            "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": FakeVllm.content}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        }
        self._send(200, reply)

    def log_message(self, *_args):
        pass


def call(model, request: LlmRequest) -> list:
    async def run():
        return [r async for r in model.generate_content_async(request)]

    return asyncio.run(run())


def request() -> LlmRequest:
    return LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="Review: Abnahme → acceptance")])])

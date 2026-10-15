"""Model factory: each pipeline step calls the model config/pipeline.yaml gives it (see models/config.py), on an
OpenAI-compatible server through LiteLLM. Headers for every request of a run: `request_headers(...)`."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit

import litellm
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

from .config import Step, StepModel, step_model

log = logging.getLogger(__name__)

# LiteLLM prints a "Provider List" banner whenever it looks up metadata for a model it doesn't know
# (every self-hosted model). Harmless, but it floods the logs.
litellm.suppress_debug_info = True

VLLM = "hosted_vllm/"  # LiteLLM's OpenAI-compatible provider: vLLM, SGLang, OpenRouter, Ollama, LM Studio, ...
BUDGET = "thinking_token_budget"  # vLLM's cap on a reasoning model's hidden thinking
EFFORT = "reasoning_effort"  # the standard reasoning level (OpenAI, vLLM, OpenRouter); instant = "none"
EFFORT_PARAM = {"instant": "none", "low": "low", "medium": "medium", "high": "high"}


_DETAIL = re.compile(r"Hosted_vllmException - (.*)", re.S)
_SSL_NOISE = re.compile(r" ssl:<[^>]*>")


class EndpointError(RuntimeError):
    """A call to a model endpoint failed: which step, model and server, and what the server said."""


_run_headers: ContextVar[dict[str, str]] = ContextVar("run_headers", default={})


@contextmanager
def request_headers(headers: dict[str, str]) -> Iterator[None]:
    """Send these headers with every model request made inside the block — including by runs started in it,
    which keep them to the end (an asyncio task copies the context it was created in). The API sets the
    headers named in `defaults.forward_headers` this way for each request; integrations can add their own."""
    token = _run_headers.set({**_run_headers.get(), **headers})
    try:
        yield
    finally:
        _run_headers.reset(token)


def root_error(exc: BaseException) -> BaseException:
    """The error behind ADK's workflow wrappers: a failed step is re-raised as "Dynamic node … failed"
    (DynamicNodeFailError), with the real error — e.g. the server's message — kept on `.error`."""
    seen: set[int] = set()
    while isinstance(getattr(exc, "error", None), BaseException) and id(exc) not in seen:
        seen.add(id(exc))
        exc = exc.error
    return exc


def error_text(exc: BaseException) -> str:
    """What to show for a failed run or step: the real error, without the workflow wrappers."""
    exc = root_error(exc)
    return str(exc) if isinstance(exc, EndpointError) else f"{type(exc).__name__}: {exc}"


def safe_url(url: str | None) -> str:
    """An endpoint URL for logs: no credentials or query string."""
    if not url:
        return "?"
    p = urlsplit(url)
    return f"{p.scheme}://{p.hostname or ''}{f':{p.port}' if p.port else ''}{p.path}"


def server_error(e: Exception) -> str:
    """The server's own error out of a LiteLLM exception (vLLM's `message`), with the HTTP status if it answered."""
    text = str(getattr(e, "message", None) or e)
    m = _DETAIL.search(text)
    detail = _SSL_NOISE.sub("", m.group(1) if m else text).strip()
    try:
        body = json.loads(detail)
    except ValueError:
        body = None
    if not isinstance(body, dict):  # no reply to parse: a connection failure or timeout
        return f"{type(e).__name__}: {detail[:1000]}"
    msg = body.get("message") or body.get("error") or body.get("detail") or detail
    if isinstance(msg, dict):
        msg = msg.get("message") or json.dumps(msg)
    status = getattr(e, "status_code", None)
    return f"{f'HTTP {status} ' if status else ''}{type(e).__name__}: {str(msg)[:1000]}"


_THINKING = re.compile(r"^\s*(?:<think>)?(.*?)</think>\s*", re.S)


def split_thinking(response: LlmResponse) -> LlmResponse:
    """A reasoning model on a vLLM server without a reasoning parser writes its thinking into the answer
    (`<think>…</think>`; often without the opening tag, which the chat template puts in the prompt). Move it to a
    thought part, as a server with a parser does, so no caller takes it for the answer."""
    if response.partial or not response.content or not response.content.parts:
        return response
    parts: list[types.Part] = []
    for part in response.content.parts:
        found = _THINKING.match(part.text) if part.text and not part.thought else None
        if found:
            parts += [types.Part(text=found.group(1).strip(), thought=True), types.Part(text=part.text[found.end():])]
        else:
            parts.append(part)
    if len(parts) != len(response.content.parts):
        response.content = types.Content(role=response.content.role, parts=parts)
    return response


class EndpointModel(LiteLlm):
    """A model on an OpenAI-compatible endpoint (vLLM, OpenRouter, …). A failed call is logged with the server's own error (and raised with it, so
    the run shows it too). vLLM refuses a thinking budget unless the server runs with a reasoning parser
    (`--reasoning-parser`); a server without one gets the request again without the budget, and this role
    stops sending it — and its thinking, written into the answer, is split off (`split_thinking`). The same for
    a server that refuses `reasoning_effort`. Every response says which model (models.yaml id) and reasoning level
    answered, for usage (`custom_metadata`)."""

    _step: str = PrivateAttr(default="")
    _spec: StepModel | None = PrivateAttr(default=None)

    def where(self) -> str:
        return f"{self._step or 'model'} model {self.model.removeprefix(VLLM)} at {safe_url(self._additional_args.get('api_base'))}"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        # ADK names the agent's default model in the request (basic.py); a document may have chosen another one.
        llm_request.model = self.model
        if self._spec is not None:
            llm_request.config.temperature = self._spec.temperature  # None: not sent
        if run_headers := _run_headers.get():  # per request, on top of the model's own (ADK merges them)
            options = llm_request.config.http_options or types.HttpOptions()
            llm_request.config.http_options = options.model_copy(update={"headers": {**(options.headers or {}), **run_headers}})
        try:
            async for response in self._generate(llm_request, stream):
                if self._spec is not None:
                    response.custom_metadata = {**(response.custom_metadata or {}), "model_id": self._spec.id,
                                                "effort": self._spec.effort if EFFORT in self._additional_args else None}
                yield split_thinking(response)
        except Exception as e:
            message = f"{self.where()}: {server_error(e)}"
            log.error("vLLM error — %s", message)
            raise EndpointError(message) from e

    async def _generate(self, llm_request: LlmRequest, stream: bool) -> AsyncGenerator[LlmResponse, None]:
        try:
            async for response in super().generate_content_async(llm_request, stream):
                yield response
            return
        except litellm.BadRequestError as e:
            extra = self._additional_args.get("extra_body") or {}
            if EFFORT in str(e) and EFFORT in self._additional_args:
                log.warning("vLLM error — %s refused reasoning_effort (%s); retrying without it, and not sending it again",
                            self.where(), server_error(e))
                del self._additional_args[EFFORT]
            elif BUDGET in str(e) and BUDGET in extra:
                log.warning("vLLM error — %s refused the thinking budget (%s); retrying without it, and not sending it again",
                            self.where(), server_error(e))
                rest = {k: v for k, v in extra.items() if k != BUDGET}
                if rest:
                    self._additional_args["extra_body"] = rest
                else:
                    del self._additional_args["extra_body"]
            else:
                raise
        async for response in super().generate_content_async(llm_request, stream):
            yield response


def build_model(step: Step, spec: StepModel | None = None) -> EndpointModel:
    """The model for a pipeline step: `spec` (a document's choice, models/routing.py), or pipeline.yaml's."""
    m = spec or step_model(step)
    # Rate limits are retried with exponential backoff, other API errors a few times — a busy server
    # shouldn't fail a whole document. A stalled connection times out and is retried instead of blocking
    # the document: LiteLLM's own default timeout is 6000 s.
    kwargs: dict = {"num_retries": m.retries, "timeout": m.timeout}
    if m.api_key:
        kwargs["api_key"] = m.api_key
    if m.headers:
        kwargs["extra_headers"] = m.headers
    if m.extra_body:
        kwargs["extra_body"] = m.extra_body
    if m.thinking and m.effort:
        kwargs[EFFORT] = EFFORT_PARAM[m.effort]
    model = EndpointModel(model=VLLM + m.model_name, api_base=m.url, drop_params=True, **kwargs)
    model._step = step
    model._spec = m
    return model


def model_name(step: Step) -> str:
    return step_model(step).model_name

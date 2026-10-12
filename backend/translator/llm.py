"""Model factory: every agent role gets a model from its configured endpoint (model-agnostic via LiteLLM)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from urllib.parse import urlsplit

import litellm
from google.adk.models.base_llm import BaseLlm
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

from .config import Role, get_settings

log = logging.getLogger(__name__)

# LiteLLM prints a "Provider List" banner whenever it looks up metadata for a model it doesn't know
# (every self-hosted model). Harmless, but it floods the logs.
litellm.suppress_debug_info = True

VLLM = "hosted_vllm/"  # LiteLLM's OpenAI-compatible provider for vLLM (and SGLang, Ollama, LM Studio, ...)
BUDGET = "thinking_token_budget"  # vLLM's cap on a reasoning model's hidden thinking


_DETAIL = re.compile(r"Hosted_vllmException - (.*)", re.S)
_SSL_NOISE = re.compile(r" ssl:<[^>]*>")


class EndpointError(RuntimeError):
    """A call to a model endpoint failed: which role, model and server, and what the server said."""


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
    """A model on a vLLM endpoint. A failed call is logged with the server's own error (and raised with it, so
    the run shows it too). vLLM refuses a thinking budget unless the server runs with a reasoning parser
    (`--reasoning-parser`); a server without one gets the request again without the budget, and this role
    stops sending it — and its thinking, written into the answer, is split off (`split_thinking`)."""

    _role: str = PrivateAttr(default="")

    def where(self) -> str:
        return f"{self._role or 'model'} model {self.model.removeprefix(VLLM)} at {safe_url(self._additional_args.get('api_base'))}"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        try:
            async for response in self._generate(llm_request, stream):
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
            if BUDGET not in str(e) or BUDGET not in extra:
                raise
            log.warning("vLLM error — %s refused the thinking budget (%s); retrying without it, and not sending it again",
                        self.where(), server_error(e))
            rest = {k: v for k, v in extra.items() if k != BUDGET}
            if rest:
                self._additional_args["extra_body"] = rest
            else:
                del self._additional_args["extra_body"]
        async for response in super().generate_content_async(llm_request, stream):
            yield response


def build_model(role: Role) -> BaseLlm | str:
    """Return an ADK model for a role.

    With an API base, the role calls that OpenAI-compatible server directly — vLLM, or a hosted one such as
    OpenRouter (https://openrouter.ai/api/v1): MODEL is the model name there, sent with the API key, extra headers
    and extra body fields. Without one, MODEL is a LiteLLM provider model
    (`anthropic/claude-...`, `gemini/gemini-...`), and a bare `gemini-*` uses ADK's native Gemini client.
    """
    ep = get_settings().endpoint(role)
    if ep.model.startswith("gemini-") and not ep.api_base:
        return ep.model
    # Rate limits are retried with exponential backoff, other API errors a few times — a busy server
    # shouldn't fail a whole document. A stalled connection times out and is retried instead of blocking
    # the document: LiteLLM's own default timeout is 6000 s.
    kwargs: dict = {"num_retries": get_settings().model_retries, "timeout": get_settings().model_timeout}
    if ep.api_key:
        kwargs["api_key"] = ep.api_key
    if ep.headers:
        kwargs["extra_headers"] = ep.headers
    if not ep.api_base:
        if ep.extra_body:
            kwargs["extra_body"] = ep.extra_body
        return LiteLlm(model=ep.model, drop_params=True, **kwargs)
    # Without a cap a reasoning model thinks for minutes before a short review. The role's own extra body wins.
    budget = get_settings().review_reasoning_tokens if role in ("review", "lqa") else 0
    extra_body = {BUDGET: budget, **ep.extra_body} if budget > 0 else ep.extra_body
    if extra_body:
        kwargs["extra_body"] = extra_body
    model = ep.model if ep.model.startswith(VLLM) else VLLM + ep.model
    endpoint_model = EndpointModel(model=model, api_base=ep.api_base, drop_params=True, **kwargs)
    endpoint_model._role = role
    return endpoint_model


def model_name(role: Role) -> str:
    return get_settings().endpoint(role).model.removeprefix(VLLM)

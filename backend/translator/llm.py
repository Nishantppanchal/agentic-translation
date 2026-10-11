"""Model factory: every agent role gets a model from config (model-agnostic via LiteLLM)."""

from __future__ import annotations

import litellm
from google.adk.models.base_llm import BaseLlm
from google.adk.models.lite_llm import LiteLlm

from .config import Role, get_settings

# LiteLLM prints a "Provider List" banner whenever it looks up metadata for a model newer than its
# bundled model map (e.g. fresh OpenRouter models). Harmless, but it floods the logs.
litellm.suppress_debug_info = True


def build_model(role: Role) -> BaseLlm | str:
    """Return an ADK model for a role.

    `gemini-*` with no API base → ADK's native Gemini client (plain string).
    Anything else → LiteLLM, e.g. `openai/<model>` + MODEL_API_BASE for Ollama / vLLM /
    LM Studio, `anthropic/claude-...`, `gemini/gemini-...`, `openai/gpt-...`.
    """
    model, api_base, api_key = get_settings().role_model(role)
    if model.startswith("gemini-") and not api_base:
        return model
    # Rate limits (e.g. a shared upstream pool on OpenRouter) are retried with exponential backoff,
    # other API errors a few times — a busy provider shouldn't fail a whole document.
    # A stalled connection (it happens with budget providers) times out and is retried instead of
    # blocking the document: LiteLLM's own default timeout is 6000 s.
    kwargs: dict = {"num_retries": get_settings().model_retries, "timeout": get_settings().model_timeout}
    if (budget := reasoning_budget(role, model)) is not None:
        kwargs["extra_body"] = {"reasoning": {"max_tokens": budget}}
    if api_base:
        kwargs["api_base"] = api_base
    if api_key:
        kwargs["api_key"] = api_key
    return LiteLlm(model=model, drop_params=True, **kwargs)


def reasoning_budget(role: Role, model: str) -> int | None:
    """Hidden-reasoning cap for the reviewer and LQA, if the model takes one (OpenRouter's `reasoning`):
    without it a reasoning model spends minutes per page thinking before a short review."""
    budget = get_settings().review_reasoning_tokens
    if role not in ("review", "lqa") or not budget or not model.startswith("openrouter/"):
        return None
    from . import openrouter  # local: openrouter → config; keep the import graph flat

    info = openrouter.info(model)
    return budget if info is not None and "reasoning" in info["params"] else None


def model_name(role: Role) -> str:
    return get_settings().role_model(role)[0]

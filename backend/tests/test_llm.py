"""Every model call retries on rate limits and API errors, and times out instead of hanging."""

from translator.config import get_settings
from translator.llm import build_model


def test_model_calls_retry_and_time_out():
    for role in ("ocr", "translate", "review", "editor", "lqa"):
        model = build_model(role)
        if isinstance(model, str):  # a native Gemini model: ADK's own client
            continue
        assert model._additional_args["num_retries"] == get_settings().model_retries
        assert model._additional_args["timeout"] == get_settings().model_timeout



def test_reviewer_reasoning_is_capped_where_the_model_supports_it(monkeypatch):
    from translator import llm, openrouter

    s = get_settings()
    monkeypatch.setattr(s, "review_model", "openrouter/qwen/qwen3.8-flash")
    monkeypatch.setattr(s, "translate_model", "openrouter/qwen/qwen3.8-flash")
    monkeypatch.setattr(openrouter, "info", lambda model: {"params": ["reasoning", "temperature"]})
    assert llm.build_model("review")._additional_args["extra_body"] == {"reasoning": {"max_tokens": s.review_reasoning_tokens}}
    assert "extra_body" not in llm.build_model("translate")._additional_args  # the translator thinks as it likes
    monkeypatch.setattr(openrouter, "info", lambda model: {"params": ["temperature"]})
    assert "extra_body" not in llm.build_model("review")._additional_args  # not a reasoning model: nothing to cap
    monkeypatch.setattr(s, "review_reasoning_tokens", 0)
    assert llm.reasoning_budget("review", "openrouter/qwen/qwen3.8-flash") is None

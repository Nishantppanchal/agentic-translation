from google.adk.events import Event
from google.genai import types

from translator import openrouter, usage


def _ev(author: str, model: str, prompt: int, completion: int) -> Event:
    return Event(
        author=author,
        model_version=model,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt, candidates_token_count=completion, total_token_count=prompt + completion
        ),
    )


def test_usage_is_summed_per_step_and_priced(monkeypatch):
    # Prices from the (cached) OpenRouter list when LiteLLM doesn't know the model.
    monkeypatch.setattr(openrouter, "_models", {
        "anthropic/claude-haiku-5.5": {"prompt": 1e-7, "completion": 5e-7, "params": []},
        "qwen/qwen3.8-flash": {"prompt": 1.5e-7, "completion": 4.7e-7, "params": []},
    })
    events = [
        _ev("ocr_extractor", "qwen/qwen3.8-flash", 2000, 300),
        _ev("translator", "anthropic/claude-haiku-5.5", 1000, 800),
        _ev("translator", "anthropic/claude-haiku-5.5", 1200, 900),
        _ev("reviewer", "anthropic/claude-haiku-5.5", 1500, 100),
        Event(author="user"),  # no usage: ignored
    ]
    summary = usage.summarize(events)
    total = summary["total"]
    assert (total["calls"], total["prompt_tokens"], total["completion_tokens"]) == (4, 5700, 2100)
    assert total["priced"] and abs(total["cost_usd"] - (3700 * 1e-7 + 1800 * 5e-7 + 2000 * 1.5e-7 + 300 * 4.7e-7)) < 1e-12
    translation = next(r for r in summary["rows"] if r["step"] == "Translation")
    assert translation["calls"] == 2 and translation["completion_tokens"] == 1700


def test_unknown_model_cost_is_reported_as_unpriced(monkeypatch):
    monkeypatch.setattr(openrouter, "_models", {})
    summary = usage.summarize([_ev("translator", "local/some-model", 10, 10)])
    assert summary["total"]["priced"] is False and summary["rows"][0]["cost_usd"] is None

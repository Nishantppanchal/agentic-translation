from google.adk.events import Event
from google.genai import types

from translator.api import usage


def _ev(author: str, model: str, prompt: int, completion: int) -> Event:
    return Event(
        author=author,
        model_version=model,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt, candidates_token_count=completion, total_token_count=prompt + completion
        ),
    )


def test_usage_is_summed_per_step():
    events = [
        _ev("ocr_reader", "Qwen/Qwen3-VL-8B-Instruct", 2000, 300),
        _ev("translator", "Qwen/Qwen3-32B", 1000, 800),
        _ev("translator", "Qwen/Qwen3-32B", 1200, 900),
        _ev("reviewer", "Qwen/Qwen3-32B", 1500, 100),
        Event(author="user"),  # no usage: ignored
    ]
    summary = usage.summarize(events)
    total = summary["total"]
    assert (total["calls"], total["prompt_tokens"], total["completion_tokens"], total["tokens"]) == (4, 5700, 2100, 7800)
    assert "cost_usd" not in total
    translation = next(r for r in summary["rows"] if r["step"] == "Translation")
    assert translation["calls"] == 2 and translation["completion_tokens"] == 1700 and translation["tokens"] == 3900
    assert summary["rows"][0]["step"] == "Translation"  # most tokens first

"""Token usage per document, computed from the session's saved events.

ADK stores each model response's `usage_metadata` and `model_version` on its event, so no
extra bookkeeping is needed. Tokens only: models on your own vLLM servers have no per-token price.
"""

from __future__ import annotations

import logging

from ..models.config import STEP_LABELS, step_model

log = logging.getLogger(__name__)

STEP_OF_AGENT = {
    "ocr_reader": "ocr",
    "ocr_checker": "ocr_check",
    "analyst": "analyse",
    "translator": "translate",
    "refiner": "refine",
    "reviewer": "review",
    "editor": "editor",
    "lqa_reviewer": "lqa",
    "rewriter": "rewrite",
    "consistency_fixer": "polish",
}


def summarize(events) -> dict:
    """Tokens per pipeline step and model, plus totals."""
    rows: dict[tuple[str, str], dict] = {}
    for ev in events:
        usage = getattr(ev, "usage_metadata", None)
        if not usage or getattr(ev, "partial", False):
            continue
        step = STEP_OF_AGENT.get(ev.author, "editor")
        model = ev.model_version or step_model(step).model_name
        step = STEP_LABELS[step]
        row = rows.setdefault(
            (step, model), {"step": step, "model": model, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        )
        row["calls"] += 1
        row["prompt_tokens"] += usage.prompt_token_count or 0
        # OpenAI-style completion tokens already include reasoning ("thinking") tokens.
        row["completion_tokens"] += usage.candidates_token_count or 0

    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    for row in rows.values():
        row["tokens"] = row["prompt_tokens"] + row["completion_tokens"]
        for k in ("calls", "prompt_tokens", "completion_tokens"):
            total[k] += row[k]
    total["tokens"] = total["prompt_tokens"] + total["completion_tokens"]
    return {"total": total, "rows": sorted(rows.values(), key=lambda r: -r["tokens"])}

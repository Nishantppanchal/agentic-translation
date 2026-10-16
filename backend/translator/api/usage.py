"""Token usage per document, computed from the session's saved events.

ADK stores each model response's `usage_metadata` on its event, and our model wrapper adds which model (its
models.yaml id) and reasoning level answered (`custom_metadata`; older events: the server's `model_version`).
Tokens only: models on your own vLLM servers have no per-token price.
"""

from __future__ import annotations

import logging

from ..models.config import STEP_LABELS

log = logging.getLogger(__name__)

STEP_OF_AGENT = {
    "ocr_reader": "ocr",
    "ocr_checker": "ocr_check",
    "figure_reader": "ocr",
    "analyst": "analyse",
    "translator": "translate",
    "refiner": "refine",
    "reviewer": "review",
    "editor": "editor",
    "lqa_reviewer": "lqa",
    "rewriter": "rewrite",
    "consistency_fixer": "polish",
}


def summarize(events, assist: list[dict] | None = None) -> dict:
    """Tokens per pipeline step and model, plus totals. `assist`: the document's AI-assist calls (suggestions,
    completions, translation summaries — `ProjectStore.assist_usage`), which leave no session event."""
    rows: dict[tuple[str, str, str | None], dict] = {}
    for ev in events:
        usage = getattr(ev, "usage_metadata", None)
        if not usage or getattr(ev, "partial", False):
            continue
        step = STEP_LABELS[STEP_OF_AGENT.get(ev.author, "editor")]
        meta = getattr(ev, "custom_metadata", None) or {}
        model = meta.get("model_id") or ev.model_version or "unknown"
        effort = meta.get("effort")
        row = rows.setdefault((step, model, effort), {"step": step, "model": model, "effort": effort, "calls": 0,
                                                      "prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0})
        row["calls"] += 1
        row["prompt_tokens"] += usage.prompt_token_count or 0
        # OpenAI-style completion tokens already include reasoning ("thinking") tokens; shown apart as well.
        row["completion_tokens"] += usage.candidates_token_count or 0
        row["reasoning_tokens"] += getattr(usage, "thoughts_token_count", None) or 0
    for a in assist or []:
        step = STEP_LABELS.get(a["step"], a["step"])
        row = rows.setdefault((step, a["model_id"], a.get("effort")), {
            "step": step, "model": a["model_id"], "effort": a.get("effort"), "calls": 0, "prompt_tokens": 0,
            "completion_tokens": 0, "reasoning_tokens": 0})
        for k in ("calls", "prompt_tokens", "completion_tokens", "reasoning_tokens"):
            row[k] += a.get(k) or 0

    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    for row in rows.values():
        row["tokens"] = row["prompt_tokens"] + row["completion_tokens"]
        for k in ("calls", "prompt_tokens", "completion_tokens"):
            total[k] += row[k]
    total["tokens"] = total["prompt_tokens"] + total["completion_tokens"]
    return {"total": total, "rows": sorted(rows.values(), key=lambda r: -r["tokens"])}

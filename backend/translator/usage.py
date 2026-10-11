"""Token usage and cost per document, computed from the session's saved events.

ADK stores each model response's `usage_metadata` and `model_version` on its event, so no
extra bookkeeping is needed. Prices: LiteLLM's model map first, then OpenRouter's public
model list (`openrouter.py`, cached for a day) for models newer than LiteLLM knows about.
"""

from __future__ import annotations

import logging

import litellm

from . import openrouter
from .config import get_settings

log = logging.getLogger(__name__)

STEP_OF_AGENT = {
    "ocr_extractor": ("OCR", "ocr"),
    "figure_detector": ("Figure detection", "ocr"),
    "ocr_checker": ("OCR check", "ocr_check"),
    "translator": ("Translation", "translate"),
    "refiner": ("Refinement", "translate"),
    "reviewer": ("Review", "review"),
    "editor": ("Chat editor", "editor"),
    "lqa_reviewer": ("LQA", "lqa"),
    "rewriter": ("Rewrite", "translate"),
    "consistency_fixer": ("Consistency", "translate"),
}
def price_per_token(model: str) -> tuple[float, float] | None:
    bare = model.removeprefix("openrouter/")
    for key in (model, f"openrouter/{bare}", bare):
        info = litellm.model_cost.get(key)
        if info and info.get("input_cost_per_token") is not None:
            return float(info["input_cost_per_token"]), float(info.get("output_cost_per_token") or 0)
    info = openrouter.info(bare)
    return (info["prompt"], info["completion"]) if info else None


def summarize(events) -> dict:
    """Tokens and cost per pipeline step and model, plus totals."""
    settings = get_settings()
    rows: dict[tuple[str, str], dict] = {}
    for ev in events:
        usage = getattr(ev, "usage_metadata", None)
        if not usage or getattr(ev, "partial", False):
            continue
        step, role = STEP_OF_AGENT.get(ev.author, (ev.author, "editor"))
        model = ev.model_version or settings.role_model(role)[0]
        row = rows.setdefault(
            (step, model), {"step": step, "model": model, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        )
        row["calls"] += 1
        row["prompt_tokens"] += usage.prompt_token_count or 0
        # OpenAI-style completion tokens already include reasoning ("thinking") tokens.
        row["completion_tokens"] += usage.candidates_token_count or 0

    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "priced": True}
    for row in rows.values():
        price = price_per_token(row["model"])
        row["cost_usd"] = (row["prompt_tokens"] * price[0] + row["completion_tokens"] * price[1]) if price else None
        for k in ("calls", "prompt_tokens", "completion_tokens"):
            total[k] += row[k]
        if row["cost_usd"] is None:
            total["priced"] = False
        else:
            total["cost_usd"] += row["cost_usd"]
    total["tokens"] = total["prompt_tokens"] + total["completion_tokens"]
    return {"total": total, "rows": sorted(rows.values(), key=lambda r: -(r["cost_usd"] or 0))}

"""What the app shows about the models and the pipeline: a display name, whose model it is (for its logo), where
it runs (OpenRouter, Ollama, this computer or an own server — never a URL, host, key or header), and the pipeline as a diagram of its steps.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .config import DEFAULT_EFFORT, ModelSpec

# The organisation prefix of a model name ("anthropic/claude-…", "Qwen/Qwen3-…") → vendor.
_ORGS = {
    "anthropic": "anthropic", "qwen": "qwen", "alibaba": "qwen", "openai": "openai", "google": "google",
    "meta-llama": "meta", "meta": "meta", "mistralai": "mistral", "mistral": "mistral", "deepseek": "deepseek",
    "deepseek-ai": "deepseek", "x-ai": "xai", "xai": "xai", "microsoft": "microsoft", "nvidia": "nvidia",
    "cohere": "cohere", "moonshotai": "moonshot", "z-ai": "zhipu", "thudm": "zhipu", "zai-org": "zhipu",
    "minimax": "minimax", "baidu": "baidu", "ibm-granite": "ibm", "amazon": "amazon", "01-ai": "yi",
}
# Model families → vendor, when the name has no organisation prefix (a model on your own vLLM, say).
_FAMILIES = (
    (r"claude", "anthropic"), (r"qwen|qwq", "qwen"), (r"gpt|\bo[134]\b|o[134]-", "openai"), (r"gemini|gemma", "google"),
    (r"llama", "meta"), (r"mistral|mixtral|pixtral|ministral|magistral", "mistral"), (r"deepseek", "deepseek"),
    (r"grok", "xai"), (r"\bphi", "microsoft"), (r"kimi", "moonshot"), (r"glm", "zhipu"), (r"command", "cohere"),
    (r"nemotron", "nvidia"), (r"granite", "ibm"), (r"ernie", "baidu"), (r"minimax", "minimax"),
)
_UPPER = {"gpt", "vl", "ai", "oss", "glm", "it", "moe"}


def vendor(m: ModelSpec) -> str | None:
    if m.vendor:
        return m.vendor.lower()
    name = m.model_name.lower()
    if "/" in name and (org := _ORGS.get(name.split("/", 1)[0])):
        return org
    return next((v for pattern, v in _FAMILIES if re.search(pattern, name)), None)


def label(m: ModelSpec) -> str:
    """The name people see: models.yaml's `label`, else the model name tidied ("anthropic/claude-haiku-5.5" →
    "Claude Haiku 5.5", "Qwen/Qwen3-VL-8B-Instruct" → "Qwen3 VL 8B Instruct")."""
    if m.label:
        return m.label
    words = re.split(r"[-_\s]+", m.model_name.rsplit("/", 1)[-1].split(":", 1)[0])
    return " ".join(w.upper() if w.lower() in _UPPER else w[:1].upper() + w[1:] for w in words if w) or m.id


def server(m: ModelSpec) -> tuple[str, str]:
    """(kind, where) — kind is openrouter, ollama or custom; `where` says it for people without naming a host
    (an internal hostname stays on the server, like the URL, key and headers)."""
    try:
        parts = urlsplit(m.url)
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        return "custom", "own server"
    if host == "openrouter.ai" or host.endswith(".openrouter.ai"):
        return "openrouter", "OpenRouter"
    if port == 11434 or "ollama" in host:
        return "ollama", "Ollama"
    return "custom", "this computer" if host in ("localhost", "127.0.0.1", "::1") else "own server"


def describe(m: ModelSpec) -> dict[str, Any]:
    """A model as the app lists it (GET /api/models)."""
    kind, where = server(m)
    return {"id": m.id, "model_name": m.model_name, "label": label(m), "vendor": vendor(m), "server": kind, "where": where,
            "vision": m.vision, "thinking": m.thinking, "structured_output": m.structured_output,
            "default_effort": (m.effort or DEFAULT_EFFORT) if m.thinking else None}


# The pipeline as a diagram: its steps (a model step has `step`), people's turns ("you") and what feeds it ("context").
# The app lays it out by hand (components/settings/PipelineFlow.tsx): the steps with arrows at their (row, col),
# the steps that run on request (no arrows) listed under the diagram by row. Every model step appears once
# (tests/test_model_choice.py checks it, and that no arrow along a row passes behind another step).
ROWS = ("Reading (PDFs and images)", "Translating", "Reviewing", "On request, once it's ready", "AI assist")
NODES: tuple[dict[str, Any], ...] = (
    {"id": "ocr", "step": "ocr", "label": "Read the pages", "row": 0, "col": 0},
    {"id": "ocr_check", "step": "ocr_check", "label": "Check the reading", "row": 0, "col": 1},
    {"id": "source_check", "kind": "you", "label": "You check the source", "row": 0, "col": 2},
    {"id": "office", "kind": "context", "label": "Word, PowerPoint, Excel: text read from the file", "row": 0, "col": 3},
    {"id": "memory", "kind": "context", "label": "TM: reuse earlier translations", "row": 1, "col": 0},  # a lookup
    {"id": "analyse", "step": "analyse", "label": "Analysis", "row": 1, "col": 1},
    {"id": "questions", "kind": "you", "label": "You answer questions", "row": 1, "col": 2},
    {"id": "translate", "step": "translate", "label": "Translation", "row": 1, "col": 3},
    {"id": "refine", "step": "refine", "label": "Refinement", "row": 2, "col": 0},  # left of Review: the loop is drawn
    {"id": "review", "step": "review", "label": "Review", "row": 2, "col": 1},      # between them, never through a node
    {"id": "polish", "step": "polish", "label": "Consistency", "row": 2, "col": 2},
    {"id": "ready", "kind": "context", "label": "Ready. What you confirm goes into the TM", "row": 2, "col": 3},
    {"id": "editor", "step": "editor", "label": "Chat", "row": 3, "col": 0},
    {"id": "rewrite", "step": "rewrite", "label": "Rewrites", "row": 3, "col": 1},
    {"id": "lqa", "step": "lqa", "label": "Quality score", "row": 3, "col": 2},
    {"id": "suggest", "step": "suggest", "label": "Suggested prompts", "row": 4, "col": 0},
    {"id": "complete", "step": "complete", "label": "Tab completion", "row": 4, "col": 1},
    {"id": "notes", "step": "notes", "label": "Translation summary", "row": 4, "col": 2},
)
# (from, to, label): a label says when that way is taken (the review loops with refinement until no issues are left).
EDGES: tuple[tuple[str, str, str], ...] = (
    ("ocr", "ocr_check", ""), ("ocr_check", "source_check", ""), ("source_check", "memory", ""), ("office", "memory", ""),
    ("memory", "analyse", ""), ("analyse", "questions", ""), ("questions", "translate", ""), ("translate", "review", ""),
    ("review", "refine", "issues found"), ("refine", "review", ""), ("review", "polish", "no issues"),
    ("polish", "ready", ""),
)


def flow() -> dict[str, Any]:
    nodes = [{"kind": "step", **n} for n in NODES]
    return {"rows": list(ROWS), "nodes": nodes, "edges": [list(e) for e in EDGES]}  # [from, to, label]

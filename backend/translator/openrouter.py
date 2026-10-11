"""OpenRouter's public model list (prices + supported parameters), cached in memory and on disk for a day."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL = 24 * 3600
_models: dict[str, dict] | None = None


def _cache_file() -> Path:
    return get_settings().data_dir / "openrouter_models.json"


def models() -> dict[str, dict]:
    """{model id: {"prompt": $/token, "completion": $/token, "params": [supported parameters]}}; {} when offline."""
    global _models
    if _models is not None:
        return _models
    path = _cache_file()
    try:
        cached = json.loads(path.read_text())
        if time.time() - cached["fetched_at"] < CACHE_TTL:
            _models = cached["models"]
            return _models
    except (OSError, ValueError, KeyError):
        pass
    try:
        data = httpx.get(MODELS_URL, timeout=10).json()["data"]
        _models = {
            m["id"]: {
                "prompt": float(m.get("pricing", {}).get("prompt") or 0),
                "completion": float(m.get("pricing", {}).get("completion") or 0),
                "params": m.get("supported_parameters") or [],
            }
            for m in data
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": time.time(), "models": _models}))
    except Exception:
        log.warning("Could not fetch the OpenRouter model list", exc_info=True)
        _models = {}
    return _models


def info(model: str) -> dict | None:
    """Model info for an OpenRouter id, with or without the `openrouter/` LiteLLM prefix."""
    return models().get(model.removeprefix("openrouter/"))

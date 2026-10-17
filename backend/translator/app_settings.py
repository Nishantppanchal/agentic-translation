"""App-wide settings people change in the app (Settings): the model and reasoning level for each step, whether the
dictionary is used, whether scans get a second reading, and whether the chat suggests prompts (AI assist). They are
the defaults for new documents; each document keeps its own copy (doc:models, doc:dictionary, doc:second_reader),
which the upload panel and the document's settings can change. Stored in projects.db."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from . import projects
from .models import config as model_config
from .models.config import CONFIG_ONLY_STEPS, ChoiceError, Effort, Step

log = logging.getLogger(__name__)

KEY = "app"


class StepChoice(BaseModel):
    model: str
    effort: Effort | None = None  # reasoning level; only for models with `thinking: true`


class AppSettings(BaseModel):
    models: dict[Step, StepChoice] = Field(default_factory=dict)  # steps not listed use pipeline.yaml's model
    dictionary: bool = True
    assist: bool = True  # suggested follow-up prompts and Tab completions in the chat box
    second_reader: bool = True  # a second model reads scanned pages and pictures too (ocr/second.py)


_cache: tuple[projects.ProjectStore, AppSettings] | None = None


def valid_models(models: dict) -> dict[Step, StepChoice]:
    """Only the choices models.yaml can still serve (a model may have been removed or changed since)."""
    out: dict[Step, StepChoice] = {}
    cfg = model_config.current()
    for step, raw in (models or {}).items():
        if step in CONFIG_ONLY_STEPS:
            continue  # set in pipeline.yaml only
        try:
            choice = raw if isinstance(raw, StepChoice) else StepChoice.model_validate(raw)
            cfg.check_choice(step, choice.model, choice.effort)
        except (ChoiceError, ValueError, KeyError) as exc:
            log.warning("ignoring the saved model for %s: %s", step, exc)
            continue
        out[step] = choice
    return out


def load() -> AppSettings:
    global _cache
    store = projects.get_store()
    if _cache and _cache[0] is store:
        return _cache[1]
    raw = store.get_setting(KEY) or {}
    settings = AppSettings(models=valid_models(raw.get("models") or {}), dictionary=raw.get("dictionary", True),
                           assist=bool(raw.get("assist", True)), second_reader=bool(raw.get("second_reader", True)))
    _cache = (store, settings)
    return settings


def save(settings: AppSettings) -> AppSettings:
    global _cache
    store = projects.get_store()
    store.set_setting(KEY, settings.model_dump())
    _cache = (store, settings)
    return settings

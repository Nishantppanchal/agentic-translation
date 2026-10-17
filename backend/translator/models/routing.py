"""Which model each step uses for a document: pipeline.yaml, then the app's Settings, then the document's own
choice (doc:models, set at upload or in the document's settings). Each layer is checked against models.yaml
again; a choice it can no longer serve is skipped (with a warning) and the one below it is used.

Agents ask for their model on every call (`StepAgent.canonical_model_async`), so a document's choice applies from
its next model call without restarting anything."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from . import config as model_config
from .config import CONFIG_ONLY_STEPS, STEPS, ChoiceError, Step, StepModel
from .llm import EndpointModel, build_model

log = logging.getLogger(__name__)

DOC_MODELS = "doc:models"

_models: dict[tuple, EndpointModel] = {}


def choices(state: Mapping[str, Any] | None = None) -> dict[Step, dict]:
    """{step: {"model", "effort"}} as they apply to this document (or to new documents, without a state)."""
    from .. import app_settings  # local: app_settings → projects → … → agents import this module

    cfg = model_config.current()
    # pipeline.yaml's own level (None: the default level of the model, see config.default_effort)
    out: dict[Step, dict] = {step: {"model": m.id, "effort": cfg.specs[step].effort} for step, m in cfg.steps.items()}
    layers = [{k: v.model_dump() for k, v in app_settings.load().models.items()}]
    if state is not None:
        layers.append(state.get(DOC_MODELS) or {})
    for layer in layers:
        for step, choice in layer.items():
            if step not in out or step in CONFIG_ONLY_STEPS or not isinstance(choice, Mapping):
                continue  # (the AI assist steps: pipeline.yaml's model, always)
            try:
                cfg.check_choice(step, choice.get("model", ""), choice.get("effort"))
            except ChoiceError as exc:
                log.warning("model for %s: %s; using %s instead", step, exc, out[step]["model"])
                continue
            out[step] = {"model": choice["model"], "effort": choice.get("effort")}
    return out


def resolve(step: Step, state: Mapping[str, Any] | None = None) -> StepModel:
    choice = choices(state)[step]
    return model_config.current().choose(step, choice["model"], choice["effort"])


def llm(step: Step, state: Mapping[str, Any] | None = None) -> EndpointModel:
    """The model a step calls for this document (built once per model and reasoning level)."""
    spec = resolve(step, state)
    key = (step, spec.id, spec.effort, id(model_config.current()))
    if key not in _models:
        _models[key] = build_model(step, spec)
    return _models[key]


def snapshot(overrides: Mapping[str, Any] | None = None) -> dict[Step, dict]:
    """The full choice a new document keeps (doc:models): the current defaults plus its own overrides."""
    out = choices(None)
    cfg = model_config.current()
    for step, choice in (overrides or {}).items():
        if step in STEPS and step not in CONFIG_ONLY_STEPS and choice:
            cfg.check_choice(step, choice["model"], choice.get("effort"))  # the API validated it already
            out[step] = {"model": choice["model"], "effort": choice.get("effort")}
    return out

"""Model and dictionary choices: the app's defaults for new documents (Settings), and one document's own.

The models are the ones in config/models.yaml; a reasoning level only for those with `thinking: true`. No URLs,
keys or headers ever leave the server."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import app_settings, references
from ...document import versions
from ...integrations import dictionary
from ...models import catalog, routing
from ...models import config as model_config
from ...models.config import (
    CONFIG_ONLY_STEPS,
    EFFORTS,
    STEP_GROUPS,
    STEP_HELP,
    STEP_LABELS,
    VISION_STEPS,
    ChoiceError,
    Effort,
    Step,
)
from ...ocr import second
from ..services import editable_session, session_service

router = APIRouter()


class ChoiceIn(BaseModel):
    model: str
    effort: Effort | None = None  # None: the default level (config.default_effort), or a model that doesn't think


class SettingsIn(BaseModel):
    models: dict[Step, ChoiceIn | None] | None = None  # null for a step: back to the default
    dictionary: bool | None = None
    second_reader: bool | None = None  # a second model reads scanned pages and pictures too
    assist: bool | None = None  # suggested prompts and Tab completions in the chat (app-wide only)


def check_models(models: dict[str, Any]) -> dict[Step, dict]:
    """Validated choices ({step: {model, effort}}); a 422 naming each step that can't use its model."""
    cfg = model_config.current()
    errors, out = [], {}
    for step, choice in models.items():
        if choice is None:
            continue
        model, effort = (choice.model, choice.effort) if isinstance(choice, ChoiceIn) else (choice.get("model", ""), choice.get("effort"))
        if step in CONFIG_ONLY_STEPS:  # pipeline.yaml's: sending it back unchanged is fine, changing it isn't
            if {"model": model, "effort": effort} != routing.choices(None)[step]:
                errors.append({"loc": ["body", "models", step], "type": "value_error",
                               "msg": f"The model for {STEP_LABELS[step]} is set in config/pipeline.yaml, not in the app"})
            else:
                out[step] = {"model": model, "effort": effort}
            continue
        try:
            cfg.check_choice(step, model, effort)
        except ChoiceError as exc:
            errors.append({"loc": ["body", "models", step], "msg": str(exc), "type": "value_error"})
            continue
        out[step] = {"model": model, "effort": effort}
    if errors:
        raise HTTPException(422, errors)
    return out


def check_dictionary(on: bool | None) -> None:
    if on and not dictionary.configured():
        raise HTTPException(422, [{"loc": ["body", "dictionary"], "msg": references.NOT_CONFIGURED, "type": "value_error"}])


def check_second_reader(on: bool | None) -> None:
    if on and not second.available():
        raise HTTPException(422, [{"loc": ["body", "second_reader"], "msg": second.OFF_ON_SERVER, "type": "value_error"}])


def _steps() -> list[dict]:
    """The steps people choose models for, in the order they appear (the AI assist ones are pipeline.yaml's)."""
    return [{"step": step, "label": STEP_LABELS[step], "help": STEP_HELP[step], "group": g["id"],
             "vision": step in VISION_STEPS} for g in STEP_GROUPS for step in g["steps"]]


def _groups() -> list[dict]:
    return [{**g, "steps": list(g["steps"]), "vision": all(s in VISION_STEPS for s in g["steps"]),
             "distinct": bool(g.get("distinct"))} for g in STEP_GROUPS]


def _defaults(cfg: model_config.ModelConfig) -> dict[str, dict[str, dict]]:
    """{step: {model id: {"effort", "from"}}}: the level "Default" stands for, for each thinking model on each step."""
    out: dict[str, dict[str, dict]] = {}
    for step in (step for g in STEP_GROUPS for step in g["steps"]):
        for m in cfg.models.values():
            effort, origin = cfg.default_effort(step, m.id)
            if effort is not None:
                out.setdefault(step, {})[m.id] = {"effort": effort, "from": origin}
    return out


def settings_view() -> dict[str, Any]:
    saved = app_settings.load()
    cfg = model_config.current()
    choices = routing.choices(None)
    return {
        "models": choices,
        "configured": {step: {"model": m.id, "effort": cfg.specs[step].effort} for step, m in cfg.steps.items()},  # pipeline.yaml
        "defaults": _defaults(cfg),
        "flow": catalog.flow(),
        "overridden": list(saved.models),
        "assist": saved.assist,
        "dictionary": references.dictionary_status(None),
        "second_reader": second.status(None, choices),
        "steps": _steps(),
        "groups": _groups(),
        "efforts": list(EFFORTS),
    }


def document_settings(state) -> dict[str, Any]:
    choices = routing.choices(state)
    return {"models": choices, "dictionary": references.dictionary_status(state),
            "second_reader": second.status(state, choices)}


@router.get("/api/models")
def models() -> list[dict[str, Any]]:
    """The models people can choose (never their URLs, keys or headers)."""
    return [catalog.describe(m) for m in model_config.current().models.values()]


@router.get("/api/settings")
def get_app_settings() -> dict[str, Any]:
    return settings_view()


@router.put("/api/settings")
def put_app_settings(body: SettingsIn) -> dict[str, Any]:
    """The defaults for new documents. Documents already uploaded keep their own choices."""
    saved = app_settings.load()
    models = {k: v.model_dump() for k, v in saved.models.items()}
    if body.models is not None:
        chosen = check_models({k: v for k, v in body.models.items() if v is not None})
        for step, choice in body.models.items():
            if choice is None:
                models.pop(step, None)
            else:
                models[step] = chosen[step]
    check_dictionary(body.dictionary)
    check_second_reader(body.second_reader)
    app_settings.save(app_settings.AppSettings(
        models=app_settings.valid_models(models),
        dictionary=saved.dictionary if body.dictionary is None else body.dictionary,
        second_reader=saved.second_reader if body.second_reader is None else body.second_reader,
        assist=saved.assist if body.assist is None else body.assist,
    ))
    return settings_view()


def _describe(step: Step, choice: dict) -> str:
    effort = f" ({choice['effort']})" if choice.get("effort") else ""
    return f"{STEP_LABELS[step]} → {choice['model']}{effort}"


@router.patch("/api/sessions/{session_id}/settings")
async def patch_document_settings(session_id: str, body: SettingsIn) -> dict[str, Any]:
    """This document's models, dictionary and second reading, from its next run (not while the agents are working on it)."""
    session = await editable_session(session_id)
    delta: dict[str, Any] = {}
    changes: list[str] = []
    if body.models is not None:
        chosen = check_models({k: v for k, v in body.models.items() if v is not None})
        mine = dict(routing.choices(session.state))
        defaults = routing.choices(None)
        for step, choice in body.models.items():
            new = chosen[step] if choice is not None else defaults[step]
            if new != mine.get(step):
                changes.append(_describe(step, new))
            mine[step] = new
        delta[routing.DOC_MODELS] = mine
    if body.dictionary is not None:
        check_dictionary(body.dictionary)
        if body.dictionary != references.dictionary_on(session.state):
            changes.append(f"dictionary {'on' if body.dictionary else 'off'}")
        delta[references.DOC_DICTIONARY] = body.dictionary
    if body.second_reader is not None:
        check_second_reader(body.second_reader)
        if body.second_reader != second.enabled(session.state):
            changes.append(f"second reading {'on' if body.second_reader else 'off'}")
        delta[second.DOC_KEY] = body.second_reader
    if delta:
        text = ("Settings for this document: " + "; ".join(changes) + " (from the next run)") if changes else "Settings saved"
        await session_service.append_event(session, versions.activity_event(text, delta))
    return document_settings({**session.state, **delta})

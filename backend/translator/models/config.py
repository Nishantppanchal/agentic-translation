"""Which models the pipeline uses.

`config/models.yaml` lists the models: any OpenAI-compatible chat-completions server (vLLM, SGLang, OpenRouter,
…), each with an `id`, the `model_name` the server knows it by, its `url`, and optionally an `api_key`, `headers`
and `extra_body`. `config/pipeline.yaml` says which model (by id) does each step. `${NAME}` in either file is the
environment variable NAME (`backend/.env` is loaded into the environment), `${NAME:-}` one that may be unset.

Headers reach every model request from three places, later ones winning: `defaults.headers` (all models), the
model's own `headers`, and the headers of the run that makes the call — `defaults.forward_headers` copies the
named headers of the API request that started a run, and code can add more with `llm.request_headers(...)`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import get_settings

Step = Literal["ocr", "ocr_check", "analyse", "translate", "review", "refine", "polish", "rewrite", "editor", "lqa"]
STEPS: tuple[Step, ...] = get_args(Step)
STEP_LABELS: dict[Step, str] = {
    "ocr": "OCR",  # reads each page image, the text inside pictures, and pages read again in the source check
    "ocr_check": "OCR check",
    "analyse": "Analysis",
    "translate": "Translation",
    "review": "Review",
    "refine": "Refinement",
    "polish": "Consistency",  # the polish step before Ready, and the consistency task
    "rewrite": "Rewrite",  # tasks: rewrite with an instruction, alternatives
    "editor": "Chat editor",
    "lqa": "LQA",
}


class ConfigError(ValueError):
    """models.yaml or pipeline.yaml is wrong: says which file and what."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Defaults(_Strict):
    headers: dict[str, str] = Field(default_factory=dict, repr=False)
    forward_headers: list[str] = Field(default_factory=list)
    timeout: float = 180.0  # seconds per call; a stalled connection is retried instead of blocking a document
    retries: int = 5  # per call, on rate limits (exponential backoff) and API errors
    temperature: float = 0.2


class ModelSpec(_Strict):
    id: str
    model_name: str
    url: str
    api_key: str | None = Field(None, repr=False)
    headers: dict[str, str] = Field(default_factory=dict, repr=False)
    extra_body: dict[str, Any] = Field(default_factory=dict)
    timeout: float | None = None
    retries: int | None = None
    temperature: float | None = None
    # JSON-schema output for the translator, reviewer and refiner (vLLM and most hosted APIs support it);
    # false: they answer in a tag format instead.
    structured_output: bool = True


class ModelsFile(_Strict):
    defaults: Defaults = Field(default_factory=Defaults)
    models: list[ModelSpec]


class StepSpec(_Strict):
    model: str
    extra_body: dict[str, Any] = Field(default_factory=dict)  # added to the model's, e.g. a thinking budget
    temperature: float | None = None


class PipelineFile(_Strict):
    default: str | None = None  # the model for every step not listed
    steps: dict[Step, str | StepSpec] = Field(default_factory=dict)


@dataclass(frozen=True)
class StepModel:
    """Everything one step needs to call its model."""

    step: Step
    id: str
    model_name: str
    url: str
    api_key: str | None
    headers: dict[str, str]
    extra_body: dict[str, Any]
    timeout: float
    retries: int
    temperature: float
    structured_output: bool

    def __repr__(self) -> str:  # never the key or header values (they may hold credentials)
        return f"StepModel({self.step}: {self.id} = {self.model_name} at {self.url})"


@dataclass(frozen=True)
class ModelConfig:
    steps: dict[Step, StepModel]
    forward_headers: tuple[str, ...]

    def step(self, step: Step) -> StepModel:
        return self.steps[step]


_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}")


def _expand(value: Any, file: Path) -> Any:
    """`${NAME}` → the environment variable (an error if unset); `${NAME:-default}` → it or the default."""
    if isinstance(value, dict):
        return {k: _expand(v, file) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, file) for v in value]
    if not isinstance(value, str):
        return value

    def sub(m: re.Match) -> str:
        found = os.environ.get(m.group(1))
        if found is not None:
            return found
        if m.group(2) is not None:
            return m.group(3)
        raise ConfigError(f"{file}: {m.group(1)} is not set (put it in backend/.env, or write ${{{m.group(1)}:-}})")

    return _VAR.sub(sub, value)


def _read(file: Path, schema: type[BaseModel]) -> BaseModel:
    try:
        raw = yaml.safe_load(file.read_text()) or {}
    except FileNotFoundError:
        example = file.with_name(f"{file.stem}.example{file.suffix}")
        hint = f": copy {example.name} to {file.name} and edit it" if example.exists() else ""
        raise ConfigError(f"{file} not found{hint}") from None
    except yaml.YAMLError as e:
        raise ConfigError(f"{file}: {e}") from None
    try:
        return schema.model_validate(_expand(raw, file))
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors(include_input=False))
        raise ConfigError(f"{file}: {problems}") from None


def build(models: ModelsFile, pipeline: PipelineFile, where: str = "pipeline.yaml") -> ModelConfig:
    by_id: dict[str, ModelSpec] = {}
    for m in models.models:
        if m.id in by_id:
            raise ConfigError(f"models.yaml: two models have the id {m.id!r}")
        by_id[m.id] = m
    d = models.defaults
    steps: dict[Step, StepModel] = {}
    for step in STEPS:
        spec = pipeline.steps.get(step, pipeline.default)
        if spec is None:
            raise ConfigError(f"{where}: no model for the step {step!r} (list it under steps, or set default)")
        spec = StepSpec(model=spec) if isinstance(spec, str) else spec
        m = by_id.get(spec.model)
        if m is None:
            raise ConfigError(f"{where}: step {step!r} uses {spec.model!r}, which is not an id in models.yaml "
                              f"({', '.join(by_id) or 'none'})")
        steps[step] = StepModel(
            step=step, id=m.id, model_name=m.model_name, url=m.url, api_key=m.api_key or None,
            headers={**d.headers, **m.headers}, extra_body={**m.extra_body, **spec.extra_body},
            timeout=m.timeout if m.timeout is not None else d.timeout,
            retries=m.retries if m.retries is not None else d.retries,
            temperature=next(t for t in (spec.temperature, m.temperature, d.temperature) if t is not None),
            structured_output=m.structured_output,
        )
    return ModelConfig(steps=steps, forward_headers=tuple(d.forward_headers))


def load(models_file: Path, pipeline_file: Path) -> ModelConfig:
    return build(_read(models_file, ModelsFile), _read(pipeline_file, PipelineFile), where=str(pipeline_file))


@lru_cache
def current() -> ModelConfig:
    s = get_settings()
    return load(Path(s.models_file), Path(s.pipeline_file))


def step_model(step: Step) -> StepModel:
    return current().step(step)

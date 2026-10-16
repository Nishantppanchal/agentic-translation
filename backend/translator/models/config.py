"""Which models the pipeline uses.

`config/models.yaml` lists the models: any OpenAI-compatible chat-completions server (vLLM, SGLang, OpenRouter,
…), each with an `id`, the `model_name` the server knows it by, its `url`, and optionally an `api_key`, `headers`
and `extra_body`. `config/pipeline.yaml` says which model (by id) does each step. `${NAME}` in either file is the
environment variable NAME (`backend/.env` is loaded into the environment), `${NAME:-}` one that may be unset.

Headers reach every model request from three places, later ones winning: `defaults.headers` (all models), the
model's own `headers`, and the headers of the run that makes the call — `defaults.forward_headers` copies the
named headers of the API request that started a run, and code can add more with `llm.request_headers(...)`.

pipeline.yaml gives the defaults. People can choose other models (and a reasoning level for models with
`thinking: true`) in the app — for all new documents (Settings) or one document — see models/routing.py.
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

Step = Literal["ocr", "ocr_check", "analyse", "translate", "review", "refine", "polish", "rewrite", "editor", "lqa",
               "suggest", "complete", "notes"]
STEPS: tuple[Step, ...] = get_args(Step)
# Steps that look at page images: their model must read images (`vision: true` in models.yaml).
VISION_STEPS: tuple[Step, ...] = ("ocr", "ocr_check", "editor")
# How hard a model with `thinking: true` reasons, sent as the standard `reasoning_effort` (instant = "none": no
# thinking; vLLM turns it into enable_thinking=false). A thinking model always gets one: the choice made in the
# app, else the step's `effort` in pipeline.yaml (when the step uses that model), else the model's own `effort`
# in models.yaml, else DEFAULT_EFFORT (OpenAI's documented default for reasoning_effort).
Effort = Literal["instant", "low", "medium", "high"]
EFFORTS: tuple[Effort, ...] = get_args(Effort)
DEFAULT_EFFORT: Effort = "medium"
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
    "suggest": "Suggestions",  # the suggested follow-up prompts in the chat
    "complete": "Tab completion",  # the rest of a chat message being typed (keep it fast)
    "notes": "Translation summary",  # the summary for the client: decisions, assumptions, open queries
}


# The steps as people choose models for them (Settings): one model per group, or per step under Advanced.
STEP_GROUPS: tuple[dict[str, Any], ...] = (
    {"id": "reading", "label": "Reading", "help": "Reads each page (OCR) and checks the reading", "steps": ("ocr", "ocr_check")},
    {"id": "translating", "label": "Translating", "help": "Analysis, translation, fixes and rewrites",
     "steps": ("analyse", "translate", "refine", "polish", "rewrite")},
    {"id": "reviewing", "label": "Reviewing", "help": "The AI review and the quality score (LQA)", "steps": ("review", "lqa")},
    {"id": "chat", "label": "Chat", "help": "The chat editor (it looks at pages too)", "steps": ("editor",)},
    {"id": "assist", "label": "AI assist", "help": "Suggested prompts, Tab completions and the translation summary",
     "steps": ("suggest", "complete", "notes")},
)


class ConfigError(ValueError):
    """models.yaml or pipeline.yaml is wrong: says which file and what."""


class ChoiceError(ValueError):
    """A model chosen in the app can't do that step (unknown, can't read images, or doesn't think)."""


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
    vision: bool = False  # reads images: needed for the steps that look at pages (VISION_STEPS)
    thinking: bool = False  # a reasoning model: offers Instant / Low / Medium / High (sent as `reasoning_effort`)
    effort: Effort | None = None  # its default level (thinking models only); unset: DEFAULT_EFFORT
    label: str | None = None  # the name people see ("Claude Haiku 5.5"); unset: made from model_name
    vendor: str | None = None  # whose model it is, for its logo (anthropic, qwen, openai, …); unset: from model_name
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
    effort: Effort | None = None  # reasoning level, for a model with `thinking: true`


class PipelineFile(_Strict):
    default: str | StepSpec | None = None  # the model for every step not listed
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
    temperature: float | None  # None: not sent (a reasoning model at Low/Medium/High uses its own)
    structured_output: bool
    vision: bool
    thinking: bool = False
    effort: Effort | None = None

    def __repr__(self) -> str:  # never the key or header values (they may hold credentials)
        return f"StepModel({self.step}: {self.id} = {self.model_name} at {self.url})"


@dataclass(frozen=True)
class ModelConfig:
    steps: dict[Step, StepModel]  # pipeline.yaml's choices
    forward_headers: tuple[str, ...]
    models: dict[str, ModelSpec]
    defaults: Defaults
    specs: dict[Step, StepSpec]  # pipeline.yaml's entry for each step

    def step(self, step: Step) -> StepModel:
        return self.steps[step]

    def check_choice(self, step: Step, model_id: str, effort: str | None = None) -> ModelSpec:
        """The model, if it can do this step at this reasoning level; ChoiceError (saying why) if not."""
        m = self.models.get(model_id)
        if m is None:
            raise ChoiceError(f"{model_id!r} is not a model in models.yaml ({', '.join(self.models)})")
        if step in VISION_STEPS and not m.vision:
            raise ChoiceError(f"{STEP_LABELS[step]} looks at page images, and {model_id!r} doesn't read images")
        if effort is not None and effort not in EFFORTS:
            raise ChoiceError(f"unknown reasoning level {effort!r} (one of {', '.join(EFFORTS)})")
        if effort is not None and not m.thinking:
            raise ChoiceError(f"{model_id!r} doesn't think (no `thinking: true` in models.yaml), so it has no reasoning level")
        return m

    def default_effort(self, step: Step, model_id: str) -> tuple[Effort | None, str | None]:
        """The level a thinking model gets on this step when nobody chose one, and where it comes from
        ("pipeline.yaml", "models.yaml" or "built-in"); (None, None) for a model that doesn't think."""
        m = self.models.get(model_id)
        if m is None or not m.thinking:
            return None, None
        spec = self.specs.get(step)
        if spec is not None and spec.model == model_id and spec.effort is not None:
            return spec.effort, "pipeline.yaml"
        if m.effort is not None:
            return m.effort, "models.yaml"
        return DEFAULT_EFFORT, "built-in"

    def choose(self, step: Step, model_id: str, effort: str | None = None) -> StepModel:
        """The step on this model: pipeline.yaml's own settings for the step (extra_body, temperature) only apply
        when it is the step's pipeline.yaml model. No level chosen: the default one (`default_effort`)."""
        m = self.check_choice(step, model_id, effort)
        spec = self.specs[step]
        own = spec if spec.model == model_id else StepSpec(model=model_id)
        return _step_model(step, m, self.defaults, own, effort if effort is not None else self.default_effort(step, model_id)[0])


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


def _step_model(step: Step, m: ModelSpec, d: Defaults, spec: StepSpec, effort: str | None) -> StepModel:
    thinks = bool(m.thinking and effort and effort != "instant")
    # A reasoning model at Low/Medium/High: the default temperature isn't sent (some providers refuse one with
    # reasoning on); a temperature set on the step or the model still is.
    temperature = next((t for t in (spec.temperature, m.temperature) if t is not None), None if thinks else d.temperature)
    return StepModel(
        step=step, id=m.id, model_name=m.model_name, url=m.url, api_key=m.api_key or None,
        headers={**d.headers, **m.headers}, extra_body={**m.extra_body, **spec.extra_body},
        timeout=m.timeout if m.timeout is not None else d.timeout,
        retries=m.retries if m.retries is not None else d.retries,
        temperature=temperature, structured_output=m.structured_output, vision=m.vision,
        thinking=m.thinking, effort=effort if m.thinking else None,
    )


def build(models: ModelsFile, pipeline: PipelineFile, where: str = "pipeline.yaml") -> ModelConfig:
    by_id: dict[str, ModelSpec] = {}
    for m in models.models:
        if m.id in by_id:
            raise ConfigError(f"models.yaml: two models have the id {m.id!r}")
        by_id[m.id] = m
        if m.effort is not None and not m.thinking:
            raise ConfigError(f"models.yaml: {m.id!r} sets effort {m.effort!r} but is not marked `thinking: true`")
    d = models.defaults
    steps: dict[Step, StepModel] = {}
    specs: dict[Step, StepSpec] = {}
    for step in STEPS:
        spec = pipeline.steps.get(step, pipeline.default)
        if spec is None:
            raise ConfigError(f"{where}: no model for the step {step!r} (list it under steps, or set default)")
        spec = StepSpec(model=spec) if isinstance(spec, str) else spec
        m = by_id.get(spec.model)
        if m is None:
            raise ConfigError(f"{where}: step {step!r} uses {spec.model!r}, which is not an id in models.yaml "
                              f"({', '.join(by_id) or 'none'})")
        if step in VISION_STEPS and not m.vision:
            raise ConfigError(f"{where}: step {step!r} looks at page images, so it needs a vision model, but {m.id!r} "
                              "is not marked `vision: true` in models.yaml")
        if spec.effort is not None and not m.thinking:
            raise ConfigError(f"{where}: step {step!r} sets effort {spec.effort!r}, but {m.id!r} is not marked "
                              "`thinking: true` in models.yaml")
        specs[step] = spec
        effort = spec.effort if spec.effort is not None else (m.effort or DEFAULT_EFFORT) if m.thinking else None
        steps[step] = _step_model(step, m, d, spec, effort)
    return ModelConfig(steps=steps, forward_headers=tuple(d.forward_headers), models=by_id, defaults=d, specs=specs)


def load(models_file: Path, pipeline_file: Path) -> ModelConfig:
    return build(_read(models_file, ModelsFile), _read(pipeline_file, PipelineFile), where=str(pipeline_file))


@lru_cache
def current() -> ModelConfig:
    s = get_settings()
    return load(Path(s.models_file), Path(s.pipeline_file))


def step_model(step: Step) -> StepModel:
    return current().step(step)

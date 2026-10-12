"""Runtime configuration, loaded from environment variables / `.env`.

Every agent role calls a model endpoint directly: an OpenAI-compatible server such as vLLM, with its URL,
served model name, API key, extra HTTP headers and extra request fields. Each role can use its own endpoint.
Without an API base, MODEL is a LiteLLM provider model (`anthropic/<name>`, `gemini/<name>`, ...), and a bare
`gemini-*` name uses ADK's native Gemini client.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, NamedTuple

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The tests set TRANSLATOR_ENV_FILE= (empty) so a developer's .env never reaches them.
ENV_FILE = os.environ.get("TRANSLATOR_ENV_FILE", ".env") or None

# Settings below read .env themselves, but hosted-provider keys (ANTHROPIC_API_KEY, GEMINI_API_KEY, ...) are
# read by LiteLLM from the process environment, so export .env there too.
if ENV_FILE:
    load_dotenv(ENV_FILE, override=False)

Role = Literal["ocr", "ocr_check", "translate", "review", "editor", "lqa"]
ROLES: tuple[Role, ...] = ("ocr", "ocr_check", "translate", "review", "editor", "lqa")

TARGET_LANG = "English"  # every document is translated into English

# JSON objects in the environment: HTTP headers (string values) and extra request fields (any JSON).
# They may hold credentials, so they're kept out of the settings' repr and out of validation errors.
Headers = Annotated[dict[str, str] | None, NoDecode, Field(repr=False)]
ExtraBody = Annotated[dict | None, NoDecode, Field(repr=False)]
Secret = Annotated[str | None, Field(repr=False)]


class Endpoint(NamedTuple):
    """Where and how one role calls its model."""

    model: str  # the served model name (with an API base), else a LiteLLM provider model
    api_base: str | None
    api_key: str | None
    headers: dict[str, str]
    extra_body: dict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore", hide_input_in_errors=True)

    # Default endpoint used by every role unless overridden below: a vLLM server (`vllm serve <model> --port 8100`;
    # the backend itself uses port 8000). MODEL is the served model name, as GET <api base>/models lists it.
    model: str = "Qwen/Qwen3-VL-8B-Instruct"
    model_api_base: str | None = "http://localhost:8100/v1"
    model_api_key: Secret = None  # vLLM's --api-key; sent as "Authorization: Bearer …"
    model_headers: Headers = None  # extra HTTP headers on every request (JSON), e.g. a gateway token
    model_extra_body: ExtraBody = None  # extra request fields the server accepts (JSON), e.g. chat_template_kwargs

    # OCR: the vision LLM that reads pages (OCR_MODEL, inherits MODEL_* like the other roles).
    ocr_model: str | None = None
    ocr_api_base: str | None = None
    ocr_api_key: Secret = None
    ocr_headers: Headers = None
    ocr_extra_body: ExtraBody = None
    ocr_check_model: str | None = None
    ocr_check_api_base: str | None = None
    ocr_check_api_key: Secret = None
    ocr_check_headers: Headers = None
    ocr_check_extra_body: ExtraBody = None
    translate_model: str | None = None
    translate_api_base: str | None = None
    translate_api_key: Secret = None
    translate_headers: Headers = None
    translate_extra_body: ExtraBody = None
    review_model: str | None = None
    review_api_base: str | None = None
    review_api_key: Secret = None
    review_headers: Headers = None
    review_extra_body: ExtraBody = None
    editor_model: str | None = None
    editor_api_base: str | None = None
    editor_api_key: Secret = None
    editor_headers: Headers = None
    editor_extra_body: ExtraBody = None
    # Independent LQA (quality scoring). Unset → the review endpoint; set it to get a second opinion.
    lqa_model: str | None = None
    lqa_api_base: str | None = None
    lqa_api_key: Secret = None
    lqa_headers: Headers = None
    lqa_extra_body: ExtraBody = None

    # Pipeline knobs.
    ocr_dpi: int = 150
    # The OCR check: the OCR_CHECK model compares the reading with the page; its word fixes are applied only when
    # small or confirmed by the PDF's text layer — larger ones are listed, not applied.
    ocr_check_enabled: bool = True
    # auto: the PDF's embedded images, plus the pictures, charts and seals PP-DocLayoutV3 finds (layout server) · off
    figure_detection: Literal["auto", "off"] = "auto"
    figure_text: bool = True  # read the text inside figures and translate it as a legend

    # The layout MCP server (../layout-server): PP-DocLayoutV3 finds the pictures on pages, and the chat editor
    # inspects page layouts with it. Blank LAYOUT_SERVER_DIR: figures come from the PDF's embedded images only.
    layout_server_dir: str = "../layout-server"
    layout_model: str = "PP-DocLayoutV3"
    # Where the model files are: a folder of model folders by name, like PaddleX's ~/.paddlex/official_models
    # (PP-DocLayoutV3/, ...), or the layout model's own
    # folder (inference.yml, inference.json, inference.pdiparams). Blank: PaddleX downloads them to its cache.
    layout_model_dir: str = ""
    layout_threshold: float = 0.5
    layout_timeout: float = 300.0  # seconds; first call loads (and may download) the model

    # A dictionary service (any HTTP endpoint answering the contract in dictionary-server/README.md): key terms
    # are looked up during the analysis and shown with the questions; the editor can look terms up. Blank = off.
    dictionary_url: str = ""
    dictionary_api_key: Secret = None  # sent as "Authorization: Bearer …"
    dictionary_headers: Headers = None
    dictionary_timeout: float = 15.0
    page_max_chars: int = 6000  # pages longer than this are translated in parts
    carry_context_chars: int = 1500  # previous source+translation carried into each page
    review_max_rounds: int = 2
    max_questions_per_batch: int = 3
    # Whole-document analysis before translating: brief + key terms; ambiguous ones are asked up front.
    analysis_enabled: bool = True
    analysis_max_terms: int = 25
    max_questions: int = 6  # questions asked before translating
    analysis_chunk_chars: int = 40000  # longer documents are analysed in parts
    # OCR check: auto = skip the second vision call when the transcription is the same text as the PDF's
    # own text layer (after normalising markdown and spacing) on a page without pictures; always = check
    # every page. OCR_CHECK_AGREEMENT below 100 also skips near matches — a misread word scores ~98.
    ocr_check: Literal["auto", "always"] = "auto"
    ocr_check_agreement: float = 100.0
    # JSON-schema output for translator/reviewer/refiner: auto = when the model supports it, else tags.
    structured_output: Literal["auto", "on", "off"] = "auto"
    max_concurrency: int = 2  # model calls at once within one run
    max_parallel_runs: int = 2  # pipelines/tasks running at once across documents (more are queued)
    temperature: float = 0.2
    model_retries: int = 5  # per model call, on rate limits (exponential backoff) and API errors
    model_timeout: float = 180.0  # seconds per model call; a stalled connection is retried, not waited on
    # Reasoning models otherwise think for minutes per review call: cap the hidden thinking of the reviewer and
    # LQA on vLLM (`thinking_token_budget`; the server needs --reasoning-parser — one without it gets the call
    # again uncapped). 0 = no cap.
    review_reasoning_tokens: int = 2000

    # Storage + server.
    data_dir: Path = Path("data")
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    user_id: str = "local"

    @field_validator(*(f"{p}_{k}" for p in ("model", *ROLES) for k in ("headers", "extra_body")), "dictionary_headers",
                     mode="before")
    @classmethod
    def _json_object(cls, value):
        """`{"X-Token": "…"}` from the environment; empty means none (it still stops a role inheriting)."""
        if isinstance(value, str):
            value = json.loads(value) if value.strip() else {}
            if not isinstance(value, dict):
                raise ValueError("must be a JSON object")
        return value

    def endpoint(self, role: Role) -> Endpoint:
        """A role's endpoint. Each setting the role leaves unset is inherited from MODEL_*; set it empty
        (`REVIEW_API_BASE=`, `REVIEW_HEADERS={}`) to stop inheriting, e.g. for a second server that needs no
        gateway headers."""
        if role == "lqa" and not self.lqa_model:
            return self.endpoint("review")

        def pick(field: str):
            own = getattr(self, f"{role}_{field}")
            return getattr(self, f"model_{field}") if own is None else own

        return Endpoint(
            model=getattr(self, f"{role}_model") or self.model,
            api_base=pick("api_base") or None,
            api_key=pick("api_key") or None,
            headers=dict(pick("headers") or {}),
            extra_body=dict(pick("extra_body") or {}),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Runtime configuration, loaded from environment variables / `.env`.

Every agent role can use a different model. Model strings use LiteLLM naming
(`openai/<name>`, `anthropic/<name>`, `gemini/<name>`, `ollama_chat/<name>`, ...).
A bare `gemini-*` name with no API base uses ADK's native Gemini client.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Settings below read .env themselves, but provider keys (OPENROUTER_API_KEY, ANTHROPIC_API_KEY,
# GEMINI_API_KEY, ...) are read by LiteLLM from the process environment, so export .env there too.
load_dotenv(".env", override=False)

Role = Literal["ocr", "ocr_check", "translate", "review", "editor", "lqa"]

TARGET_LANG = "English"  # every document is translated into English


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Default model + endpoint used by every role unless overridden below.
    model: str = "openai/gemma4"
    model_api_base: str | None = "http://localhost:11434/v1"
    model_api_key: str | None = "ollama"

    # Per-role overrides (e.g. OCR_MODEL=gemini/gemini-2.5-flash, OCR_API_BASE=).
    ocr_model: str | None = None
    ocr_api_base: str | None = None
    ocr_api_key: str | None = None
    ocr_check_model: str | None = None
    ocr_check_api_base: str | None = None
    ocr_check_api_key: str | None = None
    translate_model: str | None = None
    translate_api_base: str | None = None
    translate_api_key: str | None = None
    review_model: str | None = None
    review_api_base: str | None = None
    review_api_key: str | None = None
    editor_model: str | None = None
    editor_api_base: str | None = None
    editor_api_key: str | None = None
    # Independent LQA (quality scoring). Unset → the review model; set it to get a second opinion.
    lqa_model: str | None = None
    lqa_api_base: str | None = None
    lqa_api_key: str | None = None

    # Pipeline knobs.
    ocr_dpi: int = 150
    ocr_check_enabled: bool = True
    # auto:   PDF images + PP-DocLayout (if the layout server is available), else vision-LLM boxes on scans
    # layout: PDF images + PP-DocLayout only · vision: PDF images + vision-LLM boxes on scans
    # pdf:    embedded PDF images only · off
    figure_detection: Literal["auto", "layout", "vision", "pdf", "off"] = "auto"
    figure_text: bool = True  # read text inside figures (translated as a legend)

    # PP-DocLayout MCP server (../layout-server); blank LAYOUT_SERVER_DIR disables it.
    layout_server_dir: str = "../layout-server"
    layout_model: str = "PP-DocLayout_plus-L"  # or PP-DocLayoutV3, PP-DocLayout-L/M/S
    layout_threshold: float = 0.5
    layout_timeout: float = 300.0  # seconds; first call loads (and may download) the model
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
    model_timeout: float = 180.0  # seconds per model call; a stalled provider connection is retried, not waited on
    # Reasoning models (e.g. Qwen 3.8 Flash) otherwise think for minutes per review call: cap their hidden reasoning
    # for the reviewer and LQA (OpenRouter models that support it). 0 = no cap.
    review_reasoning_tokens: int = 2000

    # Storage + server.
    data_dir: Path = Path("data")
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    user_id: str = "local"

    def role_model(self, role: Role) -> tuple[str, str | None, str | None]:
        """Return (model, api_base, api_key) for a role, falling back to defaults."""
        if role == "lqa" and not self.lqa_model:
            return self.role_model("review")
        model = getattr(self, f"{role}_model") or self.model
        api_base = getattr(self, f"{role}_api_base")
        api_key = getattr(self, f"{role}_api_key")
        # Unset → inherit the default endpoint. Set to "" to disable inheritance
        # (e.g. OCR on hosted Gemini while everything else runs on Ollama).
        if api_base is None:
            api_base = self.model_api_base
        if api_key is None:
            api_key = self.model_api_key
        return model, api_base or None, api_key or None


@lru_cache
def get_settings() -> Settings:
    return Settings()

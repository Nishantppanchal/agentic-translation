"""Runtime settings, from environment variables / `.env`.

Models are configured in YAML, not here: `config/models.yaml` (the models) and `config/pipeline.yaml` (which
model does each step) — see models/config.py. `.env` holds their secrets (referenced as `${NAME}`) and the
pipeline knobs below.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The tests set TRANSLATOR_ENV_FILE= (empty) so a developer's .env never reaches them.
ENV_FILE = os.environ.get("TRANSLATOR_ENV_FILE", ".env") or None

# The YAML model files read secrets from the process environment (`${OPENROUTER_API_KEY}`): export .env there.
if ENV_FILE:
    load_dotenv(ENV_FILE, override=False)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
TARGET_LANG = "English"  # every document is translated into English

# A JSON object in the environment (HTTP headers). It may hold credentials: kept out of repr and errors.
Headers = Annotated[dict[str, str] | None, NoDecode, Field(repr=False)]
Secret = Annotated[str | None, Field(repr=False)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore", hide_input_in_errors=True)

    models_file: Path = CONFIG_DIR / "models.yaml"
    pipeline_file: Path = CONFIG_DIR / "pipeline.yaml"

    # Pipeline knobs.
    ocr_dpi: int = 150
    # The OCR check: the OCR_CHECK model compares the reading with the page; its word fixes are applied only when
    # small or confirmed by the PDF's text layer — larger ones are listed, not applied.
    ocr_check_enabled: bool = True
    # auto: the PDF's embedded images, plus the pictures, charts and seals PP-DocLayoutV3 finds (layout server) · off
    figure_detection: Literal["auto", "off"] = "auto"
    figure_text: bool = True  # read the text inside figures and translate it as a legend
    # auto: before a region becomes a figure, the OCR model looks at it and says picture or text (a block of text
    # the layout model took for a picture is then transcribed as text) · off: trust the layout model (and the
    # size / text-layer checks in ocr/figures.py)
    figure_check: Literal["auto", "off"] = "auto"
    figure_text_cover: float = 0.6  # text regions of the layout covering this much of a "picture": it's text
    # Pictures in Word, PowerPoint and Excel files: auto — the OCR model (if it reads images) reads the text in each
    # and it is translated (alt text, a caption in Word, the slide's notes in PowerPoint) · off — pictures are left alone
    office_pictures: Literal["auto", "off"] = "auto"
    office_picture_min_cm: float = 1.5  # smaller on their short side (icons, bullets): left alone
    office_picture_max: int = 60  # pictures read per file at most (the rest are listed as not translated)

    # The layout MCP server (../layout-server): PP-DocLayoutV3 finds the pictures on pages, and the chat editor
    # inspects page layouts with it. Blank LAYOUT_SERVER_DIR: figures come from the PDF's embedded images only.
    layout_server_dir: str = "../layout-server"
    layout_model: str = "PP-DocLayoutV3"
    # Where the model files are: a folder of model folders by name, like PaddleX's ~/.paddlex/official_models
    # (PP-DocLayoutV3/, ...), or the layout model's own
    # folder (inference.yml, inference.json, inference.pdiparams). Blank: PaddleX downloads them to its cache.
    layout_model_dir: str = ""
    # Minimum layout confidence: LAYOUT_THRESHOLD for every class, LAYOUT_THRESHOLDS (JSON) per class. Text regions
    # come in at a low bar (more of them = better evidence against a block of text read as a picture); pictures
    # need more.
    layout_threshold: float = 0.3
    layout_thresholds: Annotated[dict[str, float], NoDecode] = {"image": 0.55, "chart": 0.55, "seal": 0.45}
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
    max_concurrency: int = 2  # model calls at once within one run
    max_parallel_runs: int = 2  # pipelines/tasks running at once across documents (more are queued)

    # Storage + server.
    data_dir: Path = Path("data")
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    user_id: str = "local"

    @field_validator("layout_thresholds", mode="before")
    @classmethod
    def _thresholds(cls, value):
        """`{"image": 0.6}` from the environment; empty means the defaults for every class."""
        if isinstance(value, str):
            value = json.loads(value) if value.strip() else {}
        return value

    @field_validator("dictionary_headers", mode="before")
    @classmethod
    def _json_object(cls, value):
        """`{"X-Token": "…"}` from the environment; empty means none."""
        if isinstance(value, str):
            value = json.loads(value) if value.strip() else {}
            if not isinstance(value, dict):
                raise ValueError("must be a JSON object")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

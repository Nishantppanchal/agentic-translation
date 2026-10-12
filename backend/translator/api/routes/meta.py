"""What the app is set up with (models per step, languages, dictionary) and dictionary lookups."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ...config import TARGET_LANG
from ...integrations import dictionary
from ...languages import LANGUAGES
from ...models.config import STEPS
from ...models.llm import model_name

router = APIRouter()


@router.get("/api/config")
async def config() -> dict[str, Any]:
    return {"models": {step: model_name(step) for step in STEPS}, "languages": LANGUAGES, "target_lang": TARGET_LANG,
            "dictionary": dictionary.enabled()}


@router.get("/api/dictionary")
async def dictionary_lookup(term: str, lang: str = "") -> dict[str, Any]:
    """Look a term up in the dictionary service (DICTIONARY_URL); `lang` is the source language (name or code)."""
    if not dictionary.enabled():
        raise HTTPException(404, "No dictionary is set up (DICTIONARY_URL in backend/.env).")
    return {"term": term, "entries": (await dictionary.lookup([term], lang or None)).get(term, [])}

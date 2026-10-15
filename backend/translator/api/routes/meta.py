"""What the app is set up with (models per step, languages, dictionary) and dictionary lookups."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ...config import TARGET_LANG
from ...integrations import dictionary
from ...languages import LANGUAGES
from ...models import routing

router = APIRouter()


@router.get("/api/config")
async def config() -> dict[str, Any]:
    """Languages, and the models new documents use (choices: GET /api/settings)."""
    return {"models": {step: c["model"] for step, c in routing.choices(None).items()}, "languages": LANGUAGES,
            "target_lang": TARGET_LANG, "dictionary": dictionary.configured()}


@router.get("/api/dictionary")
async def dictionary_lookup(term: str, lang: str = "") -> dict[str, Any]:
    """Look a term up in the dictionary service (DICTIONARY_URL); `lang` is the source language (name or code)."""
    if not dictionary.configured():
        raise HTTPException(404, "No dictionary is set up (DICTIONARY_URL in backend/.env).")
    return {"term": term, "entries": (await dictionary.lookup([term], lang or None)).get(term, [])}

"""Term lookups in a dictionary service: any HTTP endpoint that answers this contract (DICTIONARY_URL).

    POST <url>   {"terms": ["réception avec réserves", "ASI"], "source_lang": "fr", "target_lang": "en"}
    200          {"results": {"réception avec réserves": [{"translation": "acceptance with reservations",
                  "definition": "…", "domain": "construction law", "source": "IATE", "url": "https://…"}],
                  "ASI": [...]}}

A term the dictionary doesn't know has an empty list (or is left out). DICTIONARY_API_KEY is sent as a Bearer
token, DICTIONARY_HEADERS as extra headers. `dictionary-server/` is a dummy implementation; put an adapter in front
of IATE, Wiktionary or a commercial API to use those. Lookups help but never block: a failing or slow service is
logged and the work goes on without it.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import TARGET_LANG, get_settings
from ..languages import lang_code
from ..models.llm import safe_url

log = logging.getLogger(__name__)

FIELDS = ("translation", "definition", "domain", "source", "url")
MAX_ENTRIES = 5  # per term
_cache: dict[tuple[str, str], list[dict]] = {}  # (language, term) → entries, for this process


def configured() -> bool:
    """A dictionary service is set up (DICTIONARY_URL). Whether a document uses it: references.dictionary_on."""
    return bool(get_settings().dictionary_url)


enabled = configured  # the older name


def _entry(raw: Any) -> dict | None:
    if not isinstance(raw, dict) or not str(raw.get("translation") or raw.get("definition") or "").strip():
        return None
    entry = {k: str(raw[k]).strip() for k in FIELDS if raw.get(k) not in (None, "")}
    if raw.get("term"):
        entry["term"] = str(raw["term"]).strip()
    return entry


async def lookup(terms: list[str], source_lang: str | None) -> dict[str, list[dict]]:
    """{term: entries} for the terms the dictionary knows. {} when no dictionary is set up or it fails."""
    settings = get_settings()
    if not settings.dictionary_url or not terms:
        return {}
    lang = lang_code(source_lang) if source_lang and not source_lang.startswith("auto") else ""
    lang = "" if lang == "und" else lang
    found = {t: _cache[(lang, t)] for t in terms if (lang, t) in _cache}
    missing = list(dict.fromkeys(t for t in terms if (lang, t) not in _cache))
    if missing:
        headers = dict(settings.dictionary_headers or {})
        if settings.dictionary_api_key:
            headers["Authorization"] = f"Bearer {settings.dictionary_api_key}"
        body = {"terms": missing, "source_lang": lang, "target_lang": lang_code(TARGET_LANG)}
        try:
            async with httpx.AsyncClient(timeout=settings.dictionary_timeout) as client:
                r = await client.post(settings.dictionary_url, json=body, headers=headers)
                r.raise_for_status()
                results = r.json().get("results") or {}
        except Exception as e:  # never block a run on the dictionary — but say what went wrong
            detail = f"HTTP {e.response.status_code}: {e.response.text[:300]}" if isinstance(e, httpx.HTTPStatusError) else f"{type(e).__name__}: {e}"
            log.warning("dictionary at %s failed: %s", safe_url(settings.dictionary_url), detail)
            return found
        for t in missing:
            entries = [e for e in (_entry(x) for x in (results.get(t) or [])) if e][:MAX_ENTRIES]
            _cache[(lang, t)] = entries
            found[t] = entries
    return {t: e for t, e in found.items() if e}

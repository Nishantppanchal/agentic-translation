"""Whether a document's scanned pages and pictures get a second reading (the `ocr_second` step, agents/steps/page.py).

On by default. The app's Settings (for new documents) and each document's own settings can turn it off, as with
the dictionary; OCR_SECOND=off in backend/.env turns it off on the server."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..config import get_settings

DOC_KEY = "doc:second_reader"  # True / False for this document; absent: the app's setting
OFF_ON_SERVER = "The second reading is turned off on the server (OCR_SECOND=off in backend/.env)."


def available() -> bool:
    return get_settings().ocr_second != "off"


def enabled(state: Mapping[str, Any] | None = None) -> bool:
    """This document's pages get a second reading (or, without a state, new documents' pages do)."""
    from .. import app_settings  # local: app_settings → projects → … → agents

    if not available():
        return False
    value = state.get(DOC_KEY) if state is not None else None
    return app_settings.load().second_reader if value is None else bool(value)


def warnings(choices: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """What's wrong with the reading models chosen ({step: {"model", …}}): the point of two readers and a judge is
    that they are different models, so they rarely make the same mistake."""
    first, second, check = (choices.get(s, {}).get("model") for s in ("ocr", "ocr_second", "ocr_check"))
    out = []
    if first and first == second:
        out.append("The second reading uses the same model as the first: they will tend to misread the same way. "
                   "Choose another company's model for Second reading.")
    if check and check in (first, second):
        out.append("The OCR check settles where the two readings differ, and it is one of the two readers: it will tend "
                   "to side with its own reading. Choose a third model for OCR check.")
    return out


def status(state: Mapping[str, Any] | None = None, choices: Mapping[str, Mapping[str, Any]] | None = None) -> dict:
    """{available, enabled, reason, warnings}: what the Settings and the document's settings show."""
    on = available()
    return {"available": on, "enabled": enabled(state), "reason": None if on else OFF_ON_SERVER,
            "warnings": warnings(choices or {}) if enabled(state) else []}

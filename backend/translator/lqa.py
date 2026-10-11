"""Language quality assessment (LQA) with MQM-style scoring.

Errors carry a category (accuracy, fluency, terminology, style, locale, markup) and a severity with
the MQM 2.0 penalty weights: minor 1, major 5, critical 25. The document score is

    score = 100 − penalty points per 1000 source words

(Chinese/Japanese/Thai: characters ÷ 2 count as words), and passes at the project's threshold
(default 90, i.e. at most 10 penalty points per 1000 words).
"""

from __future__ import annotations

import re

from .documents import NO_SPACE_CHARS
from .structured import CATEGORIES, SEVERITIES
from .text import plain

PENALTY = {"minor": 1, "major": 5, "critical": 25}
REFERENCE_WORDS = 1000
DEFAULT_THRESHOLD = 90.0

_NO_SPACE = re.compile(f"[{NO_SPACE_CHARS}]")
_WORD = re.compile(r"[^\W_]+(?:(?:['’-]|[.,](?=\d))[^\W_]+)*")  # "it's", "110-kV", "30.04.2026" are one word
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}.*$", re.M)


def word_count(text: str) -> float:
    """Source words, as translators count them (markup excluded; CJK characters ÷ 2)."""
    text = _TABLE_RULE.sub(" ", plain(text or "")).replace("|", " ")
    cjk = len(_NO_SPACE.findall(text))
    return len(_WORD.findall(_NO_SPACE.sub(" ", text))) + cjk / 2


def evaluated_words(segments: list[dict]) -> float:
    return sum(word_count(s["source"]) for s in segments if s.get("translatable", True) and s.get("target"))


def scorecard(issues: list[dict], words: float, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Category × severity counts, penalty points and the normalised score."""
    matrix = {c: {sev: 0 for sev in SEVERITIES} for c in [*CATEGORIES, "other"]}
    for i in issues:
        matrix[i.get("category") or "other"][i["severity"]] += 1
    if not any(matrix["other"].values()):
        del matrix["other"]
    penalty = sum(PENALTY[i["severity"]] for i in issues)
    score = max(0.0, 100 - penalty * REFERENCE_WORDS / words) if words else 100.0
    return {
        "words": round(words),
        "penalty": penalty,
        "score": round(score, 1),
        "threshold": threshold,
        "passed": score >= threshold,
        "counts": {sev: sum(i["severity"] == sev for i in issues) for sev in SEVERITIES},
        "matrix": matrix,
    }

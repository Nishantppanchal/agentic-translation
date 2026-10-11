"""Text matching shared by find/replace, the termbase and term highlighting.

Words are matched whole in scripts that separate words with spaces, and as plain substrings in
scripts that don't (Chinese, Japanese, Thai, …), where "word boundaries" never occur.
"""

from __future__ import annotations

import functools
import re

from .documents import NO_SPACE_CHARS

# A word character from a script that separates words with spaces (Latin, Cyrillic, digits, ...).
SPACED_WORD = rf"[^\W{NO_SPACE_CHARS}]"


@functools.lru_cache(maxsize=4096)
def term_pattern(term: str, case_sensitive: bool = False) -> re.Pattern:
    left = rf"(?<!{SPACED_WORD})" if re.fullmatch(SPACED_WORD, term[:1]) else ""
    right = rf"(?!{SPACED_WORD})" if re.fullmatch(SPACED_WORD, term[-1:]) else ""
    return re.compile(left + re.escape(term) + right, 0 if case_sensitive else re.IGNORECASE)


def contains_term(text: str, term: str, case_sensitive: bool = False) -> bool:
    return bool(term) and term_pattern(term, case_sensitive).search(text or "") is not None


_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+", re.M)
_BULLET = re.compile(r"^\s*[-*+]\s+", re.M)
_EMPHASIS = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")


_CODES = re.compile(r"""<g\s+id\s*=\s*["'][^"']+["']\s*>|</g\s*>|<x\s+id\s*=\s*["'][^"']+["']\s*/>""", re.I)


def plain(markdown: str) -> str:
    """Segment text → plain text for exchange files (TMX) and word counts: markdown markers and inline
    codes removed, where they would show literally."""
    return _EMPHASIS.sub(r"\2", _BULLET.sub("", _HEADING.sub("", _CODES.sub("", markdown or ""))))


def with_markup_of(source: str, target: str) -> str:
    """Give a plain TM translation the heading level of the segment it fills ("## Ergebnis" ← "Result")."""
    m = _HEADING.match(source or "")
    if m and not _HEADING.match(target or ""):
        return f"{m.group(1)} {target.strip()}"
    return target


def match_case(found: str, replacement: str) -> str:
    """Carry the matched text's capitalisation over to the replacement (Defects → Deficiencies)."""
    if found.isupper() and len(found) > 1:
        return replacement.upper()
    if found[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    first_word = replacement.split(" ", 1)[0]
    if found[:1].islower() and not any(c.isupper() for c in first_word[1:]):  # keep "BoQ", "LV", "iPhone"
        return replacement[:1].lower() + replacement[1:]
    return replacement

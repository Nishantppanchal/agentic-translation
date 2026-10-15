"""Text matching shared by find/replace, the termbase and term highlighting.

Words are matched whole in scripts that separate words with spaces, and as plain substrings in
scripts that don't (Chinese, Japanese, Thai, …), where "word boundaries" never occur.
"""

from __future__ import annotations

import functools
import re
import unicodedata

from .document.pages import NO_SPACE_CHARS

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




_OBJECT_MARK = re.compile(r"\[\^\d+\]")  # an object in a Word / PowerPoint sentence (office/markup.py)
_LINK_TEXT = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def plain(markdown: str) -> str:
    """Segment text → plain text for word counts and comparisons: the markdown markers removed."""
    text = _EMPHASIS.sub(r"\2", _BULLET.sub("", _HEADING.sub("", markdown or "")))
    return _LINK_TEXT.sub(r"\1", _OBJECT_MARK.sub("", text))


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


_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
_TABLE_SEP = re.compile(r"^:?-{2,}:?$")


def norm(text: str) -> str:
    """Letters and digits only, case-folded: for matching text whatever its spacing and punctuation."""
    return _NON_WORD.sub("", unicodedata.normalize("NFKC", text or "").casefold())


def markdown_grid(text: str) -> list[list[str]]:
    """The cells of a markdown pipe table, row by row (the separator row left out)."""
    rows = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if not raw.startswith("|"):
            continue
        cells = [c.strip() for c in raw.strip("|").split("|")]
        if all(_TABLE_SEP.match(c.replace(" ", "")) for c in cells if c):
            continue
        rows.append(cells)
    return rows

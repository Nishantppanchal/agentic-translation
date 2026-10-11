"""Find & replace across a document's translations (a person's tool; the chat editor has its own).

Preview first, then apply the chosen segments as human edits in one version. Locked segments are
never changed. Whole-word matching uses the same rules as the termbase: word boundaries in scripts
that separate words with spaces, plain substrings in Chinese, Japanese, Thai….
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from . import state as st
from .filters import inline
from .text import SPACED_WORD, match_case

Scope = Literal["all", "unconfirmed"]
MAX_PATTERN = 500


class ReplaceError(ValueError):
    """Bad search pattern."""


def compile_find(find: str, *, regex: bool = False, case: bool = False, whole_word: bool = False) -> re.Pattern:
    if not find:
        raise ReplaceError("Enter something to find.")
    if len(find) > MAX_PATTERN:
        raise ReplaceError("Search text is too long.")
    body = find if regex else re.escape(find)
    if whole_word:
        # Only add a boundary where the search text starts/ends with a word character.
        left = rf"(?<!{SPACED_WORD})" if regex or re.fullmatch(SPACED_WORD, find[:1]) else ""
        right = rf"(?!{SPACED_WORD})" if regex or re.fullmatch(SPACED_WORD, find[-1:]) else ""
        body = f"{left}(?:{body}){right}"
    try:
        return re.compile(body, 0 if case else re.IGNORECASE)
    except re.error as exc:
        raise ReplaceError(f"Invalid regular expression: {exc}") from exc


def _replacement(replace: str, regex: bool, case: bool) -> str | Callable[[re.Match], str]:
    if not regex:
        # Literal (backslashes and $ mean nothing). Without "match case", keep the found text's
        # capitalisation: "Cable tray" → "Cable bridge" at the start of a sentence.
        return (lambda _m: replace) if case else (lambda m: match_case(m[0], replace))
    # Accept JavaScript-style references too: $1, $&, ${name} → \g<1>, \g<0>, \g<name>.
    converted = re.sub(r"\$(\d+|&|\{(\w+)\})", lambda m: rf"\g<{m[2] or ('0' if m[1] == '&' else m[1])}>", replace)
    return converted


def matches(
    segments: list[dict], pattern: re.Pattern, replace: str, *, regex: bool = False, scope: Scope = "all",
) -> tuple[list[dict], int]:
    """→ ([{segment_id, source, before, after, count}], matching segments skipped: locked, or the change would
    break their inline codes)."""
    repl = _replacement(replace, regex, case=not pattern.flags & re.IGNORECASE)
    out, locked = [], 0
    for seg in map(st.normalize, segments):
        target = seg.get("target") or ""
        if not seg.get("translatable", True) or not target:
            continue
        if scope == "unconfirmed" and seg["status"] in st.HUMAN_DONE:
            continue
        try:
            after, count = pattern.subn(repl, target)
        except (re.error, IndexError) as exc:  # e.g. \g<3> with only two groups
            raise ReplaceError(f"Invalid replacement: {exc}") from exc
        if not count:
            continue
        if seg["locked"] or (inline.has_codes(seg["source"]) and inline.validate(seg["source"], after) and not inline.validate(seg["source"], target)):
            locked += 1  # locked, or the replacement would break the segment's formatting codes
            continue
        out.append({"segment_id": seg["id"], "source": seg["source"], "before": target, "after": after, "count": count})
    return out, locked

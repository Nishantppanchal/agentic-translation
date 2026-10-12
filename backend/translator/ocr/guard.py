"""The OCR check's corrections, applied only where they are safe.

A vision model asked to check a reading "corrects" it into plausible words. So the checker's corrected
page is compared token by token with the first reading, and a change is applied only when it is
- a small fix inside words ("Kabelprische" → "Kabelpritsche": a character or two), or
- confirmed by the PDF's own text layer (every new word is in it), or
- the removal of an exact repeat (a reading loop: the same text twice in a row).
Anything else — another word, a changed number, text added or dropped, a different paragraph or table
structure — keeps the first reading; real word changes are listed for a person to check.

In Chinese, Japanese and Korean one character can be a whole word (复查 → 检查), so no change counts as
small there: it is applied only when the text layer has the corrected text in context.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from rapidfuzz.distance import Levenshtein

# CJK characters are compared one by one: a clause written without spaces is not one "word".
_CJK = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff"
_TOKEN = re.compile(rf"\s+|[{_CJK}]|[^\W_{_CJK}]+|[^\w\s]|_")
WORD = re.compile(rf"[{_CJK}]|[^\W_{_CJK}]+")  # a word; CJK: a character
_WORD = WORD
_CJK_CHAR = re.compile(rf"[{_CJK}]")
_DIGIT = re.compile(r"\d")
_SYNTAX = set("|#*`>[]$\\-:")  # markdown structure: the layout decides it, not the checker
MAX_EDIT = 2  # characters changed per word for a fix to count as small
MAX_WORDS = 3  # words replaced in one place for a fix to count as small


def _small(old: str, new: str) -> bool:
    a, b = _WORD.findall(old), _WORD.findall(new)
    if not a or len(a) != len(b) or len(a) > MAX_WORDS or _DIGIT.search(old + new):
        return False
    if _CJK_CHAR.search(old + new):  # one character can be another word: never "small"
        return False
    if [t for t in _TOKEN.findall(old) if not _WORD.fullmatch(t)] != [t for t in _TOKEN.findall(new) if not _WORD.fullmatch(t)]:
        return False  # punctuation or spacing between the words changed too
    return all(Levenshtein.distance(x, y) <= min(MAX_EDIT, max(1, len(x) // 3)) for x, y in zip(a, b))


def _confirmed(new: str, layer: set[str]) -> bool:
    words = _WORD.findall(new)
    return bool(words) and all(w.casefold() in layer for w in words)


def _syntax_only(old: str, new: str) -> bool:
    return all(c.isspace() or c in _SYNTAX for c in old + new)


def _short(text: str, n: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def guard(original: str, corrected: str, text_layer: str = "") -> tuple[str, list[str], list[str]]:
    """→ (page markdown with the safe corrections applied, corrections applied, corrections not applied)."""
    a, b = _TOKEN.findall(original), _TOKEN.findall(corrected)
    layer = {w.casefold() for w in _WORD.findall(text_layer or "")}
    compact_layer = "".join((text_layer or "").split())

    def confirmed(new: str, label_new: str) -> bool:
        if not layer:
            return False
        if _CJK_CHAR.search(label_new):  # the corrected characters together with their neighbours
            return "".join(label_new.split()) in compact_layer
        return _confirmed(new, layer)

    out: list[str] = []
    applied: list[str] = []
    held: list[str] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        old, new = "".join(a[i1:i2]), "".join(b[j1:j2])
        if _CJK_CHAR.search(old + new):  # a character alone says little: show its neighbours
            before, after = "".join(a[max(0, i1 - 4) : i1]).lstrip(), "".join(a[i2 : i2 + 4]).rstrip()
            label_old, label_new = f"{before}{old}{after}", f"{before}{new}{after}"
        else:
            label_old, label_new = old, new
        if op == "equal" or _syntax_only(old, new):
            out.append(old)  # unchanged, or only spacing / markdown structure: keep the reading
            continue
        if op == "delete":
            before = "".join(a[max(0, i1 - (i2 - i1)) : i1])
            if old.strip() and before.strip() == old.strip():  # the same text twice in a row
                applied.append(f"repeated text removed: “{_short(old)}”")
                continue
            out.append(old)
            held.append(f"the checker would drop “{_short(old)}”")
            continue
        if op == "insert":
            if confirmed(new, label_new):
                out.append(new)
                applied.append(f"missing text added (in the PDF's text layer): “{_short(new)}”")
            else:
                held.append(f"the checker reads more here: “{_short(new)}”")
            continue
        if _small(old, new) or confirmed(new, label_new):
            out.append(new)
            applied.append(f"“{_short(label_old)}” → “{_short(label_new)}”")
        else:
            out.append(old)
            held.append(f"“{_short(label_old)}” → “{_short(label_new)}”?")
    return "".join(out), applied, held

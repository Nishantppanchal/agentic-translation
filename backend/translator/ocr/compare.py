"""Two readings of the same page (or picture), compared word by word.

Two vision models read each scanned page independently (agents/steps/page.py). Where they agree, two readers saw
the same text; where they differ, `disputes` says where. Each dispute knows its words in both readings, a few words
around it, and where it sits in each reading's own text, so `apply` can put the other reading's version in
without touching the markdown around it. Markdown, punctuation, spacing, case, line-end hyphens and character
widths (full-width digits, ligatures) are not differences. In Chinese, Japanese and Korean a character is a word.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

_CJK = "぀-ヿ㐀-䶿一-鿿가-힯豈-﫿"
_WORD = re.compile(rf"[{_CJK}]|[^\W_{_CJK}]+")  # a CJK character, or a run of letters and digits
_CJK_CHAR = re.compile(rf"[{_CJK}]")
# Not text: the app's markers, HTML tags and entities (tables), LaTeX commands and math delimiters.
_NOISE = re.compile(r"\*?\[Figure:[^\]]*\]\*?|\[\[(?:FIGURE \d+|HEADER|FOOTER)\]\]|<[^>\n]+>|&#?\w+;|\\[a-zA-Z]+|\$")
_MARKUP = re.compile(r"[|*#`>_]+|:?-{3,}:?")  # table pipes and rules, emphasis, headings: not shown in the context


def _plain(text: str) -> str:
    return " ".join(_MARKUP.sub(" ", text).split())


@dataclass(frozen=True)
class Word:
    norm: str  # what is compared: NFKC, case-folded
    start: int  # where it is in its text
    end: int


@dataclass(frozen=True)
class Dispute:
    """A place where two readings differ. `ours` is "" where only the other reading has text, `theirs` is "" where
    only ours has. `span` / `their_span`: where each version is in its reading's text (an empty span is where the
    other's text would go)."""

    ours: str
    theirs: str
    before: str  # this reading's words just before and after, to show where it is
    after: str
    span: tuple[int, int]
    their_span: tuple[int, int]


def words(text: str) -> list[Word]:
    noise = [m.span() for m in _NOISE.finditer(text)]
    out = []
    for m in _WORD.finditer(text):
        if any(a <= m.start() < b for a, b in noise):
            continue
        out.append(Word(unicodedata.normalize("NFKC", m.group()).casefold(), m.start(), m.end()))
    return out


def _span(ws: list[Word], i1: int, i2: int) -> tuple[int, int]:
    if i1 < i2:
        return ws[i1].start, ws[i2 - 1].end
    at = ws[i1 - 1].end if i1 else (ws[0].start if ws else 0)
    return at, at


def disputes(ours: str, theirs: str) -> list[Dispute]:
    """Where `theirs` differs from `ours`, in the order they come in `ours`."""
    a, b = words(ours), words(theirs)
    out: list[Dispute] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, [w.norm for w in a], [w.norm for w in b], autojunk=False).get_opcodes():
        if op == "equal" or "".join(w.norm for w in a[i1:i2]) == "".join(w.norm for w in b[j1:j2]):
            continue  # the same letters split differently: "Kabel-" "pritsche", "16 mm²" / "16mm2"
        span, their_span = _span(a, i1, i2), _span(b, j1, j2)
        cjk = bool(_CJK_CHAR.search(ours[span[0]:span[1]] + theirs[their_span[0]:their_span[1]]))
        n = 6 if cjk else 3  # words of context (a CJK "word" is one character)
        before = ours[a[max(0, i1 - n)].start:a[i1 - 1].end] if i1 else ""
        after = ours[a[i2].start:a[min(len(a), i2 + n) - 1].end] if i2 < len(a) else ""
        out.append(Dispute(ours=ours[span[0]:span[1]], theirs=theirs[their_span[0]:their_span[1]],
                           before=_plain(before), after=_plain(after), span=span, their_span=their_span))
    return out


def rate(ours: str, found: list[Dispute]) -> float:
    """Disagreements per 100 words of the reading: 0–3 on readable pages, over 10 on ones that are hard to read."""
    return 100 * len(found) / max(1, len(words(ours)))


def apply(ours: str, found: list[Dispute], chosen: Iterable[int]) -> str:
    """`ours` with the other reading's version put in at the disputes numbered in `chosen` (indices into `found`)."""
    out = ours
    for k in sorted(set(chosen), key=lambda k: found[k].span[0], reverse=True):  # from the end: spans stay valid
        d = found[k]
        new = d.theirs
        start, end = d.span
        if start == end and new:  # text only the other reading has: keep it apart from its neighbours
            cjk = bool(_CJK_CHAR.match(new))
            if start and not out[start - 1].isspace() and not cjk:
                new = " " + new
            if end < len(out) and not out[end].isspace() and not cjk:
                new = new + " "
        if not new and start and end < len(out) and out[start - 1] == " " and out[end] == " ":
            end += 1  # a word taken out: not two spaces in its place
        out = out[:start] + new + out[end:]
    return out


def same(a: str, b: str) -> bool:
    """The same words (as disputes() compares them)."""
    return [w.norm for w in words(a)] == [w.norm for w in words(b)]

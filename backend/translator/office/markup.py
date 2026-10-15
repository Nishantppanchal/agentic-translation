"""A paragraph's pieces ↔ the segment text the agents translate, using the markdown the app already uses.

A paragraph (Word `w:p`, PowerPoint `a:p`, an Excel shared string) is a list of pieces: text with its formatting,
and objects (a footnote mark, an inline picture, a field) that aren't text. The formatting most of the text has is
the paragraph's base and gets no markers. A stretch that differs from it gets `**bold**`, `*italic*`, `***both***`
or `[text](url)` for a link; an object in mid-sentence becomes `[^1]`, `[^2]`… (objects at either end stay there).

The markers are handles, not formatting: when the translation is written back, the k-th bold stretch takes the
whole formatting of the k-th bold stretch of the original (a red, bold "ACHTUNG" stays red), and `[^k]` puts the
k-th object back where the translation has it. A stretch that differs only in what markdown can't say (colour
alone, underline, size) is written in the base formatting and counted as "formatting simplified".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark").disable(["image", "html_inline", "autolink", "backticks", "entity"])

_ESCAPE = re.compile(r"([\\*_\[\]])")
_OBJECT = re.compile(r"\\?\[\\?\^(\d+)\\?\]")
_SENTINEL = 0xE000  # private-use characters stand for the objects while the inline markdown is parsed


@dataclass
class Piece:
    """Text (with \\n for a line break, \\t for a tab) or an object (`text` empty, `obj` set)."""

    text: str = ""
    style: str = ""  # the formatting, as a comparable key
    bold: bool = False
    italic: bool = False
    link: str | None = None  # a link's target
    payload: Any = None  # what the writer needs: the run / rPr / hyperlink element
    obj: Any = None  # an object (format-specific)

    @property
    def is_object(self) -> bool:
        return self.obj is not None


@dataclass
class Encoded:
    text: str  # the segment text
    base: Piece | None  # the base formatting's piece
    stretches: dict[str, list[Piece]] = field(default_factory=dict)  # marker kind → original stretches, in order
    objects: list[Piece] = field(default_factory=list)  # [^1], [^2]… in mid-sentence
    lead: list[Piece] = field(default_factory=list)  # objects before the text
    tail: list[Piece] = field(default_factory=list)  # objects after it
    simplified: int = 0  # stretches written in the base formatting (a difference markdown can't express)


@dataclass
class Out:
    """One piece of the translation to write: text with the original piece whose formatting it takes, or an object."""

    text: str = ""
    like: Piece | None = None
    obj: Piece | None = None
    link: bool = False


def escape(text: str) -> str:
    return _ESCAPE.sub(r"\\\1", text)


def _merge(pieces: list[Piece]) -> list[Piece]:
    out: list[Piece] = []
    for p in pieces:
        last = out[-1] if out else None
        if (last and not p.is_object and not last.is_object and p.style == last.style and p.link == last.link
                and p.link is None):
            last.text += p.text
        else:
            out.append(Piece(**{**p.__dict__}))
    return [p for p in out if p.is_object or p.text]


def _kind(p: Piece, base: Piece) -> str:
    if p.link is not None:
        return "link"
    b, i = p.bold != base.bold, p.italic != base.italic
    return "bi" if b and i else "b" if b else "i" if i else ""


_WRAP = {"b": "**", "i": "*", "bi": "***"}


def _wrap(text: str, kind: str) -> str:
    """Markers hug the text: markdown emphasis can't start or end with a space."""
    core = text.strip(" ")
    if not core or kind not in _WRAP:
        return escape(text)
    left, right = text[: len(text) - len(text.lstrip(" "))], text[len(text.rstrip(" ")) :]
    return f"{left}{_WRAP[kind]}{escape(core)}{_WRAP[kind]}{right}"


def encode(pieces: list[Piece]) -> Encoded:
    pieces = _merge(pieces)
    texts = [p for p in pieces if not p.is_object]
    if not texts:
        return Encoded(text="", base=None, lead=[p for p in pieces if p.is_object])
    weight: dict[str, int] = {}
    for p in texts:
        if p.link is None:
            weight[p.style] = weight.get(p.style, 0) + len(p.text.strip())
    base_style = max(weight, key=lambda k: weight[k]) if weight else texts[0].style
    base = next((p for p in texts if p.style == base_style and p.link is None), texts[0])
    first = pieces.index(texts[0])
    last = len(pieces) - 1 - pieces[::-1].index(texts[-1])
    enc = Encoded(text="", base=base, lead=pieces[:first], tail=pieces[last + 1 :])
    out: list[str] = []
    for p in pieces[first : last + 1]:
        if p.is_object:
            enc.objects.append(p)
            out.append(f"[^{len(enc.objects)}]")
            continue
        kind = _kind(p, base)
        if kind:
            enc.stretches.setdefault(kind, []).append(p)
        elif p.style != base.style:
            enc.simplified += 1
        if kind == "link":
            out.append(f"[{escape(p.text)}]({p.link or ''})")
        else:
            out.append(_wrap(p.text, kind))
    enc.text = "".join(out)
    return enc


def plain(pieces: list[Piece]) -> str:
    return "".join(p.text for p in pieces if not p.is_object)


@dataclass
class Decoded:
    out: list[Out]
    simplified: int = 0  # marked stretches with no original to take formatting from
    moved: list[Piece] = field(default_factory=list)  # objects the translation lost (written before the tail)


def decode(target: str, enc: Encoded) -> Decoded:
    """The translation → pieces to write, each with the original piece whose formatting it takes."""
    text = _OBJECT.sub(lambda m: chr(_SENTINEL + int(m.group(1))), target)
    tokens = (_md.parseInline(text)[0].children or []) if text else []
    used = {k: 0 for k in enc.stretches}
    placed: set[int] = set()
    result = Decoded(out=[])
    state = {"bold": 0, "italic": 0, "link": 0, "span": 0}
    span_piece: dict[int, Piece | None] = {}

    def like(kind: str) -> Piece | None:
        """The original stretch a marked span takes its formatting from (each span claims the next one)."""
        if not kind:
            return enc.base
        if state["span"] in span_piece:
            return span_piece[state["span"]]
        found = enc.stretches.get(kind) or []
        if not found:
            result.simplified += 1
            piece = enc.base
        else:
            piece = found[min(used[kind], len(found) - 1)]
            used[kind] += 1
        span_piece[state["span"]] = piece
        return piece

    def kind() -> str:
        if state["link"]:
            return "link"
        b, i = state["bold"] > 0, state["italic"] > 0
        return "bi" if b and i else "b" if b else "i" if i else ""

    def emit(chunk: str) -> None:
        for part in re.split(f"([{chr(_SENTINEL + 1)}-{chr(_SENTINEL + 999)}])", chunk):
            if not part:
                continue
            n = ord(part) - _SENTINEL if len(part) == 1 and _SENTINEL < ord(part) < _SENTINEL + 1000 else 0
            if n:
                if 1 <= n <= len(enc.objects) and n not in placed:
                    placed.add(n)
                    result.out.append(Out(obj=enc.objects[n - 1]))
                continue
            k = kind()
            piece = like(k)
            prev = result.out[-1] if result.out else None
            if prev is not None and prev.obj is None and prev.like is piece and prev.link == (k == "link"):
                prev.text += part
            else:
                result.out.append(Out(text=part, like=piece, link=k == "link"))

    for tok in tokens:
        if tok.type == "text":
            emit(tok.content)
        elif tok.type in ("softbreak", "hardbreak"):
            emit("\n")
        elif tok.type in ("strong_open", "strong_close", "em_open", "em_close", "link_open", "link_close"):
            key = {"strong": "bold", "em": "italic", "link": "link"}[tok.type.rsplit("_", 1)[0]]
            state[key] = state[key] + 1 if tok.type.endswith("_open") else max(0, state[key] - 1)
            state["span"] += 1
        elif tok.content:
            emit(tok.content)
    result.moved = [o for i, o in enumerate(enc.objects, start=1) if i not in placed]
    return result

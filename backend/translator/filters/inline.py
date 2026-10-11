"""Inline codes in segment text, XLIFF style: `<g id="1">bold words</g>` spans and `<x id="2"/>` placeholders.

Office and XLIFF segments carry formatting this way (a `g` is a formatting run or a hyperlink, an `x` is
a tab, line break, image, field or footnote mark). The translator must keep every code exactly once, and
may move a `g` pair to wherever its words end up. Parsing is tolerant: escaped tags, single quotes and
spacing variants are accepted, unbalanced tags are closed or dropped.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass, field

_TOKEN = re.compile(
    r"""<g\s+id\s*=\s*["']([^"']+)["']\s*>|</g\s*>|<x\s+id\s*=\s*["']([^"']+)["']\s*/>""",
    re.I,
)
_ESCAPED = re.compile(r"&lt;(/?(?:g|x)\b[^&]{0,40}?)&gt;", re.I)


@dataclass
class Node:
    kind: str  # "text" | "g" | "x"
    text: str = ""
    id: str = ""
    children: list[Node] = field(default_factory=list)


def has_codes(text: str | None) -> bool:
    return bool(text) and _TOKEN.search(text) is not None


def normalize(text: str) -> str:
    """Unescape `&lt;g id="1"&gt;` and canonicalise tag spelling."""
    if not text or ("&lt;" not in text and "<" not in text):
        return text or ""
    text = _ESCAPED.sub(lambda m: f"<{html.unescape(m[1])}>", text)
    return serialize(parse(text))


def parse(text: str) -> list[Node]:
    """→ a tree. `</g>` without an open `<g>` is dropped; open `<g>`s are closed at the end."""
    root = Node("g")
    stack = [root]
    pos = 0
    for m in _TOKEN.finditer(text or ""):
        if m.start() > pos:
            stack[-1].children.append(Node("text", text[pos:m.start()]))
        pos = m.end()
        if m[1] is not None:
            g = Node("g", id=m[1])
            stack[-1].children.append(g)
            stack.append(g)
        elif m[2] is not None:
            stack[-1].children.append(Node("x", id=m[2]))
        elif len(stack) > 1:
            stack.pop()
    if pos < len(text or ""):
        stack[-1].children.append(Node("text", text[pos:]))
    return root.children


def serialize(nodes: list[Node]) -> str:
    out = []
    for n in nodes:
        if n.kind == "text":
            out.append(n.text)
        elif n.kind == "x":
            out.append(f'<x id="{n.id}"/>')
        else:
            out.append(f'<g id="{n.id}">{serialize(n.children)}</g>')
    return "".join(out)


def strip(text: str | None) -> str:
    """Plain text: codes removed, span contents kept."""
    return _TOKEN.sub("", text or "")


def codes(text: str | None) -> Counter:
    """{"g:1": 1, "x:2": 1, …} — opening g tags and placeholders."""
    return Counter(f"g:{m[1]}" if m[1] is not None else f"x:{m[2]}" for m in _TOKEN.finditer(text or "") if m[1] or m[2])


def _balanced(text: str) -> bool:
    depth = 0
    for m in _TOKEN.finditer(text or ""):
        if m[1] is not None:
            depth += 1
        elif m[2] is None:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _show(code: str) -> str:
    kind, cid = code.split(":", 1)
    return f'<g id="{cid}">…</g>' if kind == "g" else f'<x id="{cid}"/>'


def validate(source: str, target: str) -> list[str]:
    """Problems with the target's codes compared with the source (empty = fine)."""
    want, have = codes(source), codes(target)
    problems = []
    missing = sorted((want - have).elements())
    extra = sorted((have - want).elements())
    if missing:
        problems.append("missing " + ", ".join(_show(c) for c in missing))
    if extra:
        problems.append("unexpected " + ", ".join(_show(c) for c in extra))
    if not _balanced(target):
        problems.append("a <g> is not closed (or closed twice)")
    return problems


def repair(source: str, target: str) -> tuple[str, list[str]]:
    """Make the target's codes match the source as far as possible → (text, what was done).

    Unknown and duplicate codes are removed (their text is kept); missing placeholders are appended
    at the end; a missing span loses its formatting (its words are already in the text).
    """
    target = normalize(target)
    want = codes(source)
    seen: Counter = Counter()
    fixes: list[str] = []

    def keep(nodes: list[Node]) -> list[Node]:
        out: list[Node] = []
        for n in nodes:
            if n.kind == "text":
                out.append(n)
                continue
            key = f"{n.kind}:{n.id}"
            seen[key] += 1
            if seen[key] > want.get(key, 0):
                fixes.append(f"removed {_show(key)}")
                if n.kind == "g":
                    out.extend(keep(n.children))
                continue
            if n.kind == "g":
                n.children = keep(n.children)
            out.append(n)
        return out

    nodes = keep(parse(target))
    for key in sorted((want - seen).elements()):
        if key.startswith("x:"):
            nodes.append(Node("x", id=key[2:]))
            fixes.append(f"appended {_show(key)}")
        else:
            fixes.append(f"lost the formatting of {_show(key)}")
    return serialize(nodes), fixes


def display(text: str | None) -> str:
    """For people reading a document (review tables): `<g id="1">x</g>` → `{1}x{/1}`, `<x id="2"/>` → `{2}`."""
    out = []

    def walk(nodes: list[Node]) -> None:
        for n in nodes:
            if n.kind == "text":
                out.append(n.text)
            elif n.kind == "x":
                out.append(f"{{{n.id}}}")
            else:
                out.append(f"{{{n.id}}}")
                walk(n.children)
                out.append(f"{{/{n.id}}}")

    walk(parse(text or ""))
    return "".join(out)


def labels_hint(source: str, labels: dict[str, str] | None) -> str:
    """'1 = bold, 2 = tab' for prompts and the UI."""
    if not labels:
        return ""
    ids = [k.split(":", 1)[1] for k in codes(source)]
    return ", ".join(f"{i} = {labels[i]}" for i in ids if i in labels)

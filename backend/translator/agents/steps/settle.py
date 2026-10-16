"""Settling where two readings of an image differ, and the small helpers the reading graphs share.

The arbiter (the OCR check model) is shown the image and the numbered places where the two readings disagree, and
says what is printed at each. Where it reads the second reading's words, they replace the first's (two of three);
where it reads the first's, nothing changes; anything else (neither, or unreadable) is left for the person checking
the source, with both versions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from google.adk import Context
from google.genai import types

from ...models.replies import parse_arbitration
from ...ocr import compare
from ...ocr.compare import Dispute
from .. import prompts
from ..common import reply_text, user_message
from ..workers import ocr_arbiter

MAX_LISTED = 40  # disputes listed for one page at most (a page that hard is marked as a whole)


@dataclass
class Settled:
    text: str
    changed: list[str] = field(default_factory=list)  # what was changed, as “first” → “second”
    open: list[str] = field(default_factory=list)  # what's left for the person checking the source


def _quote(d: Dispute, words: str) -> str:
    cjk = compare._CJK_CHAR.search(d.before + words + d.after)
    sep = "" if cjk else " "
    return "“" + sep.join(x for x in (d.before[-24:], words or "‸", d.after[:24]) if x) + "”"  # ‸: nothing there


def describe(d: Dispute) -> str:
    """One disagreement for the person: both versions, with the words around them."""
    return f"{_quote(d, d.ours)} or {_quote(d, d.theirs)}? (the two readings differ)"


def items(found: list[Dispute]) -> str:
    return "\n".join(f"{k}. …{d.before} [A: {d.ours or '(nothing)'} | B: {d.theirs or '(nothing)'}] {d.after}…"
                     for k, d in enumerate(found, start=1))


async def arbitrate(ctx: Context, image: types.Part, found: list[Dispute], what: str, run_id: str) -> dict[int, str]:
    """What the arbiter reads at each numbered place ({1: "…"}; "?" where it can't read it)."""
    prompt = prompts.ARBITRATE.format(what=what, items=items(found))
    out = await ctx.run_node(ocr_arbiter, node_input=user_message(image, prompt), run_id=run_id)
    return parse_arbitration(reply_text(out))


def decide(ours: str, found: list[Dispute], answers: dict[int, str]) -> Settled:
    chosen, changed, left = [], [], []
    for k, d in enumerate(found, start=1):
        said = answers.get(k, "?").strip()
        if said.lower() in ("(nothing)", "nothing"):
            said = ""
        if said != "?" and compare.same(said, d.theirs) and not compare.same(said, d.ours):
            chosen.append(k - 1)
            changed.append(f"{_quote(d, d.ours)} → {_quote(d, d.theirs)} (the second reading; the OCR check agrees)")
        elif said != "?" and compare.same(said, d.ours):
            continue
        else:
            seen = "" if said == "?" else f"; the OCR check read “{said}”"
            left.append(f"{_quote(d, d.ours)} or {_quote(d, d.theirs)}? (the two readings differ{seen})")
    return Settled(compare.apply(ours, found, chosen), changed, left)


async def save_json(ctx: Context, name: str, data) -> None:
    await ctx.save_artifact(name, types.Part(text=json.dumps(data, ensure_ascii=False)))


async def load_json(ctx: Context, name: str):
    part = await ctx.load_artifact(name)
    if part is None or not part.text:
        return None
    try:
        return json.loads(part.text)
    except ValueError:
        return None


async def load_bytes(ctx: Context, name: str) -> bytes:
    part = await ctx.load_artifact(name)
    if part is None or part.inline_data is None:
        raise RuntimeError(f"Missing artifact {name}")
    return part.inline_data.data

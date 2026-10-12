"""Tasks on a finished document, run on request through one workflow:

    START → dispatch ─┬─(rewrite)─────→ rewrite       "more formal", "shorter", … — one result or alternatives
                      ├─(consistency)─→ consistency   one translation per repeated sentence; termbase applied
                      └─(lqa)─────────→ assess        independent quality score (agents/lqa.py)

The task (`POST /api/sessions/{id}/tasks`) arrives in `doc:task` = {kind, segment_ids, instruction, n}.
Rewrites and consistency fixes are staged as a proposal: nothing changes until the person accepts, and
with alternatives they pick one per segment.

Consistency groups are found without a model: segments with the same source but different
translations (if a person already confirmed one of them, that translation is used, no model call),
and segments that break a termbase rule (a forbidden variant, or the approved term missing). Then one
model call per group.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from google.adk import Context, Event, Workflow
from google.adk.workflow import START, node

from .. import projects
from ..config import get_settings
from ..document import proposals
from ..document import state as st
from ..document.pages import page_batches
from ..models import structured
from ..models.replies import parse_alternatives, parse_segments
from ..quality import qa
from ..text import contains_term
from . import prompts
from .common import doc_langs, pair_text, reply_text, run_bounded, say, user_message
from .lqa import assess
from .workers import consistency_fixer, rewriter

OPS_NAME = "ops"
ROUTES = {"alternatives": "rewrite", "retranslate": "rewrite", "consistency": "consistency", "lqa": "lqa"}



@node(rerun_on_resume=True)
async def dispatch(ctx: Context, node_input: Any):
    task = dict(ctx.state.get("doc:task") or {})
    route = ROUTES.get(task.get("kind", ""))
    if route is None:
        raise RuntimeError(f"Unknown task {task.get('kind')!r}.")
    yield Event(state={"doc:task": None, "doc:task_last": {**task, "at": time.time()}}, output=task, route=route)


# --------------------------------------------------------------------------- #
# Rewrite: one result, or alternatives to choose from
# --------------------------------------------------------------------------- #


@node(rerun_on_resume=True)
async def rewrite(ctx: Context, node_input: Any):
    settings = get_settings()
    task = node_input or {}
    n = max(1, min(4, int(task.get("n") or 1)))
    instruction = (task.get("instruction") or "").strip() or (
        "Offer different good ways to say it." if n > 1 else "Improve the translation: more natural and precise."
    )
    ids = set(task.get("segment_ids") or [])
    segments = [
        s for s in map(st.normalize, st.effective_segments(ctx.state))
        if s["id"] in ids and s.get("translatable", True) and s.get("target") and not s["locked"]
    ]
    if not segments:
        yield say("Nothing to rewrite: the selected segments are locked, empty or not translatable.")
        return
    source_lang, target_lang = doc_langs(ctx.state)
    use_json = structured.enabled("rewrite")
    batches = page_batches(segments, settings.page_max_chars)
    what = f"{n} alternative translations" if n > 1 else "a revised translation"
    yield say(f"Rewriting {len(segments)} segment{'s' if len(segments) != 1 else ''}: {instruction}"
               + (f" ({n} alternatives each)" if n > 1 else ""))

    async def run(i: int, batch: list[dict]) -> dict[str, list[dict]]:
        prompt = prompts.REWRITE.format(
            source_lang=source_lang, target_lang=target_lang, instruction=instruction, what=what,
            alternatives_rule=prompts.REWRITE_ALTERNATIVES if n > 1 else "",
            instructions=projects.instructions_for(ctx.state),
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in batch]),
            brief=ctx.state.get("doc:brief") or "(none)", pairs=pair_text(batch),
            output_format=prompts.REWRITE_FORMAT_JSON if use_json else prompts.REWRITE_FORMAT_TAGS,
        )
        out = reply_text(await ctx.run_node(rewriter, node_input=user_message(prompt), run_id=f"rewrite-b{i}"))
        obj = structured.parse_json(out)
        return structured.alternatives_from(obj) if obj is not None and "segments" in obj else parse_alternatives(out)

    found: dict[str, list[dict]] = {}
    async for _, result in run_bounded([lambda i=i, b=b: run(i, b) for i, b in enumerate(batches)], settings.max_concurrency):
        found.update(result)

    proposal = proposals.open_proposal(ctx.state, note=f"Rewrite: {instruction}")
    staged = 0
    for seg in segments:
        options = []
        for alt in found.get(seg["id"]) or []:
            options.append({"text": alt["text"], "note": alt.get("note", "")})
        options = options[:n]
        if not options:
            continue
        if proposals.stage_change(proposal, ctx.state, seg["id"], "target", options[0]["text"], options if n > 1 else None):
            staged += 1
    msg = (f"Proposed {'alternatives for' if n > 1 else 'a new translation for'} {staged} segment{'s' if staged != 1 else ''}"
           if staged else "The rewrite didn't change anything")
    yield say(msg + (" — pick and accept in the proposal" if staged else ""), state={"doc:proposal": proposals.close_proposal(proposal)})


# --------------------------------------------------------------------------- #
# Consistency
# --------------------------------------------------------------------------- #


def find_groups(state) -> tuple[list[list[dict]], list[tuple[dict, list[dict]]]]:
    """→ (same-source groups, [(term, segments breaking it)]). Only groups with something to change."""
    segs = [s for s in map(st.normalize, st.effective_segments(state)) if s.get("translatable", True) and s.get("target")]
    by_source: dict[str, list[dict]] = defaultdict(list)
    for s in segs:
        key = qa._norm(s["source"])
        if len(key) >= 3:
            by_source[key].append(s)
    same = [g for g in by_source.values()
            if len({qa._norm(s["target"]) for s in g}) > 1 and any(not st.is_frozen(s) for s in g)]

    term_groups = []
    for term in qa.terms_for(state, [s["source"] for s in segs]):
        if not term.get("target") and not term.get("forbidden"):
            continue
        breaking = []
        for s in segs:
            if st.is_frozen(s) or not contains_term(s["source"], term["source"], term.get("case_sensitive", False)):
                continue
            target = s["target"]
            bad = any(contains_term(target, b) for b in term.get("forbidden") or [])
            missing = term.get("target") and term.get("status") != "proposed" and qa._norm(term["target"]) not in qa._norm(target)
            if bad or missing:
                breaking.append(s)
        if breaking:
            term_groups.append((term, breaking))
    return same, term_groups


async def consistency_fixes(ctx: Context) -> tuple[dict[str, str], dict[str, int]]:
    """Fix repeated sentences and termbase rules → ({segment id: new text}, counts).

    Only changes for segments that aren't confirmed or locked. Used by the
    consistency task (as a proposal) and by the pipeline's polish step (applied to the AI draft)."""
    settings = get_settings()
    same, term_groups = find_groups(ctx.state)
    counts = {"same": len(same), "terms": len(term_groups), "from_confirmed": 0}
    if not same and not term_groups:
        return {}, counts
    source_lang, target_lang = doc_langs(ctx.state)
    use_json = structured.enabled("polish")
    fmt = prompts.REFINE_FORMAT_JSON if use_json else prompts.REFINE_FORMAT_TAGS

    def parse(out: str) -> dict[str, str]:
        obj = structured.parse_json(out)
        return structured.segments_from(obj) if obj is not None and "segments" in obj else parse_segments(out)

    current = {s["id"]: s for s in map(st.normalize, st.effective_segments(ctx.state))}
    results: dict[str, str] = {}

    # 1) Same source: a person's confirmed translation wins outright; otherwise ask the model.
    asks = []
    for group in same:
        confirmed = {qa._norm(s["target"]): s["target"] for s in group if st.is_frozen(s)}
        if len(confirmed) == 1:
            chosen = next(iter(confirmed.values()))
            for s in group:
                if not st.is_frozen(s):
                    results[s["id"]] = chosen
            counts["from_confirmed"] += 1
        else:
            asks.append(group)

    async def unify(i: int, group: list[dict]) -> dict[str, str]:
        prompt = prompts.CONSISTENCY_SAME_SOURCE.format(
            source_lang=source_lang, target_lang=target_lang,
            instructions=projects.instructions_for(ctx.state),
            glossary=projects.glossary_for(ctx.state, [group[0]["source"]]), pairs=pair_text(group), output_format=fmt,
        )
        return parse(reply_text(await ctx.run_node(consistency_fixer, node_input=user_message(prompt), run_id=f"same-{i}")))

    async for _, out in run_bounded([lambda i=i, g=g: unify(i, g) for i, g in enumerate(asks)], settings.max_concurrency):
        results.update(out)

    # 2) Termbase rules, on the texts as they are after step 1.
    async def apply_term(i: int, term: dict, group: list[dict]) -> dict[str, str]:
        texts = [{**s, "target": results.get(s["id"], s["target"])} for s in group]
        rule = f'{term["source"]} → {term["target"]}' if term.get("target") else term["source"]
        if term.get("forbidden"):
            rule += "; never " + ", ".join(f'"{b}"' for b in term["forbidden"])
        if term.get("note"):
            rule += f" ({term['note']})"
        prompt = prompts.CONSISTENCY_TERM.format(
            source_lang=source_lang, target_lang=target_lang, rule=rule,
            pairs=pair_text(texts), output_format=fmt,
        )
        return parse(reply_text(await ctx.run_node(consistency_fixer, node_input=user_message(prompt), run_id=f"term-{i}")))

    term_tasks = [lambda i=i, t=t, g=g: apply_term(i, t, g) for i, (t, g) in enumerate(term_groups)]
    async for _, out in run_bounded(term_tasks, settings.max_concurrency):
        results.update(out)

    fixes = {}
    for sid, text in results.items():
        seg = current.get(sid)
        if seg is None or st.is_frozen(seg) or not text:
            continue
        if text != seg.get("target"):
            fixes[sid] = text
    return fixes, counts


@node(rerun_on_resume=True)
async def consistency(ctx: Context, node_input: Any):
    same, term_groups = find_groups(ctx.state)
    if not same and not term_groups:
        yield say("Consistency: nothing to fix — repeated sentences are translated the same way and the termbase is followed.")
        return
    yield say(f"Consistency: {len(same)} repeated sentence{'s' if len(same) != 1 else ''} translated differently, "
               f"{len(term_groups)} termbase rule{'s' if len(term_groups) != 1 else ''} not followed")
    fixes, counts = await consistency_fixes(ctx)
    proposal = proposals.open_proposal(ctx.state, note="Consistency fixes")
    staged = sum(1 for sid, text in fixes.items() if proposals.stage_change(proposal, ctx.state, sid, "target", text))
    msg = f"Consistency: proposed {staged} change{'s' if staged != 1 else ''}"
    if counts["from_confirmed"]:
        n = counts["from_confirmed"]
        msg += f" ({n} sentence{'s' if n != 1 else ''} aligned to your confirmed translation)"
    yield say(msg if staged else "Consistency: the model kept the current translations", state={"doc:proposal": proposals.close_proposal(proposal)})


ops_workflow = Workflow(
    name=OPS_NAME,
    edges=[
        (START, dispatch),
        (dispatch, {"rewrite": rewrite, "consistency": consistency, "lqa": assess}),
    ],
)

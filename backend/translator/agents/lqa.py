"""Independent LQA run: an MQM assessor annotates the current translation; nothing is changed.

    START → assess

Runs on demand (`POST /api/sessions/{id}/lqa`) with the `lqa` model role, which defaults to the review
model; set `LQA_MODEL` to a different model for a second opinion. The result (errors, per-segment scores
and the scorecard) is stored as `doc:lqa`, and each segment's `qe` is updated.
"""

from __future__ import annotations

import time
from typing import Any

from google.adk import Context, Event, Workflow
from google.adk.workflow import START, node

from .. import projects
from ..config import get_settings
from ..document import state as st
from ..document.pages import page_batches
from ..models import routing, structured
from ..models.replies import parse_issues, parse_scores
from ..quality import lqa
from . import prompts
from .common import doc_langs, pair_text, progress_state, reply_text, run_bounded, say, user_message
from .workers import lqa_reviewer

LQA_NAME = "lqa"



def _parse(text: str) -> tuple[list[dict], dict[str, int]]:
    obj = structured.parse_json(text)
    if obj is not None and ("errors" in obj or "scores" in obj):
        return structured.issues_from(obj, "errors"), structured.scores_from(obj)
    return parse_issues(text, "error"), parse_scores(text)


def _threshold(state) -> float:
    pid = projects.project_id(state)
    project = projects.get_store().project(pid) if pid else None
    return float((project or {}).get("lqa_threshold") or lqa.DEFAULT_THRESHOLD)


@node(rerun_on_resume=True)
async def assess(ctx: Context, node_input: Any):
    settings = get_settings()
    segments = [s for s in map(st.normalize, st.get_segments(ctx.state)) if s.get("translatable", True) and s.get("target")]
    if not segments:
        yield say("LQA: there is no translation to assess yet.")
        return
    batches = page_batches(segments, settings.page_max_chars)
    total = len(batches)
    source_lang, target_lang = doc_langs(ctx.state)
    chosen = routing.resolve("lqa", ctx.state)
    model = chosen.id + (f" · {chosen.effort}" if chosen.effort else "")
    yield say(
        f"LQA: assessing {len(segments)} segments with {model}",
        state=progress_state("lqa", 0, total, "Assessing quality…"),
    )
    output_format = prompts.LQA_FORMAT_JSON if structured.enabled("lqa", ctx.state) else prompts.LQA_FORMAT_TAGS

    async def assess_batch(i: int, batch: list[dict]) -> tuple[list[dict], dict[str, int]]:
        prompt = prompts.LQA.format(
            source_lang=source_lang,
            target_lang=target_lang,
            brief=ctx.state.get("doc:brief") or "(none)",
            instructions=projects.instructions_for(ctx.state),
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in batch]),
            pairs=pair_text(batch),
            output_format=output_format,
        )
        out = reply_text(await ctx.run_node(lqa_reviewer, node_input=user_message(prompt), run_id=f"lqa-b{i}"))
        errors, scores = _parse(out)
        ids = {s["id"] for s in batch}
        return [e for e in errors if e["segment_id"] in ids], {k: v for k, v in scores.items() if k in ids}

    errors: list[dict] = []
    scores: dict[str, int] = {}
    done = 0
    async for _, (batch_errors, batch_scores) in run_bounded(
        [lambda i=i, b=b: assess_batch(i, b) for i, b in enumerate(batches)], settings.max_concurrency
    ):
        done += 1
        errors.extend(batch_errors)
        scores.update(batch_scores)
        yield Event(state=progress_state("lqa", done, total, f"Assessed {done}/{total}"))
    card = lqa.scorecard(errors, lqa.evaluated_words(segments), _threshold(ctx.state))
    versions = ctx.state.get("doc:versions") or []
    result = {
        "version": versions[-1]["version"] if versions else None,
        "model": model,
        "at": time.time(),
        "errors": errors,
        "scores": scores,
        **card,
    }
    delta: dict[str, Any] = {"doc:lqa": result}
    for s in segments:
        if s["id"] in scores:
            delta[st.seg_key(s["id"])] = {**s, "qe": scores[s["id"]]}
    c = card["counts"]
    found = ", ".join(f"{c[sev]} {sev}" for sev in ("critical", "major", "minor") if c[sev]) or "no errors"
    yield say(
        f"LQA score {card['score']} — {'pass' if card['passed'] else 'fail'} (threshold {card['threshold']:g}): "
        f"{found} in {card['words']} words",
        state=delta,
    )


lqa_workflow = Workflow(name=LQA_NAME, edges=[(START, assess)])

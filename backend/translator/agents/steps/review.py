"""The review → refine loop."""

from __future__ import annotations

import re
from typing import Any

from google.adk import Context, Event
from google.adk.workflow import node

from ... import projects
from ...config import get_settings
from ...document import state as st
from ...document.pages import (
    page_batches,
)
from ...models import structured
from ...models.replies import (
    parse_issues,
    parse_scores,
    parse_segments,
    parse_terms,
)
from ...quality import qa
from .. import prompts
from ..common import doc_langs, pair_text, progress_state, reply_text, run_bounded, say, user_message
from ..workers import refiner, reviewer


def _parse_revision(text: str) -> dict[str, str]:
    obj = structured.parse_json(text)
    return structured.segments_from(obj) if obj is not None and "segments" in obj else parse_segments(text)


def _parse_review(text: str) -> tuple[list[dict], list[dict], dict[str, int]]:
    """→ (issues, uncertain terms, scores per segment). Missing parts are simply empty."""
    obj = structured.parse_json(text)
    if obj is not None and ("issues" in obj or "uncertain_terms" in obj or "scores" in obj):
        return structured.issues_from(obj), structured.terms_from(obj), structured.scores_from(obj)
    return parse_issues(text), parse_terms(text), parse_scores(text)


def is_major(issue: dict) -> bool:
    return issue["severity"] in ("major", "critical")


def issues_to_fix(issues: list[dict], segments: list[dict], round_no: int) -> list[dict]:
    """What the refiner gets: round 1 everything raised, later rounds only major issues. A 100% TM match is
    a person's approved wording for the same sentence: it is only changed for a major issue, never for style."""
    tm_exact = {s["id"] for s in segments if s.get("origin") == "tm_exact"}
    return [x for x in issues if (round_no == 1 or is_major(x)) and (x["segment_id"] not in tm_exact or is_major(x))]


def already_used(term: dict, batch: list[dict]) -> bool:
    """A reviewer "question" whose recommendation is what the translation already says confirms it rather
    than asking anything: not worth a person's time."""
    guess = (term.get("guess") or "").casefold().strip()
    if not guess:
        return False
    segs = [s for s in batch if s["id"] in set(term.get("segment_ids") or [])] or batch
    word = re.compile(rf"(?<!\w){re.escape(guess)}(?!\w)")  # whole words: "live" isn't in "delivered"
    return any(word.search((s.get("target") or "").casefold()) for s in segs)


@node(rerun_on_resume=True)
async def review(ctx: Context, node_input: Any):
    settings = get_settings()
    round_no = int(ctx.state.get("doc:review_round") or 0) + 1
    segments = st.get_segments(ctx.state)
    pending = ctx.state.get("doc:review_pending")  # None = first round; else ids the refiner changed
    if pending is not None:
        pending_set = set(pending)
        segments = [s for s in segments if s["id"] in pending_set]
    if not segments:  # the last refine pass changed nothing → nothing new to review
        yield Event(output={"issues": []}, route="done")
        return
    batches = page_batches(segments, settings.page_max_chars)
    total = len(batches)
    source_lang, target_lang = doc_langs(ctx.state)
    yield say(
        f"Review round {round_no}: checking {sum(len(b) for b in batches)} segments",
        state=progress_state("review", 0, total, f"Reviewing (round {round_no})…", "reviewing"),
    )

    review_format = prompts.REVIEW_FORMAT_JSON if structured.enabled("review") else prompts.REVIEW_FORMAT_TAGS
    # Deterministic findings (untranslated / merged segments, QA errors such as a missing number or a
    # forbidden term) are always fixed, whatever the reviewer says.
    forced: list[dict] = qa.forced_review_issues(ctx.state, segments)
    # Terms already settled (the analysis's key terms, the glossary) aren't questions for the person.
    decided = {k["term"].casefold() for k in ctx.state.get("doc:key_terms") or []}
    decided |= {g.casefold() for g in ctx.state.get("doc:glossary") or {}}

    async def review_batch(i: int, batch: list[dict]) -> tuple[list[dict], list[dict], dict[str, int]]:
        ids = {s["id"] for s in batch}
        auto = "\n".join(f"- [{x['segment_id']}] {x['note']}" for x in forced if x["segment_id"] in ids)
        prompt = prompts.REVIEW.format(
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in batch]),
            termbase=st.termbase_text(ctx.state),
            brief=ctx.state.get("doc:brief") or "(none)",
            instructions=projects.instructions_for(ctx.state),
            pairs=pair_text(batch),
            auto_issues=auto or "(none)",
            output_format=review_format,
        )
        out = reply_text(await ctx.run_node(reviewer, node_input=user_message(prompt), run_id=f"review-r{round_no}-b{i}"))
        issues, terms, scores = _parse_review(out)
        terms = [t for t in terms if qa.in_source(t["term"], batch) and t["term"].casefold() not in decided
                 and not already_used(t, batch)]
        return (
            [x for x in issues if x["segment_id"] in ids],
            terms[: settings.max_questions_per_batch],
            {k: v for k, v in scores.items() if k in ids},
        )

    issues: list[dict] = list(forced)
    terms: list[dict] = []
    scores: dict[str, int] = {}
    done = 0
    async for _, (batch_issues, batch_terms, batch_scores) in run_bounded(
        [lambda i=i, b=b: review_batch(i, b) for i, b in enumerate(batches)], settings.max_concurrency
    ):
        done += 1
        issues.extend(batch_issues)
        terms.extend(batch_terms)
        scores.update(batch_scores)
        yield Event(state=progress_state("review", done, total, f"Reviewed {done}/{total} (round {round_no})"))

    majors = sum(1 for x in issues if is_major(x))
    # Record the AI verdict and quality estimate per segment. This is NOT the human "reviewed" status.
    major_ids = {x["segment_id"] for x in issues if is_major(x)}
    passed = {
        st.seg_key(s["id"]): {
            **st.normalize(s),
            "ai_check": "issues" if s["id"] in major_ids or s.get("flags") else "passed",
            "qe": scores.get(s["id"], s.get("qe")),
        }
        for s in segments
        if not st.is_frozen(s)
    }
    report = list(ctx.state.get("doc:review_report") or [])
    report.append({"batch": 0, "round": round_no, "issues": issues})
    delta: dict[str, Any] = {"doc:review_round": round_no, "doc:review_report": report, **passed}
    if terms:
        delta["doc:questions"] = st.add_questions(ctx.state, terms, origin="reviewer")

    to_fix = issues_to_fix(issues, segments, round_no)
    go_refine = bool(to_fix) and round_no <= settings.review_max_rounds
    summary = (
        f"Review round {round_no}: {len(issues)} issue{'s' if len(issues) != 1 else ''} ({majors} major)"
        if issues
        else f"Review round {round_no}: no issues found"
    )
    yield say(summary + (" — refining" if go_refine else ""), state=delta)
    yield Event(output={"issues": to_fix if go_refine else []}, route="refine" if go_refine else "done")


@node(rerun_on_resume=True)
async def refine(ctx: Context, node_input: Any):
    settings = get_settings()
    issues: list[dict] = (node_input or {}).get("issues", [])
    by_seg: dict[str, list[dict]] = {}
    for x in issues:
        by_seg.setdefault(x["segment_id"], []).append(x)
    targets = [s for s in st.get_segments(ctx.state) if s["id"] in by_seg and not st.is_frozen(s)]
    batches = page_batches(targets, settings.page_max_chars)
    total = len(batches)
    round_no = int(ctx.state.get("doc:review_round") or 1)
    source_lang, target_lang = doc_langs(ctx.state)
    yield Event(state=progress_state("refine", 0, total, f"Refining {len(targets)} segments…", "reviewing"))

    async def refine_batch(i: int, batch: list[dict]) -> dict[str, str]:
        issue_text = "\n".join(
            f"- [{x['segment_id']}] ({x['severity']}) {x['note']}" for s in batch for x in by_seg[s["id"]]
        )
        prompt = prompts.REFINE.format(
            source_lang=source_lang, target_lang=target_lang,
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in batch]),
            termbase=st.termbase_text(ctx.state), pairs=pair_text(batch), issues=issue_text,
            instructions=projects.instructions_for(ctx.state),
            output_format=prompts.REFINE_FORMAT_JSON if structured.enabled("refine") else prompts.REFINE_FORMAT_TAGS,
        )
        out = reply_text(await ctx.run_node(refiner, node_input=user_message(prompt), run_id=f"refine-r{round_no}-b{i}"))
        return _parse_revision(out)

    changed: list[str] = list(ctx.state.get("doc:refined") or [])
    changed_now: list[str] = []
    done = 0
    async for i, revised in run_bounded(
        [lambda i=i, b=b: refine_batch(i, b) for i, b in enumerate(batches)], settings.max_concurrency
    ):
        done += 1
        delta: dict[str, Any] = {}
        for seg in batches[i]:
            new = revised.get(seg["id"])
            if new and new != seg.get("target"):
                delta[st.seg_key(seg["id"])] = st.apply_target(seg, new, origin="mt", status="draft")
                changed_now.append(seg["id"])
                if seg["id"] not in changed:
                    changed.append(seg["id"])
        delta.update(progress_state("refine", done, total, f"Refined batch {done}/{total}"))
        yield Event(state=delta)

    n = len(targets)
    yield say(
        f"Refiner revised {len(changed_now)} of {n} flagged segment{'s' if n != 1 else ''}"
        if changed_now
        else "Refiner kept the current wording",
        state={"doc:refined": changed, "doc:review_pending": changed_now},
    )
    yield Event(output={"refined": len(targets)})

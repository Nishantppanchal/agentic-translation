"""The review → refine loop, pausing when the reviewer has questions.

A round whose reviewer asks about terms waits for the person (`review_questions`) before refining: their answers
go into the glossary and become fixes the refiner applies with the review's own, so the next round reviews the
answered wording and nothing is asked twice."""

from __future__ import annotations

import re
from typing import Any

from google.adk import Context, Event
from google.adk.workflow import node

from ... import projects, references
from ...config import get_settings
from ...document import memory as tm_memory
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
from .questions import pause_for, record_answers, segments_mentioning, with_dictionary

REVIEW_INTERRUPT = "review_questions"  # + the round ("review_questions_r1"): each round's pause is its own


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
    tm_exact = {s["id"] for s in map(st.normalize, segments) if s["origin"] == "tm" and (s["match"] or 0) >= 100}
    return [x for x in issues if (round_no == 1 or is_major(x)) and (x["segment_id"] not in tm_exact or is_major(x))]


def _says(target: str | None, words: str) -> bool:
    word = re.compile(rf"(?<!\w){re.escape(words.casefold())}(?!\w)")  # whole words: "live" isn't in "delivered"
    return bool(word.search((target or "").casefold()))


def already_used(term: dict, batch: list[dict]) -> bool:
    """A reviewer "question" whose recommendation is what the translation already says confirms it rather
    than asking anything: not worth a person's time."""
    guess = (term.get("guess") or "").strip()
    if not guess:
        return False
    segs = [s for s in batch if s["id"] in set(term.get("segment_ids") or [])] or batch
    return any(_says(s.get("target"), guess) for s in segs)


def answer_fixes(questions: list[dict], asked: set[str], segments: list[dict]) -> list[dict]:
    """The person's answers to the reviewer's questions as fixes for the refiner (major: applied in any round), on
    every segment that uses the term and doesn't already say what they chose. Their decision wins over the
    reviewer's own notes about the term."""
    fixes = []
    for q in questions:
        if q["id"] not in asked or q["status"] != "resolved":
            continue
        target, note = (q.get("answer_target") or "").strip(), (q.get("answer") or "").strip()
        if target:
            ids = set(q.get("segment_ids") or []) | segments_mentioning(segments, q["term"])
            text = (f"The person decided: translate “{q['term']}” as “{target}”" + (f" ({note})" if note and note != target else "")
                    + ". This overrides any other note about this term.")
        elif note:  # a note alone explains the meaning
            ids = set(q.get("segment_ids") or [])
            text = f"The person explains “{q['term']}”: {note}. Make the translation say this."
        else:
            continue
        fixes += [{"segment_id": s["id"], "severity": "major", "category": "terminology", "note": text}
                  for s in segments if s["id"] in ids and s.get("translatable", True) and not st.is_frozen(s)
                  and not (target and _says(s.get("target"), target))]
    return fixes


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

    review_format = prompts.REVIEW_FORMAT_JSON if structured.enabled("review", ctx.state) else prompts.REVIEW_FORMAT_TAGS
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
            evidence=references.evidence_text(ctx.state, batch),
            tm=tm_memory.reference_lines(batch, ctx.state.get("doc:tm_refs") or {}),
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
    asking: list[str] = []
    if terms:
        before = {q["id"] for q in st.open_questions(ctx.state)}
        delta["doc:questions"] = st.add_questions(ctx.state, terms, origin="reviewer")
        # Asked before refining, while an answer can still be applied and reviewed (the round after the last refine
        # pass too: its answers get a refine pass of their own). Later ones wait for the person after the run.
        if round_no <= settings.review_max_rounds + 1:
            asking = [q["id"] for q in st.open_questions(delta) if q["id"] not in before]

    to_fix = issues_to_fix(issues, segments, round_no)
    go_refine = bool(to_fix) and round_no <= settings.review_max_rounds
    fixes = to_fix if go_refine else []
    summary = (
        f"Review round {round_no}: {len(issues)} issue{'s' if len(issues) != 1 else ''} ({majors} major)"
        if issues
        else f"Review round {round_no}: no issues found"
    )
    if asking:
        delta["doc:review_ask"] = {"round": round_no, "question_ids": asking, "issues": fixes}
        n = len(asking)
        yield say(summary + f" — {n} question{'s' if n != 1 else ''} for you first", state=delta)
        yield Event(output={"issues": fixes}, route="ask")
        return
    yield say(summary + (" — refining" if go_refine else ""), state=delta)
    yield Event(output={"issues": fixes}, route="refine" if go_refine else "done")


@node(name="review_questions", rerun_on_resume=True)
async def review_questions(ctx: Context, node_input: Any):
    """The reviewer's questions: pause for the person, then refine with their answers and the review's fixes (or
    hand over, when there is nothing to change)."""
    pending = ctx.state.get("doc:review_ask") or {}
    round_no = int(pending.get("round") or 1)
    interrupt = f"{REVIEW_INTERRUPT}_r{round_no}"
    asked = set(pending.get("question_ids") or [])
    open_qs = [q for q in st.open_questions(ctx.state) if q["id"] in asked]
    answers = (ctx.resume_inputs or {}).get(interrupt)
    if answers is None and open_qs:
        event, open_qs = await with_dictionary(ctx, open_qs, "Dictionary senses for the terms the reviewer asks about")
        if event:
            yield event
        n = len(open_qs)
        text = (f"The review raised {n} term{'s' if n != 1 else ''} I'm not sure about. I'll apply your "
                f"decision{'s' if n != 1 else ''} before the next review round. Each card explains the term and preselects "
                "my recommendation; skip to let me decide.")
        async for item in pause_for(interrupt, open_qs, text, stage="review"):
            yield item
        return

    questions, glossary, answered, kept = record_answers(ctx.state, open_qs, answers if isinstance(answers, dict) else {})
    termbase = st.without_terms(st.merge_termbase({"doc:glossary": glossary}, dict(ctx.state.get("doc:termbase") or {}), kept),
                                set(glossary))
    fixes = answer_fixes(questions, asked, st.get_segments(ctx.state))
    issues = list(pending.get("issues") or []) + fixes
    segs = len({x["segment_id"] for x in fixes})
    if answered:
        text = (f"Thanks! Applying {answered} answer{'s' if answered != 1 else ''}"
                + (f" to {segs} segment{'s' if segs != 1 else ''}" if segs else " (the translation already uses them)")
                + (" with the review's fixes" if pending.get("issues") else ""))
    else:  # skipped: the recommendations stay as unverified termbase entries (the polish applies them)
        text = "Leaving those to me" + (": applying the review's fixes" if issues else "")
    yield say(text, state={"doc:questions": questions, "doc:glossary": glossary, "doc:termbase": termbase,
                           "doc:review_ask": None, **progress_state("review", 0, 0, "Continuing…", "reviewing")})
    yield Event(output={"issues": issues}, route="refine" if issues else "done")


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
            output_format=prompts.REFINE_FORMAT_JSON if structured.enabled("refine", ctx.state) else prompts.REFINE_FORMAT_TAGS,
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

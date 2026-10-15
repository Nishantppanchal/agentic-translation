"""Translating page by page with carried context, the translation memory, and late questions (clarify)."""

from __future__ import annotations

import html
from dataclasses import dataclass
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
from ...integrations import dictionary
from ...models import structured
from ...models.replies import (
    parse_keeps,
    parse_segments,
    parse_terms,
    tag_body,
)
from ...quality import qa
from .. import prompts
from ..common import doc_langs, progress_state, reply_text, run_bounded, save_version, say, scope, user_message
from ..workers import translator
from .questions import pause_for, record_answers, segments_mentioning

CLARIFY_INTERRUPT = "clarify"


def _carried_context(segments: list[dict], before_id: str, translations: dict[str, str], max_chars: int) -> str:
    """Source + translation of the text just before `before_id`, newest last, within a char budget."""
    ids = [s["id"] for s in segments]
    idx = ids.index(before_id) if before_id in ids else 0
    parts: list[str] = []
    used = 0
    for seg in reversed(segments[:idx]):
        target = translations.get(seg["id"])
        if not seg["translatable"] or not target:
            continue
        block = f"[{seg['id']}] SOURCE: {seg['source']}\nTRANSLATION: {target}"
        if parts and used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(reversed(parts)) or "(start of document)"


def _page_context(segments: list[dict], batch: list[dict], max_chars: int) -> str:
    """For re-translating a few segments: the rest of their page(s) as already translated."""
    pages = {s["page"] for s in batch}
    skip = {s["id"] for s in batch}
    blocks = [
        f"[{s['id']}] SOURCE: {s['source']}\nTRANSLATION: {s.get('target') or ''}"
        for s in segments
        if s["page"] in pages and s["id"] not in skip and s["translatable"] and s.get("target")
    ]
    text = "\n\n".join(blocks)
    return text[-max_chars:] if text else "(no other text on this page)"


@dataclass
class BatchResult:
    translated: dict[str, str]  # segment id → translation
    terms: list[dict]  # flagged uncertain terms
    keeps: dict[str, str]  # terminology choices to carry forward
    detected: str | None  # detected source language
    brief: str | None  # updated document brief
    merged: set[str]  # ids that still look merged with a neighbour after the retry


def _parse_translation(text: str) -> BatchResult:
    """A translator reply: structured JSON when available, else the tag format."""
    obj = structured.parse_json(text)
    if obj is not None and "segments" in obj:
        brief = str(obj.get("brief") or "").strip()
        return BatchResult(
            translated=structured.segments_from(obj),
            terms=structured.terms_from(obj),
            keeps=structured.terminology_from(obj),
            detected=str(obj.get("source_language") or "").strip() or None,
            brief=brief[:1200] or None,
            merged=set(),
        )
    return BatchResult(
        translated=parse_segments(text),
        terms=parse_terms(text),
        keeps=parse_keeps(text),
        detected=tag_body(text, "source_lang"),
        brief=(tag_body(text, "brief") or "").strip()[:1200] or None,
        merged=set(),
    )


async def _translate_batch(
    ctx: Context,
    run_id: str,
    batch: list[dict],
    *,
    source_lang: str,
    target_lang: str,
    glossary: str,
    termbase: str,
    context: str,
    scope: str,
    brief: str = "",
    detect: bool = False,
    instructions: str = "(none)",
    tm: str = "(none)",
) -> BatchResult:
    """One translator call for a page (+ targeted retries for dropped and merged segments)."""
    max_terms = get_settings().max_questions_per_batch
    if structured.enabled("translate", ctx.state):
        output_format = prompts.TRANSLATE_FORMAT_JSON
    else:
        output_format = prompts.TRANSLATE_FORMAT_TAGS + (prompts.TRANSLATE_FORMAT_TAGS_DETECT if detect else "")

    def build(segs: list[dict], extra: str = "") -> str:
        return prompts.TRANSLATE.format(
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=glossary,
            termbase=termbase,
            brief=brief or "(start of document — no brief yet)",
            instructions=instructions,
            tm=tm,
            evidence=references.evidence_text(ctx.state, segs),
            max_terms=max_terms,
            context=context,
            scope=scope,
            segments="\n\n".join(f'<seg id="{s["id"]}"{_where(s)}>\n{s["source"]}\n</seg>' for s in segs),
            output_format=output_format,
        ) + extra

    async def call(segs: list[dict], suffix: str, extra: str = "") -> BatchResult:
        out = reply_text(await ctx.run_node(translator, node_input=user_message(build(segs, extra)), run_id=f"{run_id}{suffix}"))
        return _parse_translation(out)

    result = await call(batch, "")
    translated = dict(result.translated)

    missing = [s for s in batch if not translated.get(s["id"])]
    if missing:  # one retry with just the segments the model dropped
        retry = await call(missing, "-retry")
        translated.update({k: v for k, v in retry.translated.items() if v})
        result.terms += retry.terms

    merged = qa.suspect_merges(batch, translated)
    if merged:  # one retry for segments whose text looks shifted between neighbours
        retry = await call([s for s in batch if s["id"] in merged], "-split", prompts.TRANSLATE_SEPARATELY)
        candidate = {**translated, **{k: v for k, v in retry.translated.items() if k in merged and v}}
        still = qa.suspect_merges(batch, candidate)
        if len(still) < len(merged):
            translated, merged = candidate, still

    result.translated, result.merged = translated, merged
    result.terms = result.terms[:max_terms]
    result.detected = result.detected if detect else None
    return result


def _where(seg: dict) -> str:
    """Where an Office segment is ("Slide 3 · Title", "Sheet1!B4 · column …"): context for short texts."""
    return f' where="{html.escape(seg["where"], quote=True)}"' if seg.get("where") else ""


@node(rerun_on_resume=True)
async def translate(ctx: Context, node_input: Any):
    """Translate page by page, in order, carrying the previous text and the termbase forward."""
    settings = get_settings()
    segments = st.get_segments(ctx.state)
    # Segments that already have a translation (filled from the translation memory before the analysis) are kept;
    # fuzzy TM matches are references to adapt.
    batches = page_batches([s for s in segments if not s.get("target")], settings.page_max_chars)
    tm_refs: dict[str, dict] = ctx.state.get("doc:tm_refs") or {}
    total = len(batches)
    source_lang, target_lang = doc_langs(ctx.state)
    detect = source_lang.startswith("the source language")
    n_pages = len({s["page"] for b in batches for s in b})
    yield say(
        f"Translating {sum(len(b) for b in batches)} segments into {target_lang}, page by page ({n_pages} page{'s' if n_pages != 1 else ''})",
        state=progress_state("translate", 0, total, "Translating…", "translating"),
    )

    translations = {s["id"]: s["target"] for s in segments if s.get("target")}  # non-translatable = copied
    snap = {s["id"]: s.get("target") or "" for s in segments}
    termbase: dict[str, str] = dict(ctx.state.get("doc:termbase") or {})
    instructions = projects.instructions_for(ctx.state)
    brief = ctx.state.get("doc:brief") or ""

    all_terms: list[dict] = []
    part_of_page: dict[int, int] = {}
    flagged = 0
    decided = {k["term"].casefold() for k in ctx.state.get("doc:key_terms") or []}  # the analysis settled these

    for i, batch in enumerate(batches):
        page = batch[0]["page"]
        part_of_page[page] = part_of_page.get(page, 0) + 1
        multi = sum(1 for b in batches if b[0]["page"] == page) > 1
        result = await _translate_batch(
            ctx,
            f"translate-{i}",
            batch,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in batch]),
            instructions=instructions,
            tm=tm_memory.reference_lines(batch, tm_refs),
            termbase=st.termbase_text({"doc:termbase": termbase}),
            context=_carried_context(segments, batch[0]["id"], translations, settings.carry_context_chars),
            scope=scope(batch, part_of_page[page] if multi else None),
            brief=brief,
            detect=detect and i == 0,
        )
        # Models sometimes report made-up "terms" (e.g. "p1.7 fragment") or join two terms with "/".
        terms = [t for t in result.terms if qa.in_source(t["term"], batch) and t["term"].casefold() not in decided]
        result.keeps = {k: v for k, v in result.keeps.items() if qa.in_source(k, batch)}
        delta: dict[str, Any] = {}
        for seg in batch:
            produced = result.translated.get(seg["id"])
            # Fall back to the source text if the model dropped a segment; the flag forces a fix in review.
            target = produced or seg["source"]
            flags = qa.check_segment(seg, produced, merged=seg["id"] in result.merged)
            flagged += bool(flags)
            translations[seg["id"]] = target
            snap[seg["id"]] = target
            ref = tm_refs.get(seg["id"])  # a fuzzy match the translator adapted: machine translation, with its score
            delta[st.seg_key(seg["id"])] = st.apply_target(seg, target, origin="mt", status="draft", flags=flags,
                                                           match=ref["score"] if ref else None)
        if result.detected:
            source_lang = result.detected.strip()
            delta["doc:detected_lang"] = source_lang
        if result.brief:
            brief = result.brief
            delta["doc:brief"] = brief
        all_terms.extend(terms)
        # Uncertain guesses must not become "rules" for later pages.
        keeps = st.without_terms(result.keeps, {t["term"] for t in all_terms})
        if keeps:
            termbase = st.merge_termbase(ctx.state, termbase, keeps)
            delta["doc:termbase"] = termbase
        if terms:
            delta["doc:questions"] = st.add_questions(ctx.state, all_terms, origin="translator")
        delta.update(progress_state("translate", i + 1, total, f"Translated {scope(batch)} ({i + 1}/{total})"))
        yield Event(state=delta)

    version_delta = await save_version(ctx, "Draft translation", [s["id"] for s in segments if s["translatable"]], snap)
    open_q = len(st.open_questions(ctx.state))
    msg = "Draft translation ready (v1)"
    if termbase:
        msg += f"; {len(termbase)} term{'s' if len(termbase) != 1 else ''} kept consistent across pages"
    if open_q:
        msg += f" — {open_q} term{'s' if open_q != 1 else ''} flagged for clarification"
    if flagged:
        msg += f" — {flagged} segment{'s' if flagged != 1 else ''} need{'s' if flagged == 1 else ''} a fix in review"
    yield say(msg, state={**version_delta, "doc:review_round": 0, "doc:review_report": []})
    yield Event(output={"batches": total})


@node(rerun_on_resume=True)
async def clarify(ctx: Context, node_input: Any):
    """Terms the translator still couldn't resolve after the analysis: pause once; answers re-translate the
    segments that use them."""
    settings = get_settings()
    open_qs = st.open_questions(ctx.state)
    if not open_qs:
        yield Event(output={"clarified": 0})
        return

    answers = (ctx.resume_inputs or {}).get(CLARIFY_INTERRUPT)
    if answers is None:
        # The dictionary on the translator's late terms (the analysis's were looked up already), in one call.
        missing = [q for q in open_qs if not q.get("dictionary")]
        if missing and references.dictionary_on(ctx.state):
            source_lang, _ = doc_langs(ctx.state)
            hits = await dictionary.lookup([q["term"] for q in missing], source_lang)
            questions = [dict(q) for q in ctx.state.get("doc:questions") or []]
            ids = {q["id"] for q in missing}
            for q in questions:
                if q["id"] in ids and (entries := hits.get(q["term"])):
                    q["dictionary"] = entries
                    references.add_dictionary_options(q)
            results = [{"query": q["term"], "entries": [references.dictionary_entry(e) for e in q["dictionary"][:3]]}
                       for q in questions if q["id"] in ids and q.get("dictionary")]
            yield references.lookup_event(
                references.lookup_payload("dictionary", "Dictionary senses for the terms the translator asks about", results,
                                          queries=len(missing)),
                f"Dictionary: {len(results)} of {len(missing)} term{'s' if len(missing) != 1 else ''} found",
                state={"doc:questions": questions})
            open_qs = st.open_questions({"doc:questions": questions})  # (ADK State is not a Mapping to spread)
        n = len(open_qs)
        text = (f"Before the review pass I need your help with {n} term{'s' if n != 1 else ''} I wasn't sure about. "
                "Each card explains the term and preselects my recommendation; skip to keep my guesses.")
        async for item in pause_for(CLARIFY_INTERRUPT, open_qs, text):
            yield item
        return

    # Resumed with {question_id: {"target", "note"} | null}.
    questions, glossary, answered, kept = record_answers(ctx.state, open_qs, answers if isinstance(answers, dict) else {})
    segments = st.get_segments(ctx.state)
    affected: set[str] = set()
    for q in open_qs:
        if q["term"] in glossary:
            affected |= set(q["segment_ids"]) | segments_mentioning(segments, q["term"])

    termbase = st.without_terms(st.merge_termbase({"doc:glossary": glossary}, dict(ctx.state.get("doc:termbase") or {}), kept),
                                set(glossary))
    if not answered:
        yield say("Keeping my best guesses.", state={"doc:questions": questions, "doc:termbase": termbase,
                                                       **progress_state("clarify", 0, 0, "Continuing…", "reviewing")})
        yield Event(output={"clarified": 0})
        return

    targets = [s for s in segments if s["id"] in affected and s["translatable"] and not st.is_frozen(s)]
    batches = page_batches(targets, settings.page_max_chars)
    total = len(batches)
    termbase_text = st.termbase_text(ctx.state)
    source_lang, target_lang = doc_langs(ctx.state)
    yield say(
        f"Thanks! Applying {answered} answer{'s' if answered != 1 else ''}: re-translating {len(targets)} segment{'s' if len(targets) != 1 else ''}",
        state={
            "doc:questions": questions,
            "doc:glossary": glossary,
            "doc:termbase": termbase,
            **progress_state("clarify", 0, total, "Applying your answers…", "translating"),
        },
    )

    snap = st.snapshot(ctx.state)
    changed: list[str] = []
    done = 0
    tm_refs: dict[str, dict] = ctx.state.get("doc:tm_refs") or {}
    tasks = [
        lambda i=i, b=b: _translate_batch(
            ctx,
            f"clarify-{i}",
            b,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in b], glossary),
            termbase=termbase_text,
            context=_page_context(segments, b, settings.carry_context_chars * 2),
            scope=f"{scope(b)} — re-translate these segments only, applying the glossary",
            brief=ctx.state.get("doc:brief") or "",
            instructions=projects.instructions_for(ctx.state),
            tm=tm_memory.reference_lines(b, tm_refs),
        )
        for i, b in enumerate(batches)
    ]
    async for i, result in run_bounded(tasks, settings.max_concurrency):
        done += 1
        delta: dict[str, Any] = {}
        for seg in batches[i]:
            new = result.translated.get(seg["id"])
            if new and new != seg.get("target"):
                delta[st.seg_key(seg["id"])] = st.apply_target(seg, new, origin="mt", status="draft",
                                                               match=(tm_refs.get(seg["id"]) or {}).get("score"))
                snap[seg["id"]] = new
                changed.append(seg["id"])
        delta.update(progress_state("clarify", done, total, f"Re-translated {scope(batches[i])} ({done}/{total})"))
        yield Event(state=delta)

    version_delta = await save_version(ctx, "Applied your clarifications", changed, snap) if changed else {}
    yield say(f"Updated {len(changed)} segment{'s' if len(changed) != 1 else ''} with your answers", state=version_delta)
    yield Event(output={"clarified": answered})

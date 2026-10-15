"""Before translating: the whole-document analysis (brief, key terms) and the questions it raises."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, NamedTuple

from google.adk import Context, Event
from google.adk.workflow import node

from ... import projects, references
from ...config import get_settings
from ...document import state as st
from ...document.pages import (
    batch_segments,
)
from ...integrations import dictionary
from ...models import structured
from ...models.llm import error_text
from ...models.replies import (
    parse_terms,
    tag_body,
)
from ...quality import qa
from .. import prompts
from ..common import doc_langs, progress_state, reply_text, say, scope, user_message
from ..workers import analyst
from .questions import pause_for, record_answers, segments_mentioning

log = logging.getLogger(__name__)


ASK_INTERRUPT = "ask"


class Analysis(NamedTuple):
    lang: str | None
    brief: str | None
    terms: list[dict]
    title: str | None = None  # an English title for the document (sidebar, header)
    summary: str | None = None  # what it says, in two sentences


def _parse_analysis(text: str) -> Analysis:
    """An analyst reply → its parts. JSON first, tags as fallback."""
    obj = structured.parse_json(text)
    if obj is not None and ("terms" in obj or "brief" in obj):
        def field(key: str) -> str | None:
            return str(obj.get(key) or "").strip() or None

        return Analysis(field("source_language"), field("brief"), structured.terms_from(obj, "terms"), _title(field("title")),
                        field("summary"))
    return Analysis(tag_body(text, "source_lang"), tag_body(text, "brief"), parse_terms(text), _title(tag_body(text, "title")),
                    tag_body(text, "summary"))


def _title(text: str | None) -> str | None:
    """One line, no quotes or trailing full stop."""
    text = " ".join((text or "").split()).strip(" \"'“”‘’").rstrip(".")
    return text[:120] or None


@node(rerun_on_resume=True)
async def analyse(ctx: Context, node_input: Any):
    """Read the whole document before translating: the brief up front, key terms fixed once (definitions
    found anywhere in the document count), and the terms whose options differ in meaning turned into
    questions for `ask`. Optional: if the analysis fails, translation goes ahead page by page as before."""
    settings = get_settings()
    segments = st.get_segments(ctx.state)
    todo = [s for s in segments if s["translatable"] and not s.get("target")]
    if not settings.analysis_enabled or not todo:
        yield Event(output={"terms": 0})
        return
    chunks = batch_segments(todo, settings.analysis_chunk_chars)
    source_lang, target_lang = doc_langs(ctx.state)
    yield say(
        "Reading the whole document first, to fix key terms and find what to ask you",
        state=progress_state("analyse", 0, len(chunks), "Reading the whole document…", "translating"),
    )
    # Approved terms are settled; proposed ones (accepted recommendations) may be asked about again.
    settled = [t for t in qa.terms_for(ctx.state, [s["source"] for s in todo]) if t.get("status") != "proposed"]
    decided = {t["source"].casefold() for t in settled}
    brief, detected = ctx.state.get("doc:brief") or "", None
    title, summary = ctx.state.get("doc:title") or "", ctx.state.get("doc:abstract") or ""
    found: dict[str, dict] = {}
    fmt = prompts.ANALYSE_FORMAT_JSON if structured.enabled("analyse", ctx.state) else prompts.ANALYSE_FORMAT_TAGS
    for i, chunk in enumerate(chunks):
        prompt = prompts.ANALYSE.format(
            source_lang=source_lang,
            target_lang=target_lang,
            max_terms=settings.analysis_max_terms,
            max_questions=settings.max_questions,
            term_fields=prompts.TERM_FIELDS.format(source_lang=source_lang),
            instructions=projects.instructions_for(ctx.state),
            glossary=projects.glossary_for(ctx.state, [s["source"] for s in chunk]),
            brief=brief or "(start of document)",
            title_so_far=f"{title} — {summary}" if title or summary else "(none yet)",
            scope=scope(chunk, i + 1 if len(chunks) > 1 else None),
            segments="\n\n".join(f'<seg id="{s["id"]}">\n{s["source"]}\n</seg>' for s in chunk),
            output_format=fmt,
        )
        try:
            out = reply_text(await ctx.run_node(analyst, node_input=user_message(prompt), run_id=f"analyse-{i}"))
        except Exception as exc:  # the analysis only helps; never block the translation on it — but say so
            error = error_text(exc)
            log.warning("analysis of part %d failed: %s", i + 1, error)
            part = f" (part {i + 1} of {len(chunks)})" if len(chunks) > 1 else ""
            hint = (" Lower `ANALYSIS_CHUNK_CHARS` in backend/.env to send it in smaller parts."
                    if re.search(r"context length|context window|ContextWindowExceeded", error, re.I) else "")
            yield say(f"**Note:** I couldn't read the whole document first{part}, so I'll translate without fixing its "
                       f"key terms or asking you about them.{hint} Error: {error}", kind="assistant")
            continue
        lang, new_brief, terms, new_title, new_summary = _parse_analysis(out)
        detected, brief = detected or lang, (new_brief or brief)[:1500]
        title, summary = new_title or title, (" ".join((new_summary or "").split()) or summary)[:600]
        for term in terms:
            key = term["term"].casefold()
            if key in decided or key in found or not qa.in_source(term["term"], todo):
                continue  # already in the glossary/termbase, a duplicate, or not actually in the text
            term["segment_ids"] = [s["id"] for s in todo if s["id"] in segments_mentioning(todo, term["term"])]
            found[key] = term
        yield Event(state=progress_state("analyse", i + 1, len(chunks), f"Read part {i + 1} of {len(chunks)}"))

    # The references, in their order of precedence (the termbase and earlier answers settled their terms above):
    # how the translation memory translated each key term, then what the dictionary says.
    names = [t["term"] for t in found.values()]
    examples = await asyncio.to_thread(references.tm_examples, ctx.state, names) if names else {}
    hits = await dictionary.lookup(names, detected or source_lang) if names and references.dictionary_on(ctx.state) else None
    for term in found.values():
        term["tm"] = examples.get(term["term"], [])
        if entries := (hits or {}).get(term["term"]):
            term["dictionary"] = entries
            if term.get("ambiguous"):
                references.add_dictionary_options(term)  # sourced meanings for the question card
    asks = [t for t in found.values() if t.get("ambiguous")][: settings.max_questions]
    asked = {t["term"].casefold() for t in asks}
    decision: dict[str, str] = {}
    for key, term in found.items():
        if key in asked:
            decision[key] = references.reconcile(term, False)  # a question: a TM-backed option is recommended
            continue
        if term.get("ambiguous"):  # more questions than may be asked: decided from the evidence instead
            term["ambiguous"] = False
        decision[key] = references.reconcile(term, len(asks) < settings.max_questions)
        if decision[key] == "asked":
            asks.append(term)
            asked.add(key)
    clear = {t["term"]: t["guess"] for t in found.values() if t["term"].casefold() not in asked and t["guess"]}
    delta: dict[str, Any] = {
        "doc:key_terms": [
            {"term": t["term"], "target": t["guess"], "meaning": t.get("meaning", ""), "asked": key in asked,
             "dictionary": t.get("dictionary", []), "tm": t.get("tm", []), "decision": decision[key],
             **({"note": t["note"]} if t.get("note") else {})}
            for key, t in found.items()
        ],
        "doc:termbase": st.merge_termbase(ctx.state, dict(ctx.state.get("doc:termbase") or {}), clear),
    }
    for event in _lookup_events(settled, found, decision, examples, hits, len(names)):
        yield event
    if brief:
        delta["doc:brief"] = brief
    if title:
        delta["doc:title"] = title
    if summary:
        delta["doc:abstract"] = summary
    if detected and (ctx.state.get("doc:source_lang") or "auto").lower().startswith("auto"):
        delta["doc:detected_lang"] = detected.strip()
    if asks:
        delta["doc:questions"] = st.add_questions(ctx.state, asks, origin="analysis")
    msg = f"Read the document: {len(found)} key term{'s' if len(found) != 1 else ''} fixed for the whole translation"
    if asks:
        msg += f"; {len(asks)} need{'s' if len(asks) == 1 else ''} your decision before I translate"
    yield say(msg, state=delta)
    yield Event(output={"terms": len(found), "questions": len(asks)})


OUTCOME = {"tm": "as in the TM", "dictionary": "dictionary agrees", "asked": "asked you", "conflict": "AI's guess kept",
           "ai": "AI's guess"}


def _lookup_events(settled: list[dict], found: dict[str, dict], decision: dict[str, str], examples: dict, hits: dict | None,
                   queries: int):
    """The lookups the analysis made, as chat items: what the termbase settled, what the TM and the dictionary say."""
    if settled:
        results = [{"query": t["source"], "entries": [{"target": t.get("target", ""), "badge": t.get("status") or "glossary"}]}
                   for t in settled[:20]]
        yield references.lookup_event(
            references.lookup_payload("termbase", "Terms already decided (project termbase, your answers)", results),
            f"Termbase: {len(settled)} term{'s' if len(settled) != 1 else ''} already decided")
    if examples:
        results = [{"query": k_t["term"], "entries": [{"source_text": x["source"], "target": x["target"], "ref": x["ref"]} for x in ex],
                    "outcome": OUTCOME[decision[k]]}
                   for k, k_t in found.items() if (ex := examples.get(k_t["term"]))]
        yield references.lookup_event(
            references.lookup_payload("tm", "How the translation memory translated the key terms", results, queries=queries),
            f"Translation memory: {len(results)} of {queries} key terms used before")
    if hits is not None:
        results = [{"query": t["term"], "entries": [references.dictionary_entry(e) for e in t["dictionary"][:3]],
                    "outcome": OUTCOME[decision[k]]} for k, t in found.items() if t.get("dictionary")]
        yield references.lookup_event(
            references.lookup_payload("dictionary", "Dictionary senses for the key terms", results, queries=queries),
            f"Dictionary: {len(results)} of {queries} key terms found")


@node(rerun_on_resume=True)
async def ask(ctx: Context, node_input: Any):
    """The analysis's questions, before translating. Answers go into the glossary, so the translation uses
    them from the first page and nothing needs re-translating."""
    open_qs = [q for q in st.open_questions(ctx.state) if q.get("origin") == "analysis"]
    if not open_qs:
        yield Event(output={"answered": 0})
        return
    answers = (ctx.resume_inputs or {}).get(ASK_INTERRUPT)
    if answers is None:
        n = len(open_qs)
        text = (f"Before I translate, please decide {n} term{'s' if n != 1 else ''}. Each card explains the term in plain "
                "English and preselects my recommendation, so **Accept all recommendations** is fine if you're unsure.")
        async for item in pause_for(ASK_INTERRUPT, open_qs, text):
            yield item
        return
    questions, glossary, answered, kept = record_answers(ctx.state, open_qs, answers if isinstance(answers, dict) else {})
    termbase = st.without_terms(st.merge_termbase({"doc:glossary": glossary}, dict(ctx.state.get("doc:termbase") or {}), kept),
                                set(glossary))
    msg = (f"Thanks! {answered} term{'s' if answered != 1 else ''} decided; translating with "
           f"{'it' if answered == 1 else 'them'}" if answered else "Using my recommendations")
    yield say(msg, state={"doc:questions": questions, "doc:glossary": glossary, "doc:termbase": termbase,
                           **progress_state("translate", 0, 0, "Translating…", "translating")})
    yield Event(output={"answered": answered})

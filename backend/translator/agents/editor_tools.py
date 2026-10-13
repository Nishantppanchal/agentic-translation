"""Function tools the editor agent uses to inspect and change the translation.

Changes are never applied directly: they are staged in `doc:proposal`, which the
UI shows as a diff for the user to accept or reject (see `translator.proposals`).
Reads always return the *effective* text (committed + pending proposal), so the
agent can refine a pending proposal over several turns.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from google.adk.models.llm_request import LlmRequest
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

from ..document import proposals, source_check
from ..document import state as st
from ..document.pages import IMAGE_EXTS, guess_mime, render_page
from ..integrations import dictionary
from ..models.replies import term_from
from ..ocr import layout
from ..quality import qa
from ..text import match_case, term_pattern
from . import prompts

MAX_RESULTS = 20
PROPOSED = "Proposed — the user will review the diff and accept or reject it."


def _view(seg: dict) -> dict:
    view = {"id": seg["id"], "page": seg["page"], "source": seg["source"], "translation": seg.get("target") or ""}
    if seg.get("pending"):
        view["pending_approval"] = True
    return view


def _proposal(state) -> dict:
    return proposals.open_proposal(state)


def _save(state, proposal: dict) -> None:
    state["doc:proposal"] = proposals.close_proposal(proposal)


def _locked(state, segment_id: str) -> bool:
    return bool(st.normalize(st.get_segment(state, segment_id) or {}).get("locked"))


def _stage(state, segment_id: str, field: str, after: str, alternatives: list[dict] | None = None) -> bool:
    """Stage `field` of a segment; staging the committed text again drops the change. Returns changed?"""
    proposal = _proposal(state)
    changed = proposals.stage_change(proposal, state, segment_id, field, after, alternatives)
    _save(state, proposal)
    return changed


def search_segments(query: str, tool_context: ToolContext) -> dict:
    """Find segments whose source text or translation contains `query` (case-insensitive).

    Args:
      query: Word or phrase to look for, in either language.

    Returns:
      Up to 20 matching segments with their ids, source text and translation (including pending proposals).
    """
    q = query.casefold()
    hits = [
        _view(s)
        for s in st.effective_segments(tool_context.state)
        if q in s["source"].casefold() or q in (s.get("target") or "").casefold()
    ]
    return {"count": len(hits), "segments": hits[:MAX_RESULTS]}


def get_segments(segment_ids: list[str], tool_context: ToolContext) -> dict:
    """Read the full source text and translation of specific segments (including pending proposals).

    Args:
      segment_ids: Segment ids such as ["p1.3", "p2.1"].
    """
    found, missing = [], []
    for sid in segment_ids:
        seg = st.get_segment(tool_context.state, sid.strip())
        if seg:
            found.append(_view(st.effective_segment(tool_context.state, seg)))
        else:
            missing.append(sid)
    return {"segments": found, "missing": missing}


def update_segment(segment_id: str, new_translation: str, tool_context: ToolContext) -> dict:
    """Propose a new translation for one segment (rewording, tone, fixing errors).

    Args:
      segment_id: The segment to change, e.g. "p2.4".
      new_translation: The complete new translation of the segment (markdown preserved).
    """
    if not st.get_segment(tool_context.state, segment_id.strip()):
        return {"status": "error", "message": f"No segment {segment_id}."}
    if _locked(tool_context.state, segment_id.strip()):
        return {"status": "error", "message": f"Segment {segment_id} is locked by the user; leave it unchanged."}
    changed = _stage(tool_context.state, segment_id.strip(), "target", new_translation)
    return {"status": "proposed" if changed else "unchanged", "segment_id": segment_id, "note": PROPOSED}


def propose_alternatives(segment_id: str, alternatives: list[str], notes: list[str], tool_context: ToolContext) -> dict:
    """Offer 2-4 alternative translations for one segment; the user picks one (or none) when accepting.
    Use this when the user asks for options, or when there are genuinely different good ways to say it.

    Args:
      segment_id: The segment, e.g. "p2.4".
      alternatives: Complete alternative translations, best first.
      notes: One short note per alternative saying what is different (e.g. "more formal"), same order.
    """
    seg = st.get_segment(tool_context.state, segment_id.strip())
    if not seg:
        return {"status": "error", "message": f"No segment {segment_id}."}
    if _locked(tool_context.state, segment_id.strip()):
        return {"status": "error", "message": f"Segment {segment_id} is locked by the user; leave it unchanged."}
    options = []
    for i, text in enumerate(alternatives):
        options.append({"text": text, "note": notes[i] if i < len(notes) else ""})
    if not options:
        return {"status": "error", "message": "No alternatives given; try again."}
    changed = _stage(tool_context.state, segment_id.strip(), "target", options[0]["text"], options)
    return {"status": "proposed" if changed else "unchanged", "options": len(options), "note": PROPOSED}


def add_comment(segment_id: str, text: str, tool_context: ToolContext) -> dict:
    """Leave a comment on a segment for the translator or reviewer (a question, a caveat, a reminder).
    Comments are notes, not changes: they don't alter the translation.

    Args:
      segment_id: The segment, e.g. "p2.4".
      text: The comment.
    """
    key = st.seg_key(segment_id.strip())
    seg = st.get_segment(tool_context.state, segment_id.strip())
    if not seg or not text.strip():
        return {"status": "error", "message": f"No segment {segment_id}." if not seg else "Empty comment."}
    seg = st.normalize(seg)
    comment = {"id": uuid.uuid4().hex[:8], "role": "agent", "text": text.strip(), "at": time.time(), "resolved": False}
    tool_context.state[key] = {**seg, "comments": [*seg["comments"], comment]}
    return {"status": "added", "segment_id": segment_id}


def replace_in_translation(find: str, replace: str, segment_ids: list[str], tool_context: ToolContext) -> dict:
    """Propose a find-and-replace across the translation (e.g. switch a term everywhere).

    Matches whole words (any position for Chinese/Japanese/Thai text) case-insensitively and keeps each occurrence's capitalisation
    (Defects → Deficiencies, defects → deficiencies). Inflected forms (plural/singular,
    grammatical case) may still need their own call or `update_segment`.

    Args:
      find: Exact text currently in the translation.
      replace: Text to put instead.
      segment_ids: Limit to these segments; pass an empty list for the whole document.
    """
    if not find:
        return {"status": "error", "message": "Nothing to find."}
    pattern = term_pattern(find)
    scope = set(segment_ids)
    changed = []
    for seg in st.effective_segments(tool_context.state):
        if scope and seg["id"] not in scope:
            continue
        new, n = pattern.subn(lambda m: match_case(m.group(0), replace), seg.get("target") or "")
        if n and _stage(tool_context.state, seg["id"], "target", new):
            changed.append(seg["id"])
    return {"proposed_in": changed, "count": len(changed), "note": PROPOSED}


def set_glossary_term(source_term: str, translation: str, note: str, tool_context: ToolContext) -> dict:
    """Propose a glossary entry: how a source term must be translated (applied with the proposal).

    Args:
      source_term: The term in the source language.
      translation: The required translation.
      note: Short explanation (meaning, context), or an empty string.
    """
    proposal = _proposal(tool_context.state)
    proposal["glossary"][source_term] = {"target": translation, "note": note}
    _save(tool_context.state, proposal)
    return {"status": "proposed", "note": PROPOSED}


def resolve_question(question_id: str, answer: str, tool_context: ToolContext) -> dict:
    """Mark an open clarification question as answered (bookkeeping; applies immediately).

    Args:
      question_id: The question id, e.g. "q2".
      answer: The user's answer, summarised.
    """
    questions = [dict(q) for q in tool_context.state.get("doc:questions") or []]
    for q in questions:
        if q["id"] == question_id:
            q["status"], q["answer"] = "resolved", answer
            tool_context.state["doc:questions"] = questions
            return {"status": "resolved", "term": q["term"], "segment_ids": q["segment_ids"]}
    return {"status": "error", "message": f"No question {question_id}."}


def ask_user_about_term(
    term: str, meaning: str, options: list[str], segment_ids: list[str], why: str, tool_context: ToolContext
) -> dict:
    """Ask the user to decide how to translate a source term. Shows a question card; the user answers later.
    The user may not read the source language, so explain the term and offer English options.

    Args:
      term: The source-language term you are unsure about.
      meaning: One plain-English sentence on what the term refers to.
      options: One to three English translations, your recommendation first.
      segment_ids: Segments where the term appears.
      why: One sentence on why the choice matters.
    """
    found = term_from({"source": term, "meaning": meaning, "options": options, "segment_ids": segment_ids, "reason": why})
    if not found:
        return {"status": "error", "message": "A question needs the source term."}
    tool_context.state["doc:questions"] = st.add_questions(tool_context.state, [found], origin="editor")
    return {"status": "asked", "note": "The user will answer via the question card. Continue with your best guess."}


READINGS = "temp:page_readings"  # what the OCR model read in this turn: text the editor may put into the source


def _not_in_review(state) -> dict | None:
    if not source_check.in_review(state):
        return {"status": "error", "message": "Page fixes are only for the source check before translating; now use "
                                              "reread_page to have the page read, then fix_source_segment per segment."}
    return None


def _stage_page(state, page: int, markdown: str, reason: str, origin: str) -> dict:
    if page not in source_check.pages(state):
        return {"status": "error", "message": f"No page {page}."}
    fix = source_check.stage(state, page, markdown, reason, origin)
    if fix is None:
        return {"status": "unchanged", "page": page, "note": "That is what the page already says."}
    state[source_check.FIXES] = {**(state.get(source_check.FIXES) or {}), str(page): fix}
    out = {"status": "proposed", "page": page, "note": "The user sees the page before and after and accepts or rejects it."}
    if fix["word_changes"]:
        out["word_changes"] = fix["word_changes"][:12]
        out["warning"] = "These words would change: make sure the user asked for that or the page image shows it."
    if fix["moved"]:
        out["moved"] = fix["moved"]
        out["moved_note"] = "These passages change place: tell the user to check the reading order against the page image."
    return out


def _unread_text(tool_context: ToolContext, before: str, after: str) -> dict | None:
    """Refuse source text that nobody read off the page: what the editor adds must already be in the document as
    read, or be what the user wrote. New text from the page is the OCR model's job (reread_page)."""
    user = "".join(p.text or "" for p in (tool_context.user_content.parts or [])) if tool_context.user_content else ""
    sources = [user, *tool_context.state.get(READINGS, []), *(seg["source"] for seg in st.get_segments(tool_context.state))]
    unread = source_check.unsourced_text(after, [before, *sources])
    if not unread:
        return None
    return {"status": "refused", "unread": unread,
            "message": "This text is neither in the document as it was read nor in what the user wrote, so it can't "
                       "go into the source from you: " + "; ".join(unread) + ". Text on the page must be read by the "
                       "OCR model: call reread_page (any time) with a precise instruction (e.g. \"read the attachments line under "
                       "the seal character by character\"). If the user tells you the exact words, use them exactly "
                       "as they wrote them."}


def get_page_source(page_number: int, tool_context: ToolContext) -> dict:
    """The SOURCE text of one page as OCR markdown: `[[HEADER]]` / `[[FOOTER]]` lines, `[[FIGURE n]]` for pictures,
    `#` headings, pipe tables, paragraphs separated by a blank line. Use it before proposing a page fix.

    Args:
      page_number: The page (1-based).
    """
    state = tool_context.state
    if page_number not in source_check.pages(state):
        return {"status": "error", "message": f"No page {page_number}; pages: {source_check.pages(state)}."}
    pending = (state.get(source_check.FIXES) or {}).get(str(page_number))
    return {"page": page_number, "markdown": source_check.page_markdown(state, page_number),
            **({"pending_fix": pending["after"]} if pending else {})}


def propose_page_source(page_number: int, corrected_markdown: str, reason: str, tool_context: ToolContext) -> dict:
    """Propose the corrected SOURCE of a page, during the source check before translating: the whole page as OCR
    markdown (same format as get_page_source). For structure the OCR got wrong — a paragraph split at a column,
    columns in the wrong order, a stamp's text inside a sentence, a broken table. Keep every word unless the user
    says it is wrong.

    Args:
      page_number: The page (1-based).
      corrected_markdown: The complete corrected page.
      reason: One sentence: what you fixed.
    """
    state = tool_context.state
    if (refused := _not_in_review(state)) is not None:
        return refused
    if page_number in source_check.pages(state):
        refused = _unread_text(tool_context, source_check.page_markdown(state, page_number), corrected_markdown)
        if refused:
            return refused
    return _stage_page(state, page_number, corrected_markdown, reason, "editor")


async def reread_page(page_number: int, instruction: str, tool_context: ToolContext) -> dict:
    """Have the OCR model (a vision model) read a page again with an instruction. Use it when text is misread or
    missing, or the order is too tangled to fix by hand.
    During the source check, the reading is proposed as the page's new source (a page fix). After it, nothing is
    changed: you get the reading back, and its text may then go into the source — fix the affected segments with
    fix_source_segment, then propose their new translations with update_segment.

    Args:
      page_number: The page (1-based).
      instruction: What to do differently, from what the user said, e.g. "two columns: read the left column to
        the end, then the right one; the red stamp is not part of the text".
    """
    from ..models.llm import build_model, error_text

    state = tool_context.state
    if page_number not in source_check.pages(state):
        return {"status": "error", "message": f"No page {page_number}; pages: {source_check.pages(state)}."}
    image = await _page_image(tool_context, page_number)
    if image is None:
        return {"status": "error", "message": f"No page image for page {page_number}."}
    request = LlmRequest(contents=[types.Content(role="user", parts=[
        image,
        types.Part(text=f"Transcribe page {page_number}." + prompts.REREAD_PAGE.format(
            instruction=instruction.strip(), previous=source_check.page_markdown(state, page_number)))])])
    request.config.system_instruction = prompts.VISION_OCR
    try:
        replies = [r async for r in build_model("ocr").generate_content_async(request)]
    except Exception as e:
        return {"status": "error", "message": f"Reading the page again failed: {error_text(e)}"}
    from ..models.replies import clean

    # Not the model's thinking: a reasoning model's arrives as thought parts (OpenRouter's `reasoning`, vLLM's
    # reasoning parser) and would otherwise open the page.
    markdown = clean("".join(p.text or "" for r in replies if r.content for p in r.content.parts or [] if not p.thought))
    state[READINGS] = [*state.get(READINGS, []), markdown]
    if source_check.in_review(state):
        return _stage_page(state, page_number, markdown, f"Read again: {instruction.strip()}", "reread")
    return {"status": "read", "page": page_number, "reading": markdown,
            "next": "Compare it with the page's segments (get_segments). Fix each misread segment with fix_source_segment "
                    "using the text exactly as read here, then propose its translation with update_segment. Change only "
                    "what the user asked about."}


async def _page_image(tool_context: ToolContext, page_number: int) -> types.Part | None:
    """The page as an image the model can see (PDF pages rendered; an uploaded image as it is)."""
    state = tool_context.state
    source = await tool_context.load_artifact(state.get("doc:source_artifact"))
    filename = state.get("doc:filename", "")
    png = render_page(source.inline_data.data, filename, page_number) if source and source.inline_data else None
    if png is None:
        return None
    is_upload = any(filename.lower().endswith(ext) for ext in IMAGE_EXTS)
    return types.Part.from_bytes(data=png, mime_type=guess_mime(filename) if is_upload else "image/png")


class LookAtPage(BaseTool):
    """Shows the editor a page image. A tool result can only carry text through OpenAI-compatible APIs, so the
    call answers briefly and the image itself is added to the model's next request (as ADK's load_artifacts
    does); it isn't kept in the session."""

    def __init__(self) -> None:
        super().__init__(
            name="look_at_page",
            description=(
                "See the image of a page of the uploaded document (a PDF page or the uploaded image). Look before "
                "you propose a page fix or fix a segment's source, and whenever the user asks what the page shows. "
                "Use it to judge what is wrong (missing, out of order, inside a stamp, colours, layout); to get text "
                "read, use reread_page — don't transcribe small, stamped or handwritten text from the image yourself."
            ),
        )

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"page_number": types.Schema(type=types.Type.INTEGER, description="The page (1-based).")},
                required=["page_number"],
            ),
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> dict:
        page = args.get("page_number")
        if not isinstance(page, int) or await _page_image(tool_context, page) is None:
            pages = source_check.pages(tool_context.state)
            return {"status": "error", "message": f"No page image for page {page!r}; pages: {pages} (text documents have none)."}
        return {"status": "shown", "page": page, "note": f"The image of page {page} follows."}

    async def process_llm_request(self, *, tool_context: ToolContext, llm_request: LlmRequest) -> None:
        await super().process_llm_request(tool_context=tool_context, llm_request=llm_request)
        last = llm_request.contents[-1] if llm_request.contents else None
        for part in (last.parts or []) if last else []:
            response = part.function_response
            if response and response.name == self.name and (response.response or {}).get("status") == "shown":
                page = response.response["page"]
                image = await _page_image(tool_context, page)
                if image is not None:
                    llm_request.contents.append(
                        types.Content(role="user", parts=[types.Part(text=f"Page {page}:"), image]))


look_at_page = LookAtPage()


async def look_up_term(term: str, tool_context: ToolContext) -> dict:
    """Look a source-language term up in the dictionary service: English translations with their definition,
    domain and source. Use it before explaining or choosing a translation for a specialised term.

    Args:
      term: The term as it appears in the source text.
    """
    state = tool_context.state
    lang = state.get("doc:detected_lang") or state.get("doc:source_lang")
    entries = (await dictionary.lookup([term.strip()], lang)).get(term.strip(), [])
    if not entries:
        return {"status": "not found", "term": term, "note": "The dictionary has no entry; rely on context."}
    return {"status": "found", "term": term, "entries": entries}


def fix_source_segment(segment_id: str, corrected_source: str, tool_context: ToolContext) -> dict:
    """Propose a correction to an OCR error in the SOURCE text. Then propose the matching translation too.

    Args:
      segment_id: The segment whose source text is wrong.
      corrected_source: The corrected source-language text.
    """
    seg = st.get_segment(tool_context.state, segment_id.strip())
    if not seg:
        return {"status": "error", "message": f"No segment {segment_id}."}
    if (refused := _unread_text(tool_context, seg["source"], corrected_source)) is not None:
        return refused
    changed = _stage(tool_context.state, segment_id.strip(), "source", corrected_source)
    return {
        "status": "proposed" if changed else "unchanged",
        "segment_id": segment_id,
        "next": "Now propose the updated translation of this segment with update_segment.",
    }


async def inspect_page_layout(page_number: int, tool_context: ToolContext) -> dict:
    """Detect the layout of a SOURCE page with PP-DocLayout: titles, text blocks, tables, images, charts,
    seals, headers/footers, page numbers. Use it to check whether something on the page is missing from
    the translation (e.g. a table or figure) or to explain how the page is structured.

    Args:
      page_number: The page to inspect (1-based).
    """
    if not layout.available():
        return {"status": "unavailable", "message": "The layout server is not configured or failed to start."}
    state = tool_context.state
    source = await tool_context.load_artifact(state.get("doc:source_artifact"))
    if source is None or source.inline_data is None:
        return {"status": "error", "message": "Source document not found."}
    png = render_page(source.inline_data.data, state.get("doc:filename", ""), page_number)
    if png is None:
        return {"status": "error", "message": f"No page image for page {page_number}."}
    result = await layout.detect_layout(png, tool_context)
    if result is None:
        return {"status": "error", "message": "Layout detection failed."}
    w, h = result["width"], result["height"]
    regions = [
        {
            "label": r["label"],
            "score": r["score"],
            # Position as % of the page (left, top, right, bottom) is easier to reason about than pixels.
            "box_percent": [round(100 * r["box"][0] / w), round(100 * r["box"][1] / h), round(100 * r["box"][2] / w), round(100 * r["box"][3] / h)],
        }
        for r in result["regions"]
    ]
    segments = [
        {"id": s["id"], "kind": s["kind"], "starts_with": (s["source"] or "")[:60]}
        for s in st.get_segments(state)
        if s["page"] == page_number
    ]
    return {"status": "ok", "model": result.get("model"), "regions": regions, "segments_on_page": segments}


def run_qa_checks(tool_context: ToolContext) -> dict:
    """Run the automatic QA checks (numbers and dates, terminology and forbidden terms, markup,
    punctuation, consistency, untranslated text) on the translation, including pending proposals.

    Returns:
      Open issues (ignored ones are left out): segment id, check, severity (error | warning) and message.
    """
    found = [i for i in qa.document_qa(tool_context.state, st.effective_segments(tool_context.state)) if not i["ignored"]]
    issues = [{k: i[k] for k in ("segment_id", "check", "severity", "message")} for i in found]
    return {"count": len(issues), "issues": issues[:40], "note": "Errors are precise; warnings may be false alarms."}


EDITOR_TOOLS = [
    search_segments,
    get_segments,
    update_segment,
    replace_in_translation,
    set_glossary_term,
    resolve_question,
    ask_user_about_term,
    fix_source_segment,
    inspect_page_layout,
    run_qa_checks,
    propose_alternatives,
    add_comment,
    get_page_source,
    propose_page_source,
    reread_page,
    look_at_page,
] + ([look_up_term] if dictionary.enabled() else [])  # only offered when a dictionary is set up

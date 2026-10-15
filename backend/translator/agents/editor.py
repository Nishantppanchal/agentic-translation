"""Chat editor agent: answers questions and edits the translation through tools.

It runs with `include_contents='none'` (current turn only) and gets its context
from the instruction instead: the document (or an outline for long ones), the
glossary, open questions and a compact transcript of earlier chat turns. That
keeps the pipeline's bulky OCR/translation events out of its context window.
"""

from __future__ import annotations

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.genai import types

from .. import projects
from ..document import comments
from ..document import state as st
from ..models.llm import build_model
from . import prompts
from . import reference_tools
from .editor_tools import EDITOR_TOOLS
from .workers import StepAgent

EDITOR_NAME = "editor"
FULL_DOC_CHARS = 14000  # include the whole document in the prompt below this size
TRANSCRIPT_TURNS = 8


def _document_view(state) -> str:
    segments = st.effective_segments(state)  # includes the pending proposal, marked
    total = sum(len(s["source"]) + len(s.get("target") or "") for s in segments)
    if total <= FULL_DOC_CHARS:
        body = "\n\n".join(
            f'[{s["id"]}]{" (text inside figure " + str(s.get("figure")) + ")" if s.get("kind") == "figure" else ""}'
            f'{" (pending approval)" if s.get("pending") else ""}'
            f'{" (flags: " + ", ".join(s["flags"]) + ")" if s.get("flags") else ""}'
            "\n"
            f'SOURCE: {s["source"]}\nTRANSLATION: {s.get("target") or ""}'
            for s in segments
        )
        return f"Full document ({len(segments)} segments):\n\n{body}"
    outline = "\n".join(f'[{s["id"]}] {(s.get("target") or s["source"])[:90].replace(chr(10), " ")}' for s in segments)
    return (
        f"The document is long ({len(segments)} segments), so only an outline is shown. "
        f"Use get_segments / search_segments to read exact text before editing.\n\n{outline}"
    )


def _transcript(ctx: ReadonlyContext) -> str:
    """Earlier chat turns (user text + the assistant's final replies), excluding this invocation."""
    turns: list[str] = []
    for ev in ctx.session.events:
        if ev.invocation_id == ctx.invocation_id or not ev.content or ev.partial:
            continue
        text = "".join(p.text or "" for p in ev.content.parts or [] if p.text and not p.thought).strip()
        if not text:
            continue
        if ev.author == "user":
            turns.append(f"User: {text}")
        elif ev.author == EDITOR_NAME:
            turns.append(f"Assistant: {text}")
    return "\n".join(turns[-2 * TRANSCRIPT_TURNS :])


def editor_instruction(ctx: ReadonlyContext) -> str:
    state = ctx.state
    source = state.get("doc:source_lang") or "auto-detect"
    if source.lower().startswith("auto"):
        source = state.get("doc:detected_lang") or "the source language"
    instruction = prompts.EDITOR.format(
        filename=state.get("doc:filename", "document"),
        source_lang=source,
        target_lang=state.get("doc:target_lang", "English"),
        status=state.get("doc:status", "unknown"),
        brief=state.get("doc:brief") or "(none)",
        glossary=projects.glossary_for(state, [s["source"] for s in st.get_segments(state)], st.effective_glossary(state)),
        instructions=projects.instructions_for(state),
        termbase=st.termbase_text(state),
        questions=st.questions_text(state),
        comments=comments.open_text(state),
        references=reference_tools.available(state),
        proposal=st.proposal_text(state),
        last_outcome=_last_outcome(state),
        document_view=_document_view(state),
    )
    transcript = _transcript(ctx)
    if transcript:
        instruction += f"\n\nConversation so far:\n{transcript}"
    return instruction


def _last_outcome(state) -> str:
    last = state.get("doc:last_proposal")
    if not last:
        return "(none)"
    if last["outcome"] == "accepted":
        return f"The user ACCEPTED your proposal {last['id']}" + (f" (now v{last['version']})." if last.get("version") else ".")
    return f"The user REJECTED your proposal {last['id']}; nothing was changed. Don't re-propose it unless asked."


async def note_proposal_request(callback_context: CallbackContext) -> types.Content | None:
    """After each turn: remember which user request(s) the pending proposal answers (used as the version note)."""
    proposal = st.get_proposal(callback_context.state)
    if not proposal or not callback_context.user_content:
        return None
    text = "".join(p.text or "" for p in callback_context.user_content.parts or []).strip()
    if text and text not in proposal["notes"]:
        callback_context.state["doc:proposal"] = {**proposal, "notes": [*proposal["notes"], text]}
    return None


editor_agent = StepAgent(
    name=EDITOR_NAME,
    step="editor",
    model=build_model("editor"),
    instruction=editor_instruction,
    tools=EDITOR_TOOLS,
    include_contents="none",
    after_agent_callback=note_proposal_request,
)

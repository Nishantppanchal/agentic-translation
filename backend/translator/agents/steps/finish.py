"""Polish (consistency fixes) and finalize (the reviewed version, document ready)."""

from __future__ import annotations

import logging
from typing import Any

from google.adk import Context, Event
from google.adk.workflow import node

from ...document import state as st
from ...models.llm import error_text
from ..common import doc_langs, progress_state, save_version, say
from .review import already_used

log = logging.getLogger(__name__)


@node(rerun_on_resume=True)
async def polish(ctx: Context, node_input: Any):
    """Before handing over: one translation per repeated sentence and the termbase applied. This is still
    the AI draft, so the fixes are applied directly (the consistency task on a finished document only
    proposes them)."""
    from ..tasks import consistency_fixes  # the tasks workflow builds on the pipeline

    try:
        fixes, counts = await consistency_fixes(ctx)
    except Exception as exc:  # polishing is a bonus; never lose the reviewed translation over it — but say so
        log.warning("polish failed: %s", error_text(exc))
        yield say("**Note:** the final consistency pass failed, so repeated sentences and termbase rules weren't "
                   f"checked one last time (**Apply termbase** runs it again). Error: {error_text(exc)}", kind="assistant")
        fixes, counts = {}, {}
    current = {s["id"]: s for s in st.get_segments(ctx.state)}
    delta: dict[str, Any] = {}
    for sid, text in fixes.items():
        if (seg := current.get(sid)) is not None:
            delta[st.seg_key(sid)] = st.apply_target(seg, text, origin=seg.get("origin") or "mt", status=seg.get("status") or "draft")
    if delta:
        refined = list(ctx.state.get("doc:refined") or [])
        delta["doc:refined"] = refined + [sid for sid in fixes if sid not in refined]
        n = len(fixes)
        parts = []
        if counts.get("same"):
            parts.append(f"{counts['same']} repeated sentence{'s' if counts['same'] != 1 else ''} unified")
        if counts.get("terms"):
            parts.append(f"{counts['terms']} termbase rule{'s' if counts['terms'] != 1 else ''} applied")
        yield say(f"Consistency pass: {n} segment{'s' if n != 1 else ''} adjusted ({', '.join(parts)})", state=delta)
    yield Event(output={"polished": len(fixes)})


@node(rerun_on_resume=True)
async def finalize(ctx: Context, node_input: Any):
    changed = list(ctx.state.get("doc:refined") or [])
    delta: dict[str, Any] = {"doc:refined": [], "doc:review_pending": None}  # reset for any later re-run
    # A reviewer's question whose recommendation the refiner has since applied asks nothing any more.
    segs = st.get_segments(ctx.state)
    questions = [dict(q) for q in ctx.state.get("doc:questions") or []]
    moot = [q for q in questions if q["status"] == "open" and q.get("origin") == "reviewer" and already_used(q, segs)]
    for q in moot:
        q.update(status="resolved", answer="applied in review", answer_target=q.get("guess"))
    if moot:
        delta["doc:questions"] = questions
    if changed:
        delta.update(await save_version(ctx, "AI review fixes", changed))
    delta.update(progress_state("done", 0, 0, "Done", "ready"))

    n_versions = len((delta.get("doc:versions") or ctx.state.get("doc:versions") or []))
    open_q = [q for q in (delta.get("doc:questions") or ctx.state.get("doc:questions") or []) if q["status"] == "open"]
    _, target_lang = doc_langs(ctx.state)
    lines = [
        f"Your {target_lang} translation is ready (v{n_versions}).",
        f"The AI reviewer's fixes changed {len(changed)} segment{'s' if len(changed) != 1 else ''} — open **Changes** to see the diff."
        if changed
        else "The AI reviewer didn't require any changes.",
    ]
    still_flagged = [x["id"] for x in st.get_segments(ctx.state) if x.get("flags")]
    if still_flagged:
        lines.append(
            f"⚠️ {len(still_flagged)} segment{'s' if len(still_flagged) != 1 else ''} still need attention "
            f"({', '.join(still_flagged[:6])}{'…' if len(still_flagged) > 6 else ''}) — they're marked in the translation."
        )
    if open_q:
        lines.append(
            f"I wasn't sure about {len(open_q)} term{'s' if len(open_q) != 1 else ''} "
            f"({', '.join('“' + q['term'] + '”' for q in open_q[:5])}). Answer the question cards below and I'll update the translation."
        )
    yield say("\n\n".join(lines), kind="assistant", state=delta)  # next steps are buttons in the UI
    yield Event(output={"versions": n_versions})

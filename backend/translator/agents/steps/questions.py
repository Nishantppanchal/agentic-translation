"""Questions for the person: recording their answers, pausing for them, and which segments a term affects."""

from __future__ import annotations

import logging

from google.adk.events import RequestInput

from ... import projects
from ...document import state as st
from ..common import progress_state, say

log = logging.getLogger(__name__)


def record_answers(state, open_qs: list[dict], answers: dict) -> tuple[list[dict], dict, int, dict[str, str]]:
    """A person's answers → (all questions, glossary, number answered, guesses kept for skipped ones).

    An answer with an English term becomes a glossary entry for this document and a project term — approved
    if the person chose it, proposed if they just accepted the recommendation; a note alone explains the
    meaning; a skipped question keeps the agent's recommendation as an unverified choice."""
    questions = [dict(q) for q in state.get("doc:questions") or []]
    by_id = {q["id"]: q for q in questions}
    glossary = dict(state.get("doc:glossary") or {})
    pid = projects.project_id(state)
    answered, kept = 0, {}
    for q in open_qs:
        q = by_id[q["id"]]
        answer = st.answer_of(answers.get(q["id"]))
        if answer:
            q.update(status="resolved", answer=answer["note"] or answer["target"], answer_target=answer["target"],
                     answer_recommended=answer["recommended"])
            glossary[q["term"]] = {"target": answer["target"], "note": answer["note"]}
            if pid:  # the decision helps later documents: approved if the person chose it, else only proposed
                note = answer["note"] or q.get("meaning", "")
                projects.get_store().upsert_term(pid, q["term"], answer["target"], note, status=st.term_status(answer))
            answered += 1
        else:
            q["status"] = "dismissed"
            if q.get("guess"):
                kept[q["term"]] = q["guess"]
    return questions, glossary, answered, kept


async def pause_for(interrupt: str, open_qs: list[dict], text: str):
    """Ask once (the chat shows the question cards) and stop until the person answers."""
    yield say(text, kind="assistant", state=progress_state("clarify", 0, 0, "Waiting for your answers", "awaiting_answers"))
    yield RequestInput(interrupt_id=interrupt, message="Decide terms", payload={"question_ids": [q["id"] for q in open_qs]})


def segments_mentioning(segments: list[dict], term: str) -> set[str]:
    t = term.casefold()
    return {s["id"] for s in segments if t in s["source"].casefold()}

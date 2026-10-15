"""The facts behind the notes for the client (and behind the chat's suggested prompts): decisions and where they
came from, assumptions, open queries and comments, what wasn't translated, and the quality checks — read from the
document's state, no model. agents/assist.py turns them into prose."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from ..quality import qa
from . import comments
from . import state as st

DECIDED_BY = {"tm": "the translation memory", "dictionary": "the dictionary", "ai": "the translator (AI), not confirmed",
              "conflict": "the translator (AI); the dictionary disagrees", "asked": "asked the client"}


def _short(text: str, n: int = 160) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def digest(state: Mapping[str, Any]) -> dict[str, Any]:
    segments = [st.normalize(s) for s in st.get_segments(state)]
    questions = state.get("doc:questions") or []
    glossary = state.get("doc:glossary") or {}
    in_glossary = {t.casefold() for t in glossary}
    # Resolved by the person (their answer is in the glossary), or settled by the agents (a reviewer's question
    # whose recommendation the refiner applied: finish.py) — the latter is an assumption, not a decision.
    answered = [q for q in questions if q.get("status") == "resolved" and q["term"].casefold() in in_glossary]
    settled = [q for q in questions if q.get("status") == "resolved" and q["term"].casefold() not in in_glossary]
    skipped = [q for q in questions if q.get("status") == "dismissed"]
    open_qs = [q for q in questions if q.get("status") == "open"]
    asked = {q["term"].casefold() for q in questions}
    decisions = [{"term": t, "target": e.get("target") or "", "note": e.get("note") or "", "by": "the client's answer"
                  if t.casefold() in {q["term"].casefold() for q in answered} else "the translator, confirmed"}
                 for t, e in glossary.items() if e.get("target")]
    key_terms = [k for k in state.get("doc:key_terms") or [] if k.get("term", "").casefold() not in asked]
    for k in key_terms:
        if k.get("decision") in ("tm", "dictionary"):
            decisions.append({"term": k["term"], "target": k.get("target") or "", "note": k.get("meaning") or "",
                              "by": DECIDED_BY[k["decision"]]})
    assumptions = [{"term": q["term"], "target": q.get("answer_target") or q.get("guess")
                    or next((o["target"] for o in q.get("options") or []), ""), "why": "the question was skipped"}
                   for q in skipped]
    assumptions += [{"term": q["term"], "target": q.get("answer_target") or q.get("guess") or "",
                     "why": "raised in review; the recommended option was applied without the client's answer"} for q in settled]
    assumptions += [{"term": k["term"], "target": k.get("target") or "", "why": DECIDED_BY[k["decision"]]}
                    for k in key_terms if k.get("decision") in ("ai", "conflict")]
    issues = [i for i in qa.document_qa(state, segments) if not i["ignored"]]
    lqa = state.get("doc:lqa") or None
    versions = state.get("doc:versions") or []
    office = state.get("doc:office") or {}
    ocr_fixed = [r.get("page") for r in state.get("doc:ocr_report") or [] if r.get("issues")]
    return {
        "name": state.get("doc:filename") or "the document",
        "title": state.get("doc:title") or "",
        "abstract": state.get("doc:abstract") or "",
        "brief": state.get("doc:brief") or "",
        "source_lang": state.get("doc:detected_lang") or state.get("doc:source_lang") or "the source language",
        "status": state.get("doc:status") or "",
        "version": versions[-1]["version"] if versions else None,
        "segments": len(segments),
        "translated": sum(1 for s in segments if s.get("target")),
        "confirmed": sum(1 for s in segments if s.get("status") in st.HUMAN_DONE),
        "decisions": decisions,
        "answered": [{"term": q["term"], "answer": q.get("answer") or q.get("answer_target") or ""} for q in answered],
        "assumptions": assumptions,
        "open_questions": [{"term": q["term"], "meaning": q.get("meaning") or "", "segments": q.get("segment_ids") or []}
                           for q in open_qs],
        "comments": [{"segment": c.get("seg_id"), "role": c.get("role"), "text": _short(c.get("text") or "")}
                     for c in comments.stored(state) if not c.get("resolved") and not c.get("deleted")],
        "qa_errors": [{"segment": i["segment_id"], "check": i["label"], "message": _short(i["message"])}
                      for i in issues if i["severity"] == "error"],
        "qa_warnings": Counter(i["label"] for i in issues if i["severity"] == "warning"),
        "qa_by_category": Counter(f"{i['category']} {i['severity']}" for i in issues),
        "lqa": ({"score": lqa.get("score"), "passed": lqa.get("passed"), "threshold": lqa.get("threshold"),
                 "counts": lqa.get("counts"), "version": lqa.get("version")} if lqa else None),
        "not_translated": dict(office.get("not_translated") or {}),
        "pictures": [{"where": s.get("where") or f"page {s.get('page')}", "text": _short(s["source"]),
                      "english": _short(s.get("target") or "")}
                     for s in segments if s.get("kind") == "figure" and s.get("source")],
        "ocr_corrected_pages": [p for p in ocr_fixed if p],
        "pending_source_fixes": len(state.get("doc:source_fixes") or {}),
        "proposal": (lambda p: {"changes": len(p.get("changes") or []), "note": p.get("note") or ""} if p else None)(
            st.get_proposal(state)),
    }


def as_text(d: dict[str, Any], *, for_notes: bool = True) -> str:
    """The digest as lines for a prompt. `for_notes`: everything; otherwise what suggesting a next step needs."""
    out = [f"Document: {d['title'] or d['name']} (file {d['name']}), {d['source_lang']} → English; "
           f"{d['translated']} of {d['segments']} segments translated, {d['confirmed']} confirmed"
           + (f"; version {d['version']} saved" if d["version"] else "")]
    if d["abstract"]:
        out.append(f"What it says: {d['abstract']}")
    if d["brief"]:
        out.append(f"Brief: {_short(d['brief'], 600 if for_notes else 300)}")

    def section(title: str, lines: list[str], limit: int = 25) -> None:
        if lines:
            more = f"\n- … and {len(lines) - limit} more" if len(lines) > limit else ""
            out.append(f"{title}:\n" + "\n".join(f"- {x}" for x in lines[:limit]) + more)

    if for_notes:
        section("Terminology decisions", [f"{x['term']} → {x['target']} (decided by {x['by']})" + (f"; {x['note']}" if x["note"] else "")
                                          for x in d["decisions"]])
        section("Questions the client answered", [f"{x['term']}: {x['answer']}" for x in d["answered"]])
        section("Assumptions", [f"{x['term']} → {x['target']} ({x['why']})" for x in d["assumptions"]])
    section("Open questions", [f"{x['term']}: {x['meaning']} (segments {', '.join(x['segments']) or '?'})" for x in d["open_questions"]])
    section("Open comments", [f"{x['segment']} ({x['role']}): {x['text']}" for x in d["comments"]], 10)
    section("QA errors", [f"{x['segment']}: {x['check']} — {x['message']}" for x in d["qa_errors"]], 12 if for_notes else 6)
    if d["qa_warnings"]:
        out.append("QA warnings: " + ", ".join(f"{n} {label}" for label, n in d["qa_warnings"].most_common()))
    if not d["qa_errors"] and not d["qa_warnings"]:
        out.append("QA: no errors or warnings")
    if d["lqa"]:
        lqa = d["lqa"]
        out.append(f"Quality score (LQA, MQM): {lqa['score']} — {'pass' if lqa['passed'] else 'fail'} (threshold {lqa['threshold']})"
                   + (f"; errors {lqa['counts']}" if lqa.get("counts") else ""))
    else:
        out.append("Quality score (LQA): not run")
    if d["not_translated"]:
        out.append("Not translated (left as in the original file): " + ", ".join(f"{n} {k}" for k, n in d["not_translated"].items()))
    if for_notes:
        section("Text inside pictures (translated in the captions / alt text)", [f"{x['where']}: {x['text']} → {x['english']}"
                                                                                  for x in d["pictures"]], 10)
        if d["ocr_corrected_pages"]:
            out.append(f"Source reading corrected by the OCR check on pages: {', '.join(map(str, d['ocr_corrected_pages']))}")
    if d["pending_source_fixes"]:
        out.append(f"Source fixes waiting for a decision: {d['pending_source_fixes']}")
    if d["proposal"]:
        out.append(f"A proposal with {d['proposal']['changes']} change(s) waits for the person's decision"
                   + (f" ({d['proposal']['note']})" if d["proposal"]["note"] else ""))
    return "\n".join(out)

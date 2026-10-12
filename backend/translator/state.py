"""Session-state layout + helpers.

Each segment lives under its own state key (`seg:<id>`) so an edit produces a
small state delta instead of re-writing the whole document.

Keys:
  doc:filename, doc:mime, doc:source_lang, doc:target_lang
  doc:status        uploaded | ocr | ocr_check | translating | reviewing | ready | error
  doc:progress      {stage, current, total, message}
  doc:pages         int
  doc:seg_ids       [segment ids in document order]
  seg:<id>          {id, page, kind, source, target, translatable}
  doc:glossary      {source_term: {target, note}}      user-confirmed, highest priority
  doc:termbase      {source_term: target}               translator's own choices, carried page to page
  doc:questions     [{id, term, guess, segment_ids, reason, status, answer}]
  doc:versions      [{version, note, created_at, changed}]
  doc:ocr_report    [{page, ok, issues}]
  doc:review_report [{batch, round, issues}]
  doc:dirty         [segment ids changed since the last saved version]
  doc:proposal      editor changes awaiting the user's approval (see below)
"""

from __future__ import annotations

import time
from collections.abc import Mapping, MutableMapping
from typing import Any

SEG = "seg:"
TRANSLATION_ARTIFACT = "translation.json"
SOURCE_ARTIFACT_PREFIX = "source"


def seg_key(segment_id: str) -> str:
    return f"{SEG}{segment_id}"


def segment_ids(state: Mapping[str, Any]) -> list[str]:
    return list(state.get("doc:seg_ids") or [])


def get_segments(state: Mapping[str, Any]) -> list[dict]:
    return [state[seg_key(i)] for i in segment_ids(state) if seg_key(i) in state]


def get_segment(state: Mapping[str, Any], segment_id: str) -> dict | None:
    seg = state.get(seg_key(segment_id))
    return dict(seg) if seg else None


def put_segment(state: MutableMapping[str, Any], seg: dict, mark_dirty: bool = True) -> None:
    state[seg_key(seg["id"])] = seg
    if mark_dirty:
        dirty = list(state.get("doc:dirty") or [])
        if seg["id"] not in dirty:
            dirty.append(seg["id"])
            state["doc:dirty"] = dirty


def snapshot(state: Mapping[str, Any]) -> dict[str, str]:
    """Translation snapshot {segment_id: target} used for versioned artifacts."""
    return {s["id"]: s.get("target") or "" for s in get_segments(state)}


def glossary_text(state: Mapping[str, Any]) -> str:
    glossary = state.get("doc:glossary") or {}
    if not glossary:
        return "(empty)"
    lines = []
    for term, entry in glossary.items():
        if entry.get("target"):
            note = f"  — {entry['note']}" if entry.get("note") else ""
            lines.append(f"- {term} → {entry['target']}{note}")
        else:  # a user clarification of meaning rather than a fixed translation
            lines.append(f"- {term}: means \"{entry.get('note', '')}\" (clarified by the author; translate accordingly)")
    return "\n".join(lines)


def termbase_text(state: Mapping[str, Any]) -> str:
    glossary = {g.casefold() for g in state.get("doc:glossary") or {}}
    termbase = {k: v for k, v in (state.get("doc:termbase") or {}).items() if k.casefold() not in glossary}
    if not termbase:
        return "(none yet)"
    return "\n".join(f"- {src} → {tgt}" for src, tgt in termbase.items())


def without_terms(termbase: dict[str, str], terms: set[str]) -> dict[str, str]:
    """Drop termbase entries superseded by the glossary (or still in doubt)."""
    folded = {t.casefold() for t in terms}
    return {k: v for k, v in termbase.items() if k.casefold() not in folded}


def merge_termbase(state: Mapping[str, Any], current: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """First choice wins (that's what keeps later pages consistent); glossary terms are skipped."""
    glossary = {g.casefold() for g in state.get("doc:glossary") or {}}
    merged = dict(current)
    known = {k.casefold() for k in merged}
    for src, tgt in new.items():
        if src.casefold() not in known and src.casefold() not in glossary:
            merged[src] = tgt
            known.add(src.casefold())
    return merged


def open_questions(state: Mapping[str, Any]) -> list[dict]:
    return [q for q in state.get("doc:questions") or [] if q.get("status") == "open"]


def questions_text(state: Mapping[str, Any]) -> str:
    qs = open_questions(state)
    if not qs:
        return "(none)"
    lines = []
    for q in qs:
        options = "; ".join(o["target"] for o in q.get("options") or []) or q.get("guess") or "?"
        lines.append(f"- [{q['id']}] \"{q['term']}\" (options: {options}; segments {', '.join(q['segment_ids']) or '?'})")
    return "\n".join(lines)


def add_questions(state: Mapping[str, Any], new_terms: list[dict], origin: str = "translator") -> list[dict]:
    """Merge newly flagged terms into the question list (dedup by term). Returns the full list.

    A question carries what someone who doesn't read the source language needs to answer it: the
    term's meaning in plain English, English options (with notes) and the agent's recommendation."""
    questions = [dict(q) for q in state.get("doc:questions") or []]
    glossary = state.get("doc:glossary") or {}
    by_term = {q["term"].casefold(): q for q in questions}
    for t in new_terms:
        key = t["term"].casefold()
        if key in {g.casefold() for g in glossary}:
            continue
        if key in by_term:
            existing = by_term[key]
            existing["segment_ids"] = sorted(set(existing["segment_ids"]) | set(t["segment_ids"]))
            continue
        options = t.get("options") or ([{"target": t["guess"], "note": ""}] if t.get("guess") else [])
        q = {
            "id": f"q{len(questions) + 1}",
            "term": t["term"],
            "guess": t.get("guess", ""),
            "options": options,
            "recommended": t.get("recommended", 0) if options else None,
            "meaning": t.get("meaning", ""),
            "gist": t.get("gist", ""),
            "segment_ids": t.get("segment_ids", []),
            "reason": t.get("reason", ""),
            "dictionary": t.get("dictionary") or [],  # entries from the dictionary service, if one is set up
            "origin": origin,
            "status": "open",
            "answer": None,
        }
        questions.append(q)
        by_term[key] = q
    return questions


def answer_of(value: Any) -> dict[str, Any] | None:
    """A person's answer → {"target", "note", "recommended"}, or None when skipped.
    Accepts {"target", "note", "recommended"} or plain text (an explanation of the meaning, as older clients
    send). `recommended`: the person took the agents' recommendation as it was (not a checked decision)."""
    if isinstance(value, dict):
        target, note = str(value.get("target") or "").strip(), str(value.get("note") or "").strip()
        recommended = bool(value.get("recommended")) and bool(target)
    else:
        target, note, recommended = "", str(value or "").strip(), False
    return {"target": target, "note": note, "recommended": recommended} if target or note else None


def term_status(answer: dict) -> str:
    """Project termbase status for an answer: a term the person chose is approved; a recommendation they
    just accepted is only proposed; an explanation without a term is a note."""
    if not answer["target"]:
        return "note"
    return "proposed" if answer.get("recommended") else "approved"


def new_version_entry(state: Mapping[str, Any], version: int, note: str, changed: list[str]) -> list[dict]:
    versions = list(state.get("doc:versions") or [])
    versions.append({"version": version, "note": note, "created_at": time.time(), "changed": changed})
    return versions


# --------------------------------------------------------------------------- #
# Proposals: editor changes are staged here until the user accepts them.
#   doc:proposal = {id, notes: [user requests], changes: [{segment_id, field, before, after}],
#                   glossary: {term: {target, note}}, created_at}
# --------------------------------------------------------------------------- #


def get_proposal(state: Mapping[str, Any]) -> dict | None:
    return state.get("doc:proposal") or None


def effective_segment(state: Mapping[str, Any], seg: dict) -> dict:
    """The segment as it would be if the pending proposal were accepted (+ a `pending` flag)."""
    proposal = get_proposal(state)
    if not proposal:
        return seg
    out = dict(seg)
    for c in proposal["changes"]:
        if c["segment_id"] == seg["id"]:
            out[c["field"]] = c["after"]
            out["pending"] = True
    return out


def effective_segments(state: Mapping[str, Any]) -> list[dict]:
    return [effective_segment(state, s) for s in get_segments(state)]


def effective_glossary(state: Mapping[str, Any]) -> dict:
    proposal = get_proposal(state)
    return {**(state.get("doc:glossary") or {}), **((proposal or {}).get("glossary") or {})}


def proposal_text(state: Mapping[str, Any]) -> str:
    proposal = get_proposal(state)
    if not proposal:
        return "(none)"
    lines = [f"- {c['segment_id']} ({c['field']}): \"{c['before'][:80]}\" → \"{c['after'][:80]}\"" for c in proposal["changes"]]
    lines += [f"- glossary: {t} → {e.get('target') or e.get('note')}" for t, e in (proposal.get("glossary") or {}).items()]
    return "\n".join(lines) or "(empty)"


# --------------------------------------------------------------------------- #
# Segment lifecycle — statuses record HUMAN work only (ISO 17100 style):
#   new → draft → confirmed (by the translator) → reviewed (by a second, human reviewer); plus `locked`.
# The AI reviewer's verdict is a separate marker, `ai_check`: "passed" | "issues" | None, and never
# changes the status (in an LSP, "reviewed" means a person checked it).
#   origin: copy (not translatable) | mt (pipeline) | agent (accepted proposal) | human (direct edit)
#           | tm_exact | tm_fuzzy (translation memory, later milestone)
# --------------------------------------------------------------------------- #

STATUSES = ("new", "draft", "confirmed", "reviewed")
HUMAN_DONE = ("confirmed", "reviewed")


def normalize(seg: dict) -> dict:
    """Fill lifecycle defaults (also upgrades segments stored before statuses existed)."""
    out = dict(seg)
    translatable = out.get("translatable", True)
    out.setdefault("origin", "copy" if not translatable else ("mt" if out.get("target") else None))
    out.setdefault("status", "confirmed" if not translatable else ("draft" if out.get("target") else "new"))
    out.setdefault("locked", not translatable)
    out.setdefault("ai_check", None)
    out.setdefault("qe", None)  # AI quality estimate 0-100 from the last review / LQA of this text
    out.setdefault("flags", [])
    out.setdefault("comments", [])
    out.setdefault("updated_at", None)
    return out


def apply_target(seg: dict, target: str, *, origin: str, status: str = "draft", flags: list[str] | None = None) -> dict:
    """The one way to change a segment's translation: sets origin/status, recomputes flags, stamps the time."""
    from .qa import check_segment  # local import: qa depends on documents, not on state

    out = normalize(seg)
    out["target"] = target
    out["origin"] = origin
    out["status"] = status
    out["flags"] = flags if flags is not None else check_segment(out, target)
    out["ai_check"] = None  # any earlier AI review was of the old text
    out["qe"] = None
    out["updated_at"] = time.time()
    return out


def is_frozen(seg: dict) -> bool:
    """Segments the agents must not touch: locked, or confirmed/reviewed by a person."""
    seg = normalize(seg)
    return bool(seg["locked"]) or seg["status"] in HUMAN_DONE


def status_counts(state: Mapping[str, Any]) -> dict[str, int]:
    counts = {s: 0 for s in STATUSES}
    for seg in get_segments(state):
        if seg.get("translatable", True):
            counts[normalize(seg)["status"]] += 1
    counts["total"] = sum(counts[s] for s in STATUSES)
    return counts

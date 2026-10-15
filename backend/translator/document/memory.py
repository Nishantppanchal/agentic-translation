"""The translation memory as a document sees it: what the project's TM already knows about its segments (read once,
before analysis and translation), and what goes back into it (the one write path).

Matches, as in CAT tools: 101 = the same sentence after the same previous sentence; 100 = the same sentence;
75-99 = a fuzzy match, given to the translator as a reference to adapt.

What is saved: a segment a person confirmed or reviewed — one by one, in bulk, or by accepting an agent's change
with Confirm. How it was approved is kept with the unit (projects.APPROVALS): a unit saved by a bulk click never
confirms a later document's segment by itself, it comes back as a 100% draft.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .. import projects
from ..text import with_markup_of
from . import state as st


def context_map(segments: list[dict]) -> dict[str, str]:
    """{segment id: the source of the translatable segment before it} — the context of a 101% match."""
    out: dict[str, str] = {}
    prev = ""
    for seg in segments:
        if not seg.get("translatable", True):
            continue
        out[seg["id"]] = prev
        prev = seg["source"]
    return out


def lookup(state: Mapping[str, Any], seg_id: str, limit: int = 5) -> list[dict]:
    """The best TM matches for one segment (the TM panel); [] outside a project."""
    pid = projects.project_id(state)
    seg = st.get_segment(state, seg_id)
    if not pid or not seg:
        return []
    prev = context_map(st.get_segments(state)).get(seg_id, "")
    return projects.get_store().lookup(pid, seg["source"], prev, limit)


def prefill(state: Mapping[str, Any], segments: list[dict]) -> tuple[dict[str, dict], dict[str, dict], dict[str, int]]:
    """→ (state delta: segments filled from 100/101% matches, {segment id: fuzzy match to adapt}, stats).
    101% after a person's one-by-one approval starts confirmed (the project's auto-confirm setting); the rest
    are drafts a person still looks at."""
    stats = {"context": 0, "exact": 0, "fuzzy": 0, "words": 0}
    pid = projects.project_id(state)
    if not pid:
        return {}, {}, stats
    store = projects.get_store()
    auto_confirm = (store.project(pid) or {}).get("auto_confirm_context", True)
    prev_of = context_map(segments)
    delta: dict[str, dict] = {}
    refs: dict[str, dict] = {}
    for seg in segments:
        if not seg.get("translatable", True) or st.is_frozen(seg) or seg.get("target"):
            continue
        best = next(iter(store.lookup(pid, seg["source"], prev_of.get(seg["id"], ""), limit=1)), None)
        if best and best["score"] >= 100:
            context = best["score"] > 100
            confirmed = context and auto_confirm and best.get("approval") != "bulk"
            target = with_markup_of(seg["source"], best["target"])  # the heading/list markup of this segment
            delta[st.seg_key(seg["id"])] = st.apply_target(seg, target, origin="tm", match=best["score"],
                                                           status="confirmed" if confirmed else "draft")
            stats["context" if context else "exact"] += 1
            stats["words"] += len(seg["source"].split())
        elif best:
            refs[seg["id"]] = {k: best[k] for k in ("score", "source", "target", "ref")}
            stats["fuzzy"] += 1
    return delta, refs, stats


def reference_lines(batch: list[dict], refs: dict[str, dict]) -> str:
    """The fuzzy matches for these segments, as prompt lines: `- [p1.3] 87% · source → target`."""
    lines = [f"- [{s['id']}] {refs[s['id']]['score']}% · {refs[s['id']]['source']} → {refs[s['id']]['target']}"
             for s in batch if s["id"] in refs]
    return "\n".join(lines) or "(none)"


@dataclass
class SaveResult:
    saved: set[str] = field(default_factory=set)  # segments whose wording is now in the TM
    added: int = 0
    updated: int = 0


def save(state: Mapping[str, Any], segments: list[dict], approval: str) -> SaveResult:
    """Write confirmed/reviewed segments to the project's TM (blocking: call it in a thread from async code).
    `approval`: segment | review | proposal | bulk. Outside a project nothing is saved."""
    result = SaveResult()
    pid = projects.project_id(state)
    if not pid:
        return result
    done = [s for s in segments if s.get("target") and s.get("status") in st.HUMAN_DONE and s.get("translatable", True)]
    if not done:
        return result
    prev_of = context_map(st.get_segments(state))
    filename = state.get("doc:filename", "")
    units = [{"source": s["source"], "target": s["target"], "prev_source": prev_of.get(s["id"], ""),
              "ref": f"{filename}#{s['id']}", "approval": approval} for s in done]
    for seg, status in zip(done, projects.get_store().add_units(pid, units)):
        if status in ("added", "updated", "unchanged"):
            result.saved.add(seg["id"])
        result.added += status == "added"
        result.updated += status == "updated"
    return result

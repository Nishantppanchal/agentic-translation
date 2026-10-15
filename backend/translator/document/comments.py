"""Segment comments: notes from the translator, the reviewer or the agent. They never change the text.

They are stored apart from the segments, in `doc:comments`, so nothing that rewrites segments can lose them. That
includes the OCR, a source fix that re-splits a page, and a retry. Each comment remembers the source text it was
made on (its anchor). When a page is re-split the segment ids change, and the comment follows its text to the new
segment. A comment whose text is gone becomes an orphan: still listed, so it can be read and deleted.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Any

from rapidfuzz import fuzz

from . import state as st

FIELD = "doc:comments"
ROLES = ("translator", "reviewer", "agent")
MAX_COMMENTS = 2000
EDITED_SOURCE = 80  # a segment whose source was corrected keeps its comments if it still reads this alike (0-100)
PUBLIC = ("id", "role", "text", "at", "resolved")


def anchor(seg: Mapping[str, Any]) -> str:
    """What a comment is attached to: the segment's source (whitespace collapsed), or its picture."""
    text = " ".join((seg.get("source") or "").split())
    if not text and seg.get("image"):
        return f"image:{seg['image']}"
    return text


def stored(state: Mapping[str, Any]) -> list[dict]:
    """All comments, oldest first. Documents from before `doc:comments` kept them inside each segment."""
    if state.get(FIELD) is not None:
        return list(state[FIELD])
    return [
        {**c, "seg_id": seg["id"], "page": seg.get("page"), "anchor": anchor(seg)}
        for seg in st.get_segments(state)
        for c in seg.get("comments") or []
    ]


def _home(comment: dict, by_id: dict[str, dict], by_anchor: dict[str, list[dict]]) -> dict | None:
    """The segment a comment belongs to now: its text's segment, else its old segment if that was only corrected."""
    key = comment.get("anchor") or ""
    same_text = by_anchor.get(key) if key else None
    if same_text:
        for seg in same_text:
            if seg["id"] == comment.get("seg_id"):
                return seg
        return next((s for s in same_text if s.get("page") == comment.get("page")), same_text[0])
    seg = by_id.get(comment.get("seg_id") or "")
    if seg and key and fuzz.ratio(anchor(seg), key) >= EDITED_SOURCE:
        return seg
    return None


def _placed(state: Mapping[str, Any]) -> tuple[list[tuple[dict, dict | None]], list[dict]]:
    segments = st.get_segments(state)
    by_id = {s["id"]: s for s in segments}
    by_anchor: dict[str, list[dict]] = {}
    for s in segments:
        if key := anchor(s):
            by_anchor.setdefault(key, []).append(s)
    pairs = [(c, _home(c, by_id, by_anchor)) for c in stored(state)]
    return pairs, segments


def _public(c: dict) -> dict:
    return {k: c[k] for k in PUBLIC if k in c}


def place(state: Mapping[str, Any]) -> tuple[dict[str, list[dict]], list[dict]]:
    """({segment id: its comments}, orphans): the comments as the document reads now."""
    pairs, _ = _placed(state)
    by_seg: dict[str, list[dict]] = {}
    orphans: list[dict] = []
    for c, seg in pairs:
        if seg is None:
            orphans.append({**_public(c), "seg_id": c.get("seg_id"), "anchor": c.get("anchor", "")})
        else:
            by_seg.setdefault(seg["id"], []).append(_public(c))
    return by_seg, orphans


def for_segment(state: Mapping[str, Any], seg_id: str) -> list[dict]:
    return place(state)[0].get(seg_id, [])


def _reanchored(state: Mapping[str, Any]) -> list[dict]:
    """The stored list with every placed comment pointing at its current segment (so ids stay fresh)."""
    pairs, _ = _placed(state)
    return [c if seg is None else {**c, "seg_id": seg["id"], "page": seg.get("page"), "anchor": anchor(seg)} for c, seg in pairs]


def add(state: Mapping[str, Any], seg_id: str, text: str, role: str = "translator") -> tuple[dict, dict]:
    """(state delta, the new comment). KeyError for an unknown segment, ValueError for an empty comment."""
    seg = st.get_segment(state, seg_id)
    if seg is None:
        raise KeyError(seg_id)
    text = text.strip()
    if not text:
        raise ValueError("The comment is empty.")
    comments = _reanchored(state)
    if len(comments) >= MAX_COMMENTS:
        raise ValueError(f"This document already has {MAX_COMMENTS} comments; delete some first.")
    comment = {
        "id": uuid.uuid4().hex[:8],
        "role": role if role in ROLES else "translator",
        "text": text,
        "at": time.time(),
        "resolved": False,
        "seg_id": seg_id,
        "page": seg.get("page"),
        "anchor": anchor(seg),
    }
    return {FIELD: [*comments, comment]}, _public(comment)


def update(state: Mapping[str, Any], comment_id: str, *, resolved: bool | None = None, delete: bool = False) -> dict:
    """State delta that resolves, reopens or deletes one comment (orphans included). KeyError if it isn't there."""
    comments = _reanchored(state)
    if not any(c["id"] == comment_id for c in comments):
        raise KeyError(comment_id)
    if delete:
        comments = [c for c in comments if c["id"] != comment_id]
    elif resolved is not None:
        comments = [{**c, "resolved": bool(resolved)} if c["id"] == comment_id else c for c in comments]
    return {FIELD: comments}


def open_text(state: Mapping[str, Any], limit: int = 40) -> str:
    """Open comments for the chat editor's instruction: `- [p1.3] reviewer: …`."""
    by_seg, orphans = place(state)
    order = {s["id"]: i for i, s in enumerate(st.get_segments(state))}
    lines = [
        f"- [{seg_id}] {c['role']}: {c['text'][:300]}"
        for seg_id in sorted(by_seg, key=lambda k: order.get(k, 0))
        for c in by_seg[seg_id]
        if not c.get("resolved")
    ]
    lines += [f"- (on text that has since changed) {c['role']}: {c['text'][:300]}" for c in orphans if not c.get("resolved")]
    if not lines:
        return "(none)"
    more = len(lines) - limit
    return "\n".join(lines[:limit]) + (f"\n… and {more} more" if more > 0 else "")

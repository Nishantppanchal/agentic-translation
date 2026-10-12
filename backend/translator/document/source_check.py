"""Checking the source before translating.

PDFs and images pause after reading (`check_source` in the workflow), so the person can look at the OCR next to
the page images and ask the chat to fix it. OCR mistakes of structure — two columns read across, a paragraph
split at the column break, a stamp's text inside a sentence, a table row read as a paragraph — span segments, so
a fix is a whole page: the page's source as OCR markdown, before and after. The editor stages it (writing it
itself, or having the vision model read the page again with the person's instruction); the person accepts or
rejects it; accepting splits the page into segments again. Nothing is translated yet, so nothing is lost.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from ..ocr.guard import WORD
from . import state as st
from .pages import IMAGE_EXTS, segments_from_pages

FIXES = "doc:source_fixes"  # {page: fix}
CHECKED = "doc:source_checked"
_FIGURE_IMAGE = re.compile(r"figure-p\d+-(\d+)\.png$")


def needs_check(state) -> bool:
    """Read with OCR (a PDF or an image), so the source is worth a look before translating."""
    return Path(state.get("doc:filename") or "").suffix.lower() in {".pdf", *IMAGE_EXTS}


def in_review(state) -> bool:
    return state.get("doc:status") == "awaiting_source_check"


def page_segments(state, page: int) -> list[dict]:
    return [s for s in st.get_segments(state) if s.get("page") == page]


def pages(state) -> list[int]:
    return sorted({s["page"] for s in st.get_segments(state) if s.get("page")})


def page_markdown(state, page: int) -> str:
    """A page's source in the OCR's own markdown: `[[HEADER]]` / `[[FOOTER]]` lines, `[[FIGURE n]]` for pictures."""
    out = []
    for s in page_segments(state, page):
        if s["kind"] in ("header", "footer"):
            out.append(f"[[{s['kind'].upper()}]] {s['source']}")
        elif s["kind"] == "figure":
            n = s.get("figure") or int((_FIGURE_IMAGE.search(s.get("image") or "") or [0, 0])[1] or 0)
            out.append(f"[[FIGURE {n}]]")
        else:
            out.append(s["source"])
    return "\n\n".join(out)


def stage(state, page: int, after: str, reason: str, origin: str) -> dict | None:
    """A page fix for the person to accept: before and after, and every word it would change (a structure fix
    changes none — a model rewriting a page must not slip in other words unnoticed). None if nothing changes."""
    before = page_markdown(state, page)
    after = after.strip()
    if not after or after == before.strip():  # a paragraph join is only whitespace, and still a change
        return None
    return {"id": f"s{uuid.uuid4().hex[:8]}", "page": page, "before": before, "after": after, "reason": reason.strip(),
            "origin": origin, "word_changes": word_changes(before, after), "moved": moved_text(before, after),
            "created_at": time.time()}


_MARKER = re.compile(r"\[\[(?:HEADER|FOOTER)\]\]|\[\[FIGURE (\d+)\]\]")


def word_changes(before: str, after: str, limit: int = 12) -> list[str]:
    """Words the fix adds or removes, and pictures it drops or adds. Order doesn't count (joining, splitting and
    reordering change no word; `moved_text` quotes what moves), nor markup (`[[HEADER]]`, a heading's `#`)."""
    def words(text: str) -> Counter:
        return Counter(WORD.findall(_MARKER.sub(" ", text)))

    def pictures(text: str) -> set[str]:
        return {m.group(1) for m in _MARKER.finditer(text) if m.group(1)}

    def listed(found: Counter) -> str:
        return ", ".join(f"“{w}”" + (f" ×{n}" if n > 1 else "") for w, n in found.most_common(limit))

    old, new = words(before), words(after)
    gone, added = old - new, new - old
    out = ([f"removed: {listed(gone)}"] if gone else []) + ([f"added: {listed(added)}"] if added else [])
    for n in sorted(pictures(before) - pictures(after)):
        out.append(f"picture {n} removed")
    for n in sorted(pictures(after) - pictures(before)):
        out.append(f"picture {n} added (no image for it: the marker is dropped)")
    return out


def moved_text(before: str, after: str, limit: int = 3, quote: int = 60) -> list[str]:
    """Passages the fix moves: the same words in another place. Counting words can't tell a right reading order
    from a wrong one (two columns stitched the wrong way round keep every word), so each moved passage is quoted
    (its start, as written) for a person to check against the page image."""
    def words(text: str) -> tuple[str, list[re.Match]]:
        text = _MARKER.sub(" ", text)
        return text, list(WORD.finditer(text))

    _, old = words(before)
    text, new = words(after)
    added = Counter(m.group() for m in new) - Counter(m.group() for m in old)
    matcher = SequenceMatcher(None, [m.group() for m in old], [m.group() for m in new], autojunk=False)
    out = []
    for tag, _, _, j1, j2 in matcher.get_opcodes():
        run = new[j1:j2]
        if tag in ("insert", "replace") and sum((Counter(m.group() for m in run) - added).values()) >= 2:
            passage = " ".join(text[run[0].start():run[-1].end()].split())
            out.append(f"“{passage[:quote].rstrip()}{' …' if len(passage) > quote else ''}”")
    return out[:limit] + ([f"and {len(out) - limit} more"] if len(out) > limit else [])


def resegment(state, page: int, markdown: str) -> dict:
    """State delta: the page's segments replaced by those of `markdown` (pictures keep their image and legend)."""
    old = page_segments(state, page)
    figures = {(page, s["figure"]): {"image": s["image"], "text": s.get("source") or ""}
               for s in old if s["kind"] == "figure" and s.get("figure")}
    new = [st.normalize(s) for s in segments_from_pages([(page, markdown)], figures)]
    old_ids = [s["id"] for s in old]
    ids = st.segment_ids(state)
    at = ids.index(old_ids[0]) if old_ids and old_ids[0] in ids else len(ids)
    kept = [i for i in ids if i not in set(old_ids)]
    delta: dict = {st.seg_key(s["id"]): s for s in new}
    delta["doc:seg_ids"] = kept[:at] + [s["id"] for s in new] + kept[at:]
    return delta

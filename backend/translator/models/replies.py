"""Parsers for the light tag-based output formats the agents are prompted to emit.

We avoid JSON / tool-calling for bulk pipeline output: small local models follow
simple `<tag attr="...">...</tag>` formats far more reliably than strict JSON.
"""

from __future__ import annotations

import html
import json
import re

_THINK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.S | re.I)
_OUTER_FENCE = re.compile(r"^\s*```[\w-]*\n(.*?)\n```\s*$", re.S)
_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_SEG = re.compile(r'<seg\s+id\s*=\s*"([^"]+)"\s*>(.*?)</seg>', re.S | re.I)


def clean(text: str) -> str:
    """Strip reasoning blocks and an outer code fence wrapping the whole reply."""
    text = _THINK.sub("", text or "").strip()
    m = _OUTER_FENCE.match(text)
    return m.group(1).strip() if m else text


def _tags(text: str, tag: str) -> list[tuple[dict[str, str], str]]:
    pattern = re.compile(rf"<{tag}\b([^>]*)>(.*?)</{tag}>", re.S | re.I)
    return [
        ({k: html.unescape(v) for k, v in _ATTR.findall(attrs)}, body.strip())
        for attrs, body in pattern.findall(text)
    ]


def tag_body(text: str, tag: str) -> str | None:
    found = _tags(text, tag)
    return found[0][1] if found else None


def parse_segments(text: str) -> dict[str, str]:
    """`<seg id="p1.2">...</seg>` → {"p1.2": "..."}"""
    return {sid.strip(): clean(body.strip("\n")) for sid, body in _SEG.findall(clean(text))}


def term_from(t: dict) -> dict | None:
    """One uncertain/key term → {term, guess, options, recommended, meaning, reason, segment_ids (, gist, ambiguous)}."""
    source = str(t.get("source") or "").strip()
    if not source:
        return None
    options, seen = [], set()
    for o in t.get("options") or []:
        target = str((o.get("target") if isinstance(o, dict) else o) or "").strip()
        if target and target.casefold() not in seen:
            seen.add(target.casefold())
            options.append({"target": target, "note": str(o.get("note") or "").strip() if isinstance(o, dict) else ""})
    guess = str(t.get("guess") or "").strip()
    if guess and guess.casefold() not in seen:
        options.insert(0, {"target": guess, "note": ""})
    try:
        rec = int(t.get("recommended") or 0)
    except (TypeError, ValueError):
        rec = 0
    rec = rec if 0 <= rec < len(options) else 0
    out = {
        "term": source,
        "guess": options[rec]["target"] if options else "",
        "options": options[:4],
        "recommended": rec if rec < 4 else 0,
        "meaning": str(t.get("meaning") or "").strip(),
        "reason": str(t.get("reason") or "").strip(),
        "segment_ids": [str(i) for i in t.get("segment_ids") or []],
    }
    if "gist" in t:
        out["gist"] = str(t.get("gist") or "").strip()
    if "ambiguous" in t:
        out["ambiguous"] = bool(t.get("ambiguous"))
    return out


def parse_terms(text: str) -> list[dict]:
    """`<term source="X" guess="Y" alt="A | B" meaning="…" segs="p1.2,p1.3">why</term>`"""
    terms = []
    for attrs, body in _tags(clean(text), "term"):
        options = [a.strip() for a in attrs.get("alt", "").split("|") if a.strip()]
        term = {
            "source": attrs.get("source", ""),
            "guess": attrs.get("guess", ""),
            "options": options,
            "meaning": attrs.get("meaning", ""),
            "segment_ids": [s.strip() for s in attrs.get("segs", "").split(",") if s.strip()],
            "reason": body,
        }
        if "gist" in attrs:  # the document analysis
            term["gist"] = attrs["gist"]
        if "ambiguous" in attrs:
            term["ambiguous"] = attrs["ambiguous"].strip().lower() in ("yes", "true", "1")
        found = term_from(term)
        if found:
            terms.append(found)
    return terms


def parse_keeps(text: str) -> dict[str, str]:
    """`<keep source="X">Y</keep>` → {"X": "Y"}: terminology choices to reuse on later pages."""
    return {
        attrs["source"].strip(): clean(body)
        for attrs, body in _tags(clean(text), "keep")
        if attrs.get("source", "").strip() and body.strip()
    }


def parse_issues(text: str, tag: str = "issue") -> list[dict]:
    """`<issue seg="p1.2" severity="major" category="accuracy">problem → fix</issue>` (LQA: tag="error")."""
    from . import structured  # local: structured imports this module

    issues = []
    for attrs, body in _tags(clean(text), tag):
        seg = attrs.get("seg", "").strip()
        if not seg or not body:
            continue
        issues.append(
            {
                "segment_id": seg,
                "severity": structured.severity(attrs.get("severity")),
                "category": structured.category(attrs.get("category")),
                "span": attrs.get("span", "").strip(),
                "note": body,
            }
        )
    return issues


def parse_alternatives(text: str) -> dict[str, list[dict]]:
    """`<alt seg="p1.2" note="more formal">text</alt>` lines → {"p1.2": [{"text", "note"}, …]}"""
    out: dict[str, list[dict]] = {}
    for attrs, body in _tags(clean(text), "alt"):
        if attrs.get("seg") and body:
            out.setdefault(attrs["seg"].strip(), []).append({"text": body, "note": attrs.get("note", "").strip()})
    return out


def parse_scores(text: str) -> dict[str, int]:
    """`<score seg="p1.2">85</score>` → {"p1.2": 85} (unreadable scores are skipped)."""
    out = {}
    for attrs, body in _tags(clean(text), "score"):
        m = re.search(r"\d+(?:\.\d+)?", body)
        if attrs.get("seg") and m:
            out[attrs["seg"].strip()] = max(0, min(100, round(float(m[0]))))
    return out


def is_none_reply(text: str) -> bool:
    t = clean(text).strip().lower()
    return not t or t in {"<none/>", "<none />", "none", "(none)", "no text"}


def parse_figure_reply(text: str) -> tuple[str, str]:
    """(kind, text) from the figure check: kind "picture" or "text". A reply that doesn't say (a model that ignores
    the format, or JSON) is taken as a picture with the reply as its text — the safe reading: nothing is dropped."""
    text = clean(text)
    kind = (tag_body(text, "kind") or "").strip().lower()
    body = tag_body(text, "text")
    if not kind and text.startswith("{"):
        try:
            obj = json.loads(text)
            kind, body = str(obj.get("kind") or "").lower(), str(obj.get("text") or "")
        except (ValueError, AttributeError):
            pass
    if body is None:
        body = "" if kind else text
    body = "" if is_none_reply(body) else clean(body)
    return ("text" if kind.startswith("text") else "picture"), body


def parse_ocr_fixes(text: str) -> tuple[bool, list[tuple[str, str]], str | None]:
    """The OCR check's reply → (ok, [(as read, as printed)], a whole corrected page if the model wrote one anyway)."""
    text = clean(text)
    verdict = (tag_body(text, "verdict") or "").lower()
    fixes = []
    for block in re.findall(r"<fix>(.*?)</fix>", text, re.S | re.I):
        read, printed = tag_body(block, "read"), tag_body(block, "printed")
        if read is not None and printed is not None and read.strip() != printed.strip():
            fixes.append((read.strip(), printed.strip()))
    page = tag_body(text, "markdown")
    ok = verdict.startswith("ok") or (not verdict and not fixes and page is None)
    return ok and not fixes and not page, fixes, clean(page) if page else None


def parse_arbitration(text: str) -> dict[int, str]:
    """The arbiter's numbered lines ("1: …") → {1: "…"}; "?" where it couldn't read the place."""
    out: dict[int, str] = {}
    for n, said in re.findall(r"^\s*(\d+)\s*[:.)]\s*(.*?)\s*$", clean(text), re.M):
        out.setdefault(int(n), said.strip().strip("`").strip())
    return out


def parse_ocr_check(text: str) -> tuple[bool, list[str], str | None]:
    """Returns (ok, issues, corrected_markdown_or_None)."""
    text = clean(text)
    verdict = (tag_body(text, "verdict") or "").lower()
    issues_body = tag_body(text, "issues") or ""
    issues = [ln.lstrip("-* ").strip() for ln in issues_body.splitlines() if ln.strip().lstrip("-* ")]
    corrected = tag_body(text, "markdown")
    if corrected is not None:
        corrected = clean(corrected)
    ok = verdict.startswith("ok") or (not verdict and corrected is None)
    return ok and not corrected, issues, corrected or None


def parse_suggestions(text: str) -> list[dict]:
    """`<suggestion label="...">the request</suggestion>` → [{"label", "prompt"}] (AI assist)."""
    return [{"label": attrs.get("label", "").strip(), "prompt": clean(body)} for attrs, body in _tags(clean(text), "suggestion")]

"""Structured (JSON-schema) output for the translator, refiner and reviewer.

Translation stays page level: one call per page, the model sees and writes the whole page. The
reply is a JSON object constrained by a schema built *for that call* — segment ids are an enum of
exactly the ids in the prompt — so the model can't invent, rename or drop-and-replace ids, and
terms / terminology / brief are typed fields instead of tags parsed out of free text.

Models without structured outputs keep the tag format (STRUCTURED_OUTPUT=off, or a hosted model LiteLLM
says has none); parsing
always tries JSON first and falls back to tags, so either reply works.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import Step, step_model
from .replies import clean, term_from

log = logging.getLogger(__name__)

JSON_SENTINEL = "Respond with JSON matching the provided schema"
_SEG_ID = re.compile(r'<(?:seg|pair) id="([^"]+)"')
# MQM core dimensions (fluency = linguistic conventions, locale = locale conventions, markup = design and markup).
CATEGORIES = ["accuracy", "fluency", "terminology", "style", "locale", "markup"]
SEVERITIES = ["minor", "major", "critical"]


# --------------------------------------------------------------------------- #
# Schemas (OpenAI strict-mode compatible: every property required, no extras)
# --------------------------------------------------------------------------- #


def _obj(props: dict[str, Any]) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _str(enum: list[str] | None = None) -> dict:
    return {"type": "string", "enum": enum} if enum else {"type": "string"}


def _arr(items: dict) -> dict:
    return {"type": "array", "items": items}


def _ids(ids: list[str]) -> dict:
    # A long document (the analysis sees all of it) would make a huge enum: plain strings then.
    return _str(ids if len(ids) <= 300 else None)


def _term_props(ids: list[str]) -> dict[str, Any]:
    """A term the author may need to decide, explained for someone who doesn't read the source language."""
    return {
        "source": _str(),
        "meaning": _str(),
        "options": _arr(_obj({"target": _str(), "note": _str()})),
        "recommended": {"type": "integer"},
        "segment_ids": _arr(_ids(ids)),
        "reason": _str(),
    }


def _terms(ids: list[str]) -> dict:
    return _arr(_obj(_term_props(ids)))


def analysis_schema(ids: list[str]) -> dict:
    term = _obj({**_term_props(ids), "gist": _str(), "ambiguous": {"type": "boolean"}})
    return {"title": "document_analysis", **_obj({"source_language": _str(), "brief": _str(), "terms": _arr(term)})}


def translation_schema(ids: list[str]) -> dict:
    return {
        "title": "page_translation",
        **_obj(
            {
                "segments": _arr(_obj({"id": _str(ids), "translation": _str()})),
                "terminology": _arr(_obj({"source": _str(), "target": _str()})),
                "uncertain_terms": _terms(ids),
                "brief": _str(),
                "source_language": _str(),
            }
        ),
    }


def refine_schema(ids: list[str]) -> dict:
    return {"title": "revised_segments", **_obj({"segments": _arr(_obj({"id": _str(ids), "translation": _str()}))})}


def _scores(ids: list[str]) -> dict:
    return _arr(_obj({"segment_id": _str(ids), "score": {"type": "integer"}}))


def review_schema(ids: list[str]) -> dict:
    issue = _obj(
        {
            "segment_id": _str(ids),
            "severity": _str(SEVERITIES),
            "category": _str(CATEGORIES),
            "problem": _str(),
            "suggestion": _str(),
        }
    )
    return {"title": "review", **_obj({"issues": _arr(issue), "scores": _scores(ids), "uncertain_terms": _terms(ids)})}


def lqa_schema(ids: list[str]) -> dict:
    error = _obj(
        {
            "segment_id": _str(ids),
            "category": _str(CATEGORIES),
            "severity": _str(SEVERITIES),
            "span": _str(),
            "problem": _str(),
            "suggestion": _str(),
        }
    )
    return {"title": "lqa", **_obj({"errors": _arr(error), "scores": _scores(ids)})}


def alternatives_schema(ids: list[str]) -> dict:
    alt = _obj({"text": _str(), "note": _str()})
    return {"title": "alternatives", **_obj({"segments": _arr(_obj({"id": _str(ids), "alternatives": _arr(alt)}))})}


SCHEMA_FOR_AGENT = {
    "analyst": analysis_schema,
    "translator": translation_schema,
    "refiner": refine_schema,
    "reviewer": review_schema,
    "lqa_reviewer": lqa_schema,
    "rewriter": alternatives_schema,
    "consistency_fixer": refine_schema,
}


def inject_schema(callback_context, llm_request):
    """before_model_callback: constrain this call to a schema built from the segment ids in its prompt.

    Only when the prompt asked for JSON (the pipeline decides per model); tag-format prompts pass through.
    """
    builder = SCHEMA_FOR_AGENT.get(callback_context.agent_name)
    if builder is None:
        return None
    text = "\n".join(p.text or "" for c in llm_request.contents for p in c.parts or [] if p.text)
    ids = list(dict.fromkeys(_SEG_ID.findall(text)))
    if ids and JSON_SENTINEL in text:
        llm_request.config.response_schema = builder(ids)
    return None


# --------------------------------------------------------------------------- #
# Which models get structured output
# --------------------------------------------------------------------------- #


def enabled(step: Step) -> bool:
    """The step's model answers in JSON constrained by a schema (models.yaml `structured_output`), else tags."""
    return step_model(step).structured_output


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def parse_json(text: str) -> dict | None:
    t = clean(text)
    for candidate in (t, (re.search(r"\{.*\}", t, re.S) or [None])[0]):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _items(obj: dict, key: str) -> list[dict]:
    return [x for x in obj.get(key) or [] if isinstance(x, dict)]


def segments_from(obj: dict) -> dict[str, str]:
    return {
        str(s["id"]).strip(): clean(str(s.get("translation") or ""))
        for s in _items(obj, "segments")
        if s.get("id")
    }


def terms_from(obj: dict, key: str = "uncertain_terms") -> list[dict]:
    return [x for x in map(term_from, _items(obj, key)) if x]


def terminology_from(obj: dict) -> dict[str, str]:
    return {
        str(k["source"]).strip(): str(k["target"]).strip()
        for k in _items(obj, "terminology")
        if str(k.get("source") or "").strip() and str(k.get("target") or "").strip()
    }


def severity(value: object) -> str:
    v = str(value or "").strip().lower()
    return "critical" if v.startswith("crit") else "major" if v.startswith("maj") else "minor"


def category(value: object) -> str | None:
    v = str(value or "").strip().lower()
    aliases = {"linguistic conventions": "fluency", "grammar": "fluency", "locale conventions": "locale",
               "design": "markup", "design and markup": "markup", "consistency": "terminology"}
    v = aliases.get(v, v)
    return v if v in CATEGORIES else None


def issues_from(obj: dict, key: str = "issues") -> list[dict]:
    """Review issues / LQA errors, tolerant of missing or unknown fields."""
    issues = []
    for i in _items(obj, key):
        if not i.get("segment_id"):
            continue
        problem, fix = str(i.get("problem") or "").strip(), str(i.get("suggestion") or "").strip()
        issues.append(
            {
                "segment_id": str(i["segment_id"]),
                "severity": severity(i.get("severity")),
                "category": category(i.get("category")),
                "span": str(i.get("span") or "").strip(),
                "note": f"{problem} → {fix}" if problem and fix else (problem or fix),
            }
        )
    return [i for i in issues if i["note"]]


def alternatives_from(obj: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for s in _items(obj, "segments"):
        sid = str(s.get("id") or "").strip()
        alts = [{"text": clean(str(a.get("text") or "")), "note": str(a.get("note") or "").strip()}
                for a in s.get("alternatives") or [] if isinstance(a, dict)]
        if sid and alts:
            out[sid] = [a for a in alts if a["text"]]
    return out


def scores_from(obj: dict) -> dict[str, int]:
    out = {}
    for x in _items(obj, "scores"):
        try:
            out[str(x["segment_id"])] = max(0, min(100, round(float(x["score"]))))
        except (KeyError, TypeError, ValueError):
            continue
    return out

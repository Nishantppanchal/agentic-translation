"""Terminology references the agents consult besides the glossary: the dictionary service (when it is set up and
turned on for the document), the translation memory and the project termbase."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from rapidfuzz import fuzz

from . import projects
from .integrations import dictionary
from .text import contains_term

DOC_DICTIONARY = "doc:dictionary"  # True / False for this document; absent: the app's setting
NOT_CONFIGURED = ("No dictionary service is set up: set DICTIONARY_URL in backend/.env and restart the backend "
                  "(the contract is in dictionary-server/README.md).")


def dictionary_on(state: Mapping[str, Any] | None = None) -> bool:
    """The dictionary is used for this document (or, without a state, for new documents)."""
    from . import app_settings  # local: app_settings → models → agents

    if not dictionary.configured():
        return False
    value = state.get(DOC_DICTIONARY) if state is not None else None
    return app_settings.load().dictionary if value is None else bool(value)


def dictionary_status(state: Mapping[str, Any] | None = None) -> dict:
    """{available, enabled, reason}: what the Settings and the document's settings show."""
    available = dictionary.configured()
    return {"available": available, "enabled": dictionary_on(state), "reason": None if available else NOT_CONFIGURED}


# --------------------------------------------------------------------------- #
# Evidence for the analysis: does the translation memory or the dictionary back the AI's guess?
# Precedence: the project termbase and the person's answers (settled before this runs) > TM > dictionary > AI.
# --------------------------------------------------------------------------- #

_ARTICLES = re.compile(r"^(?:the|a|an)\s+", re.I)


def _plain(text: str) -> str:
    return _ARTICLES.sub("", re.sub(r"[^\w\s-]", " ", text or "").casefold()).strip()


def agrees(a: str, b: str) -> bool:
    """Two English renderings of a term are the same choice ("the cable tray" ≈ "cable trays")."""
    a, b = _plain(a), _plain(b)
    return bool(a and b) and (a == b or fuzz.token_set_ratio(a, b) >= 90 or a.rstrip("s") == b.rstrip("s"))


def tm_examples(state: Mapping[str, Any], terms: list[str], per_term: int = 3) -> dict[str, list[dict]]:
    """{term: [{source, target, ref}]}: translation-memory units whose source uses the term (blocking: run in a
    thread). Empty outside a project."""
    pid = projects.project_id(state)
    if not pid:
        return {}
    store = projects.get_store()
    out: dict[str, list[dict]] = {}
    for term in terms:
        units = [u for u in store.concordance(pid, term, 30) if contains_term(u["source"], term)]
        if units:
            out[term] = [{"source": u["source"][:300], "target": u["target"][:300], "ref": u.get("ref") or ""}
                         for u in units[:per_term]]
    return out


def _candidates(term: dict) -> list[str]:
    seen, out = set(), []
    for c in [term.get("guess") or "", *(o.get("target", "") for o in term.get("options") or []),
              *(e.get("translation", "") for e in term.get("dictionary") or [])]:
        if c and c.casefold() not in seen:
            seen.add(c.casefold())
            out.append(c)
    return out


def tm_choice(term: dict) -> str | None:
    """The candidate rendering (the guess, an option or a dictionary translation) the TM's approved wording uses."""
    for example in term.get("tm") or []:
        for candidate in _candidates(term):
            plural = candidate + ("es" if candidate.endswith(("s", "x", "ch", "sh")) else "s")
            if contains_term(example["target"], candidate) or contains_term(example["target"], plural):
                return candidate
    return None


def _dictionary_targets(term: dict) -> list[str]:
    out: list[str] = []
    for e in term.get("dictionary") or []:
        t = e.get("translation", "")
        if t and not any(agrees(t, x) for x in out):
            out.append(t)
    return out


def reconcile(term: dict, room_for_question: bool) -> str:
    """Decide a key term from its evidence (`term["tm"]`, `term["dictionary"]`). Sets `term["guess"]` to the
    rendering used and returns how it was decided:
      tm          the translation memory's approved wording uses one of the candidates
      dictionary  the dictionary agrees with the AI's guess, or (no room for a question) gives one translation
      asked       a question for the person: the AI's guess and the dictionary disagree (or it was ambiguous)
      conflict    they disagree, no room to ask, several dictionary senses: the AI's guess stays, marked
      ai          no evidence either way
    An ambiguous term stays a question; a TM-backed option becomes its recommendation."""
    from_tm = tm_choice(term)
    if term.get("ambiguous"):
        if from_tm:
            options = term.setdefault("options", [])
            i = next((k for k, o in enumerate(options) if agrees(o.get("target", ""), from_tm)), None)
            if i is None:
                options.append({"target": from_tm, "note": "As in the translation memory"})
                i = len(options) - 1
            term["recommended"] = i
        return "asked"
    if from_tm:
        term["guess"] = from_tm
        return "tm"
    senses = _dictionary_targets(term)
    if not senses:
        return "ai"
    guess = term.get("guess") or ""
    if any(agrees(guess, s) for s in senses):
        return "dictionary"
    if room_for_question:
        source = next((e.get("source") for e in term.get("dictionary") or [] if e.get("source")), "The dictionary")
        options = [{"target": guess, "note": "The AI's reading of this document"}] if guess else []
        for sense in senses:
            definition = next((e.get("definition", "") for e in term["dictionary"] if agrees(e.get("translation", ""), sense)), "")
            options.append({"target": sense, "note": f"{source}: {definition}" if definition else source})
        # One clear dictionary sense is recommended over the guess; several senses: the document decides (the guess).
        term.update(ambiguous=True, options=options[:4], recommended=1 if guess and len(senses) == 1 else 0,
                    reason=f"Dictionary disagrees: {source} gives {', '.join(senses[:3])}" + (f", not “{guess}”" if guess else ""))
        return "asked"
    if len(senses) == 1:
        term["note"] = f"AI guess was “{guess}”" if guess else ""
        term["guess"] = senses[0]
        return "dictionary"
    return "conflict"


def evidence_text(state: Mapping[str, Any], batch: list[dict], terms: int = 10, entries: int = 3) -> str:
    """Dictionary senses and TM examples for the key terms in these segments (the glossary's aren't repeated):
    references for the translator and reviewer, below the glossary in priority. No network call."""
    glossary = {g.casefold() for g in state.get("doc:glossary") or {}}
    lines = []
    for key in state.get("doc:key_terms") or []:
        term = key.get("term", "")
        if not term or term.casefold() in glossary or not any(contains_term(s["source"], term) for s in batch):
            continue
        parts = []
        if senses := key.get("dictionary"):
            parts.append("dictionary: " + "; ".join(
                f"{e.get('translation', '')}" + (f" ({e['definition'][:120]})" if e.get("definition") else "")
                + (f" [{e['source']}]" if e.get("source") else "") for e in senses[:entries]))
        if examples := key.get("tm"):
            parts.append("translation memory: " + "; ".join(f"“{x['source'][:120]}” → “{x['target'][:120]}”" for x in examples[:entries]))
        if parts:
            lines.append(f"- {term}: " + " | ".join(parts))
        if len(lines) >= terms:
            break
    return "\n".join(lines) or "(none)"


def add_dictionary_options(term: dict, limit: int = 4) -> None:
    """A dictionary translation the analysis didn't offer becomes one more option, credited to its source."""
    options = term.setdefault("options", [{"target": term["guess"], "note": ""}] if term.get("guess") else [])
    have = {o["target"].casefold() for o in options}
    for entry in term.get("dictionary", []):
        target = entry.get("translation", "")
        if target and target.casefold() not in have and len(options) < limit:
            options.append({"target": target, "note": f"{entry.get('source', 'Dictionary')}: {entry.get('definition', '')}".strip(": ")})
            have.add(target.casefold())


# --------------------------------------------------------------------------- #
# Lookups shown in the chat (timeline item kind "lookup")
# --------------------------------------------------------------------------- #

LOOKUP = "lookup"  # custom_metadata[UI] of a pipeline lookup event; its payload is under custom_metadata["lookup"]


def dictionary_entry(e: dict) -> dict:
    detail = " · ".join(x for x in (e.get("definition", ""), e.get("domain", "")) if x)
    return {"target": e.get("translation", ""), "detail": detail[:300], "ref": e.get("source", "")}


def tm_entry(m: dict) -> dict:
    return {"target": m.get("target", ""), "source_text": m.get("source", ""), "score": m.get("score"), "ref": m.get("ref", ""),
            **({"badge": "bulk"} if m.get("approval") == "bulk" else {})}


def lookup_payload(source: str, purpose: str, results: list[dict], *, via: str = "pipeline", status: str = "done",
                   queries: int | None = None, note: str = "") -> dict:
    """What a lookup item shows: source dictionary | tm | termbase; results [{query, entries, outcome?}] (≤20)."""
    return {"source": source, "via": via, "status": status, "purpose": purpose, "queries": queries if queries is not None else len(results),
            "hits": sum(1 for r in results if r.get("entries")), "results": results[:20], **({"note": note} if note else {})}


def lookup_event(payload: dict, text: str, state: dict | None = None):
    """A pipeline lookup as a chat item (stored like any message, so it comes back after a reload)."""
    from google.adk import Event
    from google.genai import types

    from .agents.common import UI

    return Event(content=types.Content(role="model", parts=[types.Part(text=text)]),
                 custom_metadata={UI: LOOKUP, LOOKUP: payload}, state=state or {})

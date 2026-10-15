"""The chat editor's reference tools: the dictionary, the project's translation memory and the termbase.

Read-only. Which ones the editor gets depends on the document (`ReferenceToolset`): the termbase always, the TM in a
project, the dictionary when it is set up and on. Every result has the same shape, which the chat shows as a lookup
(api/timeline.py): {source, query, status: found | not found | off | unavailable | limit, hits, results}. At most
MAX_PER_TURN lookups per chat turn.
"""

from __future__ import annotations

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools import BaseTool, FunctionTool, ToolContext
from google.adk.tools.base_toolset import BaseToolset

from .. import projects, references
from ..document import state as st
from ..integrations import dictionary
from ..text import contains_term

MAX_PER_TURN = 8
MAX_RESULTS = 5
_COUNT = "temp:lookup_calls"  # per invocation (temp: state isn't saved)
# The lookup tools the chat shows as lookups ("look_up_term": the dictionary tool's name in older documents).
NAMES = {"look_up_dictionary": "dictionary", "look_up_term": "dictionary", "search_tm": "tm", "tm_concordance": "tm",
         "look_up_termbase": "termbase"}


def _result(source: str, query: str, results: list[dict], status: str | None = None, message: str = "") -> dict:
    out = {"source": source, "query": query, "status": status or ("found" if results else "not found"),
           "hits": len(results), "results": results[:MAX_RESULTS]}
    if message:
        out["message"] = message
    return out


def _over_limit(tool_context: ToolContext, source: str, query: str) -> dict | None:
    n = tool_context.state.get(_COUNT, 0) + 1
    tool_context.state[_COUNT] = n
    if n > MAX_PER_TURN:
        return _result(source, query, [], "limit", f"That's {MAX_PER_TURN} lookups this turn: answer with what you have.")
    return None


async def look_up_dictionary(term: str, tool_context: ToolContext) -> dict:
    """Look a source-language term up in the dictionary service: English translations with their definition,
    domain and source (e.g. IATE). Use it before explaining or choosing a translation for a specialised term.

    Args:
      term: The term as it appears in the source text.
    """
    term = term.strip()
    if limit := _over_limit(tool_context, "dictionary", term):
        return limit
    if not references.dictionary_on(tool_context.state):
        return _result("dictionary", term, [], "off", "The dictionary is turned off for this document.")
    state = tool_context.state
    lang = state.get("doc:detected_lang") or state.get("doc:source_lang")
    entries = (await dictionary.lookup([term], lang)).get(term, [])
    return _result("dictionary", term, [references.dictionary_entry(e) for e in entries])


def search_tm(sentence: str, tool_context: ToolContext) -> dict:
    """Find earlier human-approved translations of a sentence like this one in the project's translation memory
    (101 = same sentence in the same context, 100 = same sentence, 75-99 = similar). Use the exact source text.

    Args:
      sentence: A source sentence or segment text.
    """
    sentence = sentence.strip()
    if limit := _over_limit(tool_context, "tm", sentence):
        return limit
    pid = projects.project_id(tool_context.state)
    if not pid:
        return _result("tm", sentence, [], "unavailable", "This document isn't in a project, so there is no translation memory.")
    matches = projects.get_store().lookup(pid, sentence, "", MAX_RESULTS)
    return _result("tm", sentence, [references.tm_entry(m) for m in matches])


def tm_concordance(text: str, tool_context: ToolContext) -> dict:
    """Search the project's translation memory for units containing a word or phrase (in either language), to
    see how it was translated before.

    Args:
      text: A word or phrase, in the source language or in English.
    """
    text = text.strip()
    if limit := _over_limit(tool_context, "tm", text):
        return limit
    pid = projects.project_id(tool_context.state)
    if not pid:
        return _result("tm", text, [], "unavailable", "This document isn't in a project, so there is no translation memory.")
    units = projects.get_store().concordance(pid, text, MAX_RESULTS)
    return _result("tm", text, [{"source_text": u["source"][:300], "target": u["target"][:300], "ref": u.get("ref") or "",
                                 **({"badge": "bulk"} if u.get("approval") == "bulk" else {})} for u in units])


def look_up_termbase(term: str, tool_context: ToolContext) -> dict:
    """How a term is decided for this document, strongest first: the project termbase (approved, or only proposed),
    the user's answers (glossary), then the terminology the translator chose (not verified).

    Args:
      term: The source-language term.
    """
    term = term.strip()
    if limit := _over_limit(tool_context, "termbase", term):
        return limit
    state = tool_context.state
    key = term.casefold()
    out: list[dict] = []
    if pid := projects.project_id(state):
        for t in projects.get_store().terms(pid):
            if t["source"].casefold() == key or contains_term(term, t["source"]):
                out.append({"target": t["target"], "detail": t.get("note", ""), "badge": f"project · {t.get('status', 'approved')}",
                            **({"forbidden": t["forbidden"]} if t.get("forbidden") else {})})
    for source, entry in st.effective_glossary(state).items():
        if source.casefold() == key and entry.get("target"):
            out.append({"target": entry["target"], "detail": entry.get("note", ""), "badge": "your answer"})
    for source, target in (state.get("doc:termbase") or {}).items():
        if source.casefold() == key:
            out.append({"target": target, "badge": "chosen by the translator (not verified)"})
    return _result("termbase", term, out)


class ReferenceToolset(BaseToolset):
    """The reference tools this document can use (evaluated for every chat turn)."""

    def __init__(self) -> None:
        super().__init__()
        self._tools = {f.__name__: FunctionTool(f) for f in (look_up_dictionary, search_tm, tm_concordance, look_up_termbase)}

    async def get_tools(self, readonly_context: ReadonlyContext | None = None) -> list[BaseTool]:
        state = readonly_context.state if readonly_context is not None else {}
        names = ["look_up_termbase"]
        if projects.project_id(state):
            names += ["search_tm", "tm_concordance"]
        if references.dictionary_on(state):
            names.append("look_up_dictionary")
        return [self._tools[n] for n in names]


def available(state) -> str:
    """For the editor's instruction: which references it can look things up in."""
    parts = ["the termbase (look_up_termbase)"]
    if projects.project_id(state):
        parts.append("the project's translation memory (search_tm, tm_concordance)")
    if references.dictionary_on(state):
        parts.append("the dictionary (look_up_dictionary)")
    return ", ".join(parts)

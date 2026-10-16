"""AI assist: small model calls made straight from the API, outside any run — the chat's suggested next prompts,
Tab completions in the chat box, and the translation summary for the client. Each uses its own step's model for the document
(`suggest`, `complete`, `notes`; set in pipeline.yaml, changed in Settings; models/routing.py), and its tokens are counted in projects.db (`assist_usage`): these calls
leave no session event, so they never show in the chat or collide with a run.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from .. import projects
from ..document import notes
from ..models import routing, structured
from ..models.config import Step
from ..models.replies import clean, parse_suggestions
from . import prompts

log = logging.getLogger(__name__)


async def ask(step: Step, state: Mapping[str, Any], prompt: str, *, session_id: str, schema: dict | None = None,
              max_tokens: int | None = None) -> tuple[str, dict | None]:
    """One call to the step's model for this document → (reply text, its JSON object if it answered in JSON).
    A schema is used only when the model does structured output. Raises when the call fails."""
    model = routing.llm(step, state)
    request = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text=prompt)])])
    request.config.system_instruction = prompts.ASSIST_SYSTEM
    if schema is not None and structured.enabled(step, state):
        request.config.response_schema = schema
    spec = routing.resolve(step, state)
    if max_tokens and spec.effort in (None, "instant"):  # a thinking model needs room to think
        request.config.max_output_tokens = max_tokens
    replies = [r async for r in model.generate_content_async(request)]
    text = "".join(p.text or "" for r in replies if r.content for p in r.content.parts or [] if not p.thought)
    await asyncio.to_thread(_record, session_id, step, spec.id, replies)
    return text, structured.parse_json(text) if schema is not None else None


def _record(session_id: str, step: str, model_id: str, replies: list) -> None:
    prompt = completion = thoughts = 0
    effort = None
    for r in replies:
        if u := r.usage_metadata:
            prompt += u.prompt_token_count or 0
            completion += u.candidates_token_count or 0
            thoughts += u.thoughts_token_count or 0
        meta = r.custom_metadata or {}
        model_id, effort = meta.get("model_id") or model_id, meta.get("effort", effort)
    try:
        projects.get_store().record_assist_usage(session_id, step, model_id, effort, prompt, completion, thoughts)
    except Exception:  # noqa: BLE001 — counting must never break the feature
        log.exception("couldn't record the usage of an assist call")


class _Lru(OrderedDict):
    def __init__(self, size: int):
        super().__init__()
        self.size = size

    def put(self, key, value) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.size:
            self.popitem(last=False)


_suggestions = _Lru(256)
_completions = _Lru(1024)


def _chat(events, n: int = 6) -> str:
    from ..api.timeline import history  # local: the API layer imports agents, not the other way round

    turns = [i for i in history(events) if i["kind"] in ("user", "assistant")][-n:]
    return "\n".join(f"{'Person' if t['kind'] == 'user' else 'Assistant'}: {notes._short(t['text'], 500)}" for t in turns)


def context(state: Mapping[str, Any], events, *, chat_turns: int = 6) -> str:
    d = notes.digest(state)
    chat = _chat(events, chat_turns)
    return notes.as_text(d, for_notes=False) + (f"\n\nThe chat so far (oldest first):\n{chat}" if chat else "\n\nNo chat yet.")


async def suggestions(session_id: str, state: Mapping[str, Any], events) -> tuple[list[dict], bool]:
    """Up to 3 next requests for the chat → (suggestions, from the cache). Cached per document and its last event,
    so a reload asks nothing new."""
    key = (session_id, events[-1].id if events else "")
    if key in _suggestions:
        return _suggestions[key], True
    use_json = structured.enabled("suggest", state)
    prompt = prompts.SUGGEST.format(can=prompts.CHAT_CAN, digest=context(state, events),
                                    output_format=prompts.SUGGEST_FORMAT_JSON if use_json else prompts.SUGGEST_FORMAT_TAGS)
    text, obj = await ask("suggest", state, prompt, session_id=session_id, schema=structured.suggestions_schema())
    found = obj.get("suggestions") if isinstance(obj, dict) else None
    items = [x for x in found if isinstance(x, dict)] if isinstance(found, list) else parse_suggestions(text)
    out = []
    for x in items:
        label, request = " ".join(str(x.get("label") or "").split()), " ".join(str(x.get("prompt") or "").split())
        if label and request and request.casefold() not in {o["prompt"].casefold() for o in out}:
            out.append({"label": " ".join(label.split()[:6]).rstrip("."), "prompt": request})
    _suggestions.put(key, out[:3])
    return out[:3], False


_COMPLETION = re.compile(r"<completion>(.*?)(?:</completion>|$)", re.S | re.I)


def tidy_completion(text: str, typed: str) -> str:
    """The model's next words, ready to append to what is typed: one line, no repetition of the typed text, at
    most ~12 words, the leading space kept (none when it finishes a word)."""
    found = _COMPLETION.search(clean(text) if "<completion" not in text else text)
    body = found.group(1) if found else clean(text)
    body = body.split("\n", 1)[0].rstrip().strip('"“”')
    if not body.strip():
        return ""
    stripped = body.lstrip()
    tail = typed.rstrip()
    if tail and stripped.casefold().startswith(tail.casefold()):  # the model wrote the whole message out
        body = stripped[len(tail):]
        if typed[-1:].isspace():
            body = body.lstrip()
    elif typed[-1:].isspace():
        body = stripped  # the space is typed already
    elif typed[-1:] in tuple(",.;:!?)") and stripped[:1].isalnum():
        body = " " + stripped
    # otherwise as the model gave it: a leading space starts a new word, none finishes the typed one
    words = body.split(" ")
    if len([w for w in words if w]) > 12:
        body = " ".join(words[: 13 if body.startswith(" ") else 12])
    return body if body.strip() else ""


async def complete(session_id: str, state: Mapping[str, Any], events, text: str) -> str:
    key = (session_id, text)
    if key in _completions:
        return _completions[key]
    prompt = prompts.COMPLETE.format(digest=context(state, events, chat_turns=2), text=text)
    reply, _ = await ask("complete", state, prompt, session_id=session_id, max_tokens=48)
    out = tidy_completion(reply, text)
    _completions.put(key, out)
    return out


async def client_notes(session_id: str, state: Mapping[str, Any]) -> str:
    d = notes.digest(state)
    prompt = prompts.NOTES.format(source_lang=d["source_lang"], name=d["title"] or d["name"], digest=notes.as_text(d))
    text, _ = await ask("notes", state, prompt, session_id=session_id)
    return clean(text).strip()

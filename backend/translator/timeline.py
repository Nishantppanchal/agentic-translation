"""Translate ADK events into the compact timeline items / stream events the UI renders.

The same mapping is used for live SSE streaming and for rebuilding chat history
from persisted session events, so ids line up and the client can de-duplicate.
"""

from __future__ import annotations

from typing import Any

from google.adk.events import Event

from .agents.editor import EDITOR_NAME
from .agents.pipeline import UI

# Raw outputs of the pipeline's worker agents (OCR text, translations) are not chat content.
HIDDEN_AUTHORS = {"ocr_extractor", "ocr_checker", "figure_detector", "translator", "reviewer", "refiner"}
WATCHED_STATE = ("doc:", "seg:")


def _text(ev: Event) -> str:
    if not ev.content:
        return ""
    text = "".join(p.text or "" for p in ev.content.parts or [] if p.text and not p.thought)
    # Streamed chunks are deltas: their leading/trailing whitespace is significant.
    return text if ev.partial else text.strip()


def event_items(ev: Event) -> list[dict[str, Any]]:
    """Timeline items for one event (partial events produce a streaming draft item)."""
    items: list[dict[str, Any]] = []
    ts = ev.timestamp
    author = ev.author or ""

    if author == "user":
        text = _text(ev)
        if text and not ev.get_function_responses():
            items.append({"kind": "user", "id": ev.id, "text": text, "ts": ts})
        return items

    delta = ev.actions.state_delta if ev.actions else None
    if delta and "doc:versions" in delta and delta["doc:versions"]:
        v = delta["doc:versions"][-1]
        items.append(
            {
                "kind": "version",
                "id": f"version-{v['version']}",
                "version": v["version"],
                "note": v.get("note", ""),
                "changed": v.get("changed", []),
                "ts": ts,
            }
        )
    if author not in HIDDEN_AUTHORS:
        # Partial (streaming) events can carry incomplete function calls; wait for the final event.
        for i, fc in enumerate([] if ev.partial else ev.get_function_calls()):
            if fc.name == "adk_request_input":  # the clarify pause; the UI shows question cards instead
                continue
            items.append(
                {
                    "kind": "tool",
                    "id": fc.id or f"{ev.id}-fc{i}",
                    "author": author,
                    "name": fc.name,
                    "args": dict(fc.args or {}),
                    "ts": ts,
                }
            )
        text = _text(ev)
        if text:
            # Pipeline / system messages say how to render themselves; the editor's text is a reply.
            kind = (ev.custom_metadata or {}).get(UI) or ("assistant" if author == EDITOR_NAME else None)
            if kind == "activity":
                items.append({"kind": "activity", "id": ev.id, "author": author, "text": text, "ts": ts})
            elif kind == "assistant":
                if ev.partial:
                    items.append(
                        {
                            "kind": "assistant",
                            "id": f"draft-{ev.invocation_id}-{author}",
                            "author": author,
                            "text": text,
                            "ts": ts,
                            "partial": True,
                        }
                    )
                else:
                    items.append({"kind": "assistant", "id": ev.id, "author": author, "text": text, "ts": ts})

    if ev.error_message:
        items.append({"kind": "error", "id": f"{ev.id}-err", "text": ev.error_message, "ts": ts})
    return items


def history(events: list[Event]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ev in events:
        if ev.partial:
            continue
        for item in event_items(ev):
            if item["id"] not in seen:
                seen.add(item["id"])
                items.append(item)
    return items


def stream_events(ev: Event, partial_text: dict[str, str]) -> list[dict[str, Any]]:
    """SSE payloads for one live event. `partial_text` accumulates streamed chunks per draft id."""
    out: list[dict[str, Any]] = []
    for item in event_items(ev):
        if item.get("partial"):
            # ADK SSE partial events carry deltas; accumulate into the draft.
            partial_text[item["id"]] = partial_text.get(item["id"], "") + item["text"]
            item = {**item, "text": partial_text[item["id"]]}
        elif item["kind"] == "assistant":
            partial_text.pop(f"draft-{ev.invocation_id}-{item['author']}", None)
        out.append({"type": "timeline", "item": item})

    delta = ev.actions.state_delta if ev.actions else None
    if delta:
        if "doc:progress" in delta and delta["doc:progress"]:
            out.append({"type": "progress", "progress": delta["doc:progress"], "status": delta.get("doc:status")})
        keys = [k for k in delta if k.startswith(WATCHED_STATE) and k != "doc:progress"]
        if keys:
            out.append({"type": "state", "keys": keys})
    return out


REQUEST_INPUT = "adk_request_input"


def pending_interrupt(events: list[Event]) -> str | None:
    """Function-call id of the workflow's unanswered RequestInput, if it is paused. Ids repeat (a retried
    document asks again with the same id), so calls and responses are matched by count."""
    calls: dict[str, int] = {}
    answered: dict[str, int] = {}
    last = None
    for ev in events:
        for fc in ev.get_function_calls():
            if fc.name == REQUEST_INPUT:
                calls[fc.id] = calls.get(fc.id, 0) + 1
                last = fc.id
        for fr in ev.get_function_responses():
            answered[fr.id] = answered.get(fr.id, 0) + 1
    pending = [i for i, n in calls.items() if n > answered.get(i, 0)]
    return last if last in pending else (pending[-1] if pending else None)

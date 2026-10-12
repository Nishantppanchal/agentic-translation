"""Helpers shared by the pipeline steps and the task workflows: messages, progress, bounded concurrency."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

from google.adk import Context, Event
from google.genai import types

from ..document import state as st

T = TypeVar("T")


UI = "ui"  # custom_metadata key telling the API how to show a message event


def user_message(*parts: types.Part | str) -> types.Content:
    return types.Content(
        role="user", parts=[types.Part(text=p) if isinstance(p, str) else p for p in parts]
    )


def reply_text(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, types.Content):
        return "".join(p.text or "" for p in output.parts or [] if not p.thought)
    return output if isinstance(output, str) else json.dumps(output)


def progress_state(stage: str, current: int, total: int, message: str, status: str | None = None) -> dict:
    delta: dict[str, Any] = {"doc:progress": {"stage": stage, "current": current, "total": total, "message": message}}
    if status:
        delta["doc:status"] = status
    return delta


def say(text: str, kind: str = "activity", state: dict | None = None) -> Event:
    """A chat-visible message from the pipeline (kind: activity | assistant)."""
    return Event(
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        custom_metadata={UI: kind},
        state=state or {},
    )


async def run_bounded(tasks: list[Callable[[], Awaitable[T]]], limit: int) -> AsyncIterator[tuple[int, T]]:
    """Run task factories with a concurrency limit, yielding (index, result) as each finishes."""
    sem = asyncio.Semaphore(max(1, limit))

    async def run(i: int, make: Callable[[], Awaitable[T]]) -> tuple[int, T]:
        async with sem:
            return i, await make()

    pending = [asyncio.create_task(run(i, t)) for i, t in enumerate(tasks)]
    try:
        for fut in asyncio.as_completed(pending):
            yield await fut
    finally:
        for p in pending:
            p.cancel()


def doc_langs(state) -> tuple[str, str]:
    source = state.get("doc:source_lang") or "auto-detect"
    if source.lower().startswith("auto"):
        source = state.get("doc:detected_lang") or "the source language (detect it)"
    return source, state.get("doc:target_lang") or "English"


def pair_text(segments: list[dict]) -> str:
    return "\n\n".join(
        f'<pair id="{s["id"]}">\nSOURCE:\n{s["source"]}\n\nTRANSLATION:\n{s.get("target") or ""}\n</pair>'
        for s in segments
    )


async def save_version(ctx: Context, note: str, changed: list[str], snap: dict[str, str] | None = None) -> dict:
    """Snapshot the translation as a new artifact version; returns the state delta to apply."""
    snap = snap if snap is not None else st.snapshot(ctx.state)
    adk_version = await ctx.save_artifact(st.TRANSLATION_ARTIFACT, types.Part(text=json.dumps(snap, ensure_ascii=False)))
    versions = list(ctx.state.get("doc:versions") or [])
    entry = st.new_version_entry(ctx.state, len(versions) + 1, note, changed)[-1]
    entry["artifact_version"] = adk_version
    return {"doc:versions": [*versions, entry], "doc:dirty": []}


def scope(batch: list[dict], part: int | None = None) -> str:
    pages = sorted({s["page"] for s in batch})
    label = f"page {pages[0]}" if len(pages) == 1 else f"pages {pages[0]}–{pages[-1]}"
    return f"{label}, part {part}" if part else label

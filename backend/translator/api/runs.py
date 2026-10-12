"""Background run manager: one agent run per session, fanned out to SSE subscribers.

Runs execute as asyncio tasks so a long pipeline keeps going when the browser tab
closes; a reconnecting client gets the buffered events of the active run replayed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..models.llm import error_text

log = logging.getLogger(__name__)

Emit = Callable[[dict[str, Any]], None]


@dataclass
class _Run:
    task: asyncio.Task | None = None
    buffer: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    finished: bool = False


class RunManager:
    """`max_heavy`: how many heavy runs (pipelines, tasks) may work at once across all documents —
    uploading several documents queues the rest instead of flooding the model API.
    Chat turns are light and never wait."""

    def __init__(self, max_heavy: int = 2) -> None:
        self._runs: dict[str, _Run] = {}
        self._heavy = asyncio.Semaphore(max(1, max_heavy))

    def is_running(self, session_id: str) -> bool:
        run = self._runs.get(session_id)
        return bool(run and not run.finished)

    def start(self, session_id: str, work: Callable[[Emit], Awaitable[None]], heavy: bool = False) -> None:
        if self.is_running(session_id):
            raise RuntimeError("A run is already in progress for this document.")
        run = _Run()
        self._runs[session_id] = run

        def emit(event: dict[str, Any]) -> None:
            # Streaming drafts re-send the accumulated text; keep only the latest copy for replay.
            item = event.get("item") or {}
            if item.get("partial") and run.buffer and (run.buffer[-1].get("item") or {}).get("id") == item.get("id"):
                run.buffer[-1] = event
            else:
                run.buffer.append(event)
            for q in list(run.subscribers):
                q.put_nowait(event)

        async def wrapper() -> None:
            try:
                if heavy:
                    if self._heavy.locked():
                        emit({"type": "progress", "status": None, "progress": {
                            "stage": "queued", "current": 0, "total": 0, "message": "Queued: waiting for another document to finish…"}})
                    async with self._heavy:
                        await work(emit)
                else:
                    await work(emit)
            except asyncio.CancelledError:
                emit({"type": "error", "message": "Run cancelled."})
                raise
            except Exception as exc:  # surface agent/model failures to the UI
                log.exception("run failed for session %s", session_id)
                emit({"type": "error", "message": error_text(exc)})
            finally:
                run.finished = True
                emit({"type": "done"})

        run.task = asyncio.create_task(wrapper())

    async def subscribe(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        run = self._runs.get(session_id)
        if not run or run.finished:
            yield {"type": "idle"}
            return
        q: asyncio.Queue = asyncio.Queue()
        for ev in run.buffer:
            q.put_nowait(ev)
        run.subscribers.add(q)
        try:
            while True:
                ev = await q.get()
                yield ev
                if ev["type"] == "done":
                    return
        finally:
            run.subscribers.discard(q)

    def cancel(self, session_id: str) -> None:
        run = self._runs.pop(session_id, None)
        if run and run.task and not run.finished:
            run.task.cancel()

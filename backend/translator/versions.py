"""Translation versions and other changes made outside an agent run (proposal accepts, human edits)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from google.adk.artifacts import BaseArtifactService
from google.adk.events import Event, EventActions
from google.adk.sessions import Session
from google.genai import types

from . import state as st
from .agents.pipeline import UI

AUTHOR = "system"


def activity_event(text: str, delta: dict, artifact_delta: dict | None = None) -> Event:
    """A session event that applies `delta` and shows `text` as an activity line in the chat."""
    return Event(
        author=AUTHOR,
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        custom_metadata={UI: "activity"},
        actions=EventActions(state_delta=delta, artifact_delta=artifact_delta or {}),
    )


async def snapshot_version(
    artifact_service: BaseArtifactService,
    session: Session,
    view: Mapping[str, Any],
    note: str,
    changed: list[str],
) -> tuple[dict, dict, int]:
    """Save `view`'s translation as the next version → (state delta, artifact delta, version number)."""
    adk_version = await artifact_service.save_artifact(
        app_name=session.app_name,
        user_id=session.user_id,
        session_id=session.id,
        filename=st.TRANSLATION_ARTIFACT,
        artifact=types.Part(text=json.dumps(st.snapshot(view), ensure_ascii=False)),
    )
    versions = list(session.state.get("doc:versions") or [])
    entry = st.new_version_entry(session.state, len(versions) + 1, note, changed)[-1]
    entry["artifact_version"] = adk_version
    return {"doc:versions": [*versions, entry]}, {st.TRANSLATION_ARTIFACT: adk_version}, entry["version"]

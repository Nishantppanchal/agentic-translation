"""Downloads of a document version: a Word document, or Markdown (zipped with its figures when it has any)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from google.adk.artifacts import BaseArtifactService
from google.adk.sessions import Session

from ..document import state as st
from ..document.pages import assemble_markdown
from ..languages import lang_code
from .docx import to_docx

FORMATS = [
    {"id": "docx", "label": "Word document", "ext": "docx"},
    {"id": "md", "label": "Markdown (+ figures)", "ext": "md"},
]
MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/markdown; charset=utf-8",
    "zip": "application/zip",
}


class ExportError(Exception):
    pass


async def _artifact(artifact_service: BaseArtifactService, session: Session, name: str, version: int | None = None):
    return await artifact_service.load_artifact(
        app_name=session.app_name, user_id=session.user_id, session_id=session.id, filename=name, version=version
    )


def available() -> list[dict]:
    return [{**f, "available": True} for f in FORMATS]


def latest_version(session: Session) -> int | None:
    versions = session.state.get("doc:versions") or []
    return versions[-1]["version"] if versions else None


async def segments_at(artifact_service: BaseArtifactService, session: Session, version: int | None) -> list[dict]:
    """Segments with the translation as of `version` (None = current state)."""
    segments = [st.normalize(s) for s in st.get_segments(session.state)]
    if version is None:
        return segments
    entry = next((v for v in session.state.get("doc:versions") or [] if v["version"] == version), None)
    if entry is None:
        raise ExportError(f"Version {version} not found")
    part = await _artifact(artifact_service, session, st.TRANSLATION_ARTIFACT, entry["artifact_version"])
    snap = json.loads(part.text) if part and part.text else {}
    return [{**s, "target": snap.get(s["id"], s.get("target"))} for s in segments]


async def figures(artifact_service: BaseArtifactService, session: Session, segments: list[dict]) -> dict[str, bytes]:
    out = {}
    for seg in segments:
        name = seg.get("image")
        if seg.get("kind") == "figure" and name and name not in out:
            part = await _artifact(artifact_service, session, name)
            if part and part.inline_data:
                out[name] = part.inline_data.data
    return out


async def build(artifact_service: BaseArtifactService, session: Session, fmt: str, version: int | None, field: str = "target") -> tuple[bytes, str, str]:
    """→ (content, media type, file name)."""
    s = session.state
    stem = Path(s.get("doc:filename", "document")).stem
    target_lang = s.get("doc:target_lang", "")
    lang = lang_code(target_lang) if field == "target" else lang_code(s.get("doc:detected_lang") or s.get("doc:source_lang"))
    label = f"{stem}.{target_lang if field == 'target' else 'source'}{f'-v{version}' if version else ''}"
    segments = await segments_at(artifact_service, session, version)
    images = await figures(artifact_service, session, segments)
    if fmt == "docx":
        return to_docx(segments, field, lang, images), MEDIA["docx"], f"{label}.docx"
    if fmt == "md":
        markdown = assemble_markdown(segments, field="source" if field == "source" else "target")
        if not images:
            return markdown.encode(), MEDIA["md"], f"{label}.md"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{label}.md", markdown)
            for name, data in images.items():
                zf.writestr(f"figures/{name}", data)
        return buf.getvalue(), MEDIA["zip"], f"{label}.zip"
    raise ExportError(f"Unknown format {fmt!r}")

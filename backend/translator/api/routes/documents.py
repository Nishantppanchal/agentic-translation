"""Documents: upload, list, open, delete, retry; the run's event stream; versions, page images, figures and
downloads."""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pymupdf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from google.adk.sessions import Session
from google.genai import types
from sse_starlette.sse import EventSourceResponse

from ... import exports, office, projects, references
from ...agents.steps.read import source_format
from ...config import TARGET_LANG
from ...document import edits
from ...document import state as st
from ...document.pages import SUPPORTED_EXTS, guess_mime, load_pages
from ...models import routing
from ..downloads import content_disposition
from ..services import (
    APP_NAME,
    USER,
    artifact_service,
    document_view,
    figure_bytes,
    ingest_runner,
    load_session,
    runs,
    session_service,
    set_state,
    source_bytes,
    start_run,
    summary,
)
from ..timeline import history
from . import settings as settings_routes

router = APIRouter()


_page_cache: OrderedDict[tuple[str, int], bytes] = OrderedDict()


@router.get("/api/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    listed = await session_service.list_sessions(app_name=APP_NAME, user_id=USER)
    out = []
    for s in listed.sessions:
        full = await session_service.get_session(app_name=APP_NAME, user_id=USER, session_id=s.id)
        if full:
            out.append(summary(full))
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)


async def _create_document(filename: str, data: bytes, source_lang: str, pages: int, project: dict | None,
                           models: dict | None = None, dictionary_on: bool | None = None) -> Session:
    """One document = one session, with its own ingest run. It keeps the models (and dictionary choice) it was
    uploaded with: the defaults then, plus what the upload changed."""
    source_artifact = f"source{Path(filename).suffix.lower()}"
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER,
        state={
            "doc:filename": filename,
            "doc:format": source_format(filename),
            "doc:mime": guess_mime(filename),
            "doc:source_artifact": source_artifact,
            "doc:source_lang": source_lang,
            "doc:target_lang": TARGET_LANG,
            "doc:status": "uploaded",
            "doc:pages": pages,
            "doc:progress": {"stage": "queued", "current": 0, "total": 0, "message": "Starting…"},
            "doc:seg_ids": [],
            "doc:glossary": {},
            "doc:questions": [],
            "doc:versions": [],
            "doc:ocr_report": [],
            "doc:review_report": [],
            routing.DOC_MODELS: routing.snapshot(models),
            references.DOC_DICTIONARY: references.dictionary_on(None) if dictionary_on is None else dictionary_on,
            **({"doc:project_id": project["id"]} if project else {}),
        },
    )
    if project:
        projects.get_store().attach(session.id, project["id"])
    await artifact_service.save_artifact(
        app_name=APP_NAME,
        user_id=USER,
        session_id=session.id,
        filename=source_artifact,
        artifact=types.Part.from_bytes(data=data, mime_type=guess_mime(filename)),
    )
    start_run(session.id, ingest_runner, f"Translate {filename} into {TARGET_LANG}.", streaming=False)
    return session


@router.post("/api/sessions")
async def create_session(
    file: UploadFile = File(...),
    source_lang: str = Form("auto-detect"),
    project_id: str = Form(""),
    models: str = Form(""),  # JSON {step: {model, effort}}: this document's own choices (the rest: Settings)
    dictionary: str = Form(""),  # "true" / "false": use the dictionary for this document (blank: Settings)
) -> dict[str, Any]:
    """Upload a document to translate into English."""
    filename = Path(file.filename or "document").name
    try:
        chosen = settings_routes.check_models(json.loads(models)) if models.strip() else None
    except ValueError as exc:
        raise HTTPException(422, f"models: {exc}") from exc
    dictionary_on = {"true": True, "false": False}.get(dictionary.strip().lower())
    settings_routes.check_dictionary(dictionary_on)
    project = projects.get_store().project(project_id) if project_id else None
    if project_id and not project:
        raise HTTPException(404, "Project not found")
    if project:  # a project fixes the source language
        source_lang = project["source_lang"] or source_lang
    if source_lang == TARGET_LANG:
        raise HTTPException(400, f"The document is already in {TARGET_LANG}.")
    ext = Path(filename).suffix.lower()
    if reason := office.unsupported(filename):
        raise HTTPException(400, reason)
    fmt = office.detect(filename)
    if ext not in SUPPORTED_EXTS and not fmt:
        raise HTTPException(400, f"Unsupported file type {ext or '?'}. Use a PDF, an image (PNG, JPG, WebP), a Word, "
                                 "PowerPoint or Excel file (.docx, .pptx, .xlsx), TXT or MD.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    pages = 1
    try:
        if fmt:
            await asyncio.to_thread(office.check, data, fmt)
            pages = 0  # set when the text is read
        elif ext == ".pdf":
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                pages = doc.page_count
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Could not read file: {exc}") from exc

    session = await _create_document(filename, data, source_lang, pages, project, chosen, dictionary_on)
    return summary(await load_session(session.id))


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = await load_session(session_id)
    return {"summary": summary(session), "document": document_view(session), "timeline": history(session.events)}


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    runs.cancel(session_id)
    for key in await artifact_service.list_artifact_keys(app_name=APP_NAME, user_id=USER, session_id=session_id):
        await artifact_service.delete_artifact(app_name=APP_NAME, user_id=USER, session_id=session_id, filename=key)
    await session_service.delete_session(app_name=APP_NAME, user_id=USER, session_id=session_id)
    projects.get_store().detach(session_id)
    return {"ok": True}


@router.post("/api/sessions/{session_id}/retry")
async def retry_ingest(session_id: str) -> dict[str, bool]:
    """Re-run the ingest workflow for a document whose run failed or was interrupted (e.g. server restart)."""
    session = await load_session(session_id)
    status = session.state.get("doc:status")
    if runs.is_running(session_id):
        raise HTTPException(409, "The agents are still working on this document.")
    if status in ("ready", "awaiting_answers"):
        raise HTTPException(409, "Nothing to retry.")
    await set_state(
        session_id,
        {
            "doc:status": "uploaded",
            "doc:seg_ids": [],
            "doc:questions": [],
            "doc:versions": [],
            "doc:termbase": {},
            "doc:key_terms": [],
            "doc:tm_stats": None,
            "doc:tm_refs": {},
            "doc:office": None,
            "doc:page_labels": None,
            "doc:unit": None,
            "doc:brief": "",
            "doc:title": None,
            "doc:abstract": None,
            "doc:client_notes": None,
            "doc:proposal": None,
            "doc:ocr_report": [],
            "doc:review_report": [],
            "doc:review_round": 0,
            "doc:review_pending": None,
            "doc:refined": [],
            "doc:dirty": [],
        },
    )
    start_run(session_id, ingest_runner, f"Retry: translate {session.state.get('doc:filename')} into {TARGET_LANG}.", streaming=False)
    return {"ok": True}


@router.get("/api/sessions/{session_id}/stream")
async def stream(session_id: str) -> EventSourceResponse:
    async def gen():
        async for ev in runs.subscribe(session_id):
            yield {"data": json.dumps(ev, ensure_ascii=False, default=str)}

    return EventSourceResponse(gen(), ping=15)


@router.get("/api/sessions/{session_id}/versions/{version}")
async def get_version(session_id: str, version: int) -> dict[str, Any]:
    session = await load_session(session_id)
    entry = next((v for v in session.state.get("doc:versions") or [] if v["version"] == version), None)
    if not entry:
        raise HTTPException(404, "Version not found")
    part = await artifact_service.load_artifact(
        app_name=APP_NAME,
        user_id=USER,
        session_id=session_id,
        filename=st.TRANSLATION_ARTIFACT,
        version=entry["artifact_version"],
    )
    if not part or part.text is None:
        raise HTTPException(404, "Version artifact missing")
    return {"version": version, "segments": json.loads(part.text)}


@router.get("/api/sessions/{session_id}/pages/{page}")
async def page_image(session_id: str, page: int) -> Response:
    key = (session_id, page)
    if key not in _page_cache:
        session = await load_session(session_id)
        data, filename = await source_bytes(session)
        if Path(filename).suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(404, "No page image for text documents")
        pages = await asyncio.to_thread(load_pages, data, filename, 110)
        if not 1 <= page <= len(pages):
            raise HTTPException(404, "Page out of range")
        for p in pages:
            _page_cache[(session_id, p.number)] = p.image or b""
        while len(_page_cache) > 200:
            _page_cache.popitem(last=False)
    data = _page_cache[key]
    media = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return Response(data, media_type=media, headers={"Cache-Control": "max-age=3600"})


@router.get("/api/sessions/{session_id}/figures/{name}")
async def figure(session_id: str, name: str) -> Response:
    return Response(await figure_bytes(session_id, name), media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@router.get("/api/sessions/{session_id}/export/formats")
async def export_formats(session_id: str) -> list[dict[str, Any]]:
    return exports.available(await load_session(session_id))


@router.get("/api/sessions/{session_id}/export", response_model=None)
async def export(session_id: str, format: str = "md", version: int | None = None, field: str = "target") -> Response:
    """Download a version: docx | md (a zip with its figures when it has any)."""
    session = await load_session(session_id)
    if version is None and not runs.is_running(session_id):
        await edits.flush_human_edits(session_service, artifact_service, session)
    if version is None and format == "pdf":
        version = exports.latest_version(session)
    try:
        content, media, name = await exports.build(artifact_service, session, format, version, field)
    except exports.ExportError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(content, media_type=media, headers={"Content-Disposition": content_disposition(name)})

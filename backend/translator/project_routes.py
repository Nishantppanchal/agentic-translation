"""Project API: projects, style guide, termbase, translation memory, and TMX/TBX/CSV exchange.
The target language is always English (`config.TARGET_LANG`)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import projects
from .config import TARGET_LANG
from .downloads import content_disposition
from .filters import exchange
from .languages import lang_code

router = APIRouter(prefix="/api/projects")
MAX_IMPORT = 50 * 1024 * 1024


def _project(pid: str) -> dict:
    project = projects.get_store().project(pid)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _codes(project: dict) -> tuple[str, str]:
    src = project.get("source_lang") or ""
    if not src or src == "auto-detect":
        raise HTTPException(409, "Set the project's source language first.")
    return lang_code(src), lang_code(TARGET_LANG)


class ProjectIn(BaseModel):
    name: str = ""
    source_lang: str | None = None
    instructions: str | None = None
    auto_confirm_context: bool | None = None  # 101% TM matches start as confirmed
    lqa_threshold: float | None = Field(None, ge=0, le=100)


@router.get("")
async def list_projects() -> list[dict[str, Any]]:
    return projects.get_store().projects()


@router.post("")
async def create_project(body: ProjectIn) -> dict[str, Any]:
    settings = body.model_dump(include={"auto_confirm_context", "lqa_threshold"}, exclude_none=True)
    return projects.get_store().create_project(body.name, body.source_lang or "", body.instructions or "", **settings)


@router.get("/{pid}")
async def get_project(pid: str) -> dict[str, Any]:
    return _project(pid)


@router.patch("/{pid}")
async def update_project(pid: str, body: ProjectIn) -> dict[str, Any]:
    _project(pid)
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields and not (fields["name"] or "").strip():
        fields.pop("name")  # a project always keeps a name
    return projects.get_store().update_project(pid, **fields)


@router.delete("/{pid}")
async def delete_project(pid: str) -> dict[str, bool]:
    """Deletes the project's termbase and TM. Its documents stay (they just leave the project)."""
    _project(pid)
    projects.get_store().delete_project(pid)
    return {"ok": True}


# ---- termbase ---------------------------------------------------------------- #


class TermIn(BaseModel):
    source: str | None = None
    target: str | None = None
    note: str | None = None
    forbidden: list[str] | None = None
    case_sensitive: bool | None = None
    status: Literal["approved", "proposed", "note"] | None = None


@router.get("/{pid}/terms")
async def list_terms(pid: str) -> list[dict[str, Any]]:
    _project(pid)
    return projects.get_store().terms(pid)


@router.post("/{pid}/terms")
async def add_term(pid: str, body: TermIn) -> dict[str, Any]:
    _project(pid)
    if not (body.source or "").strip():
        raise HTTPException(400, "A term needs a source.")
    return projects.get_store().upsert_term(
        pid, body.source, body.target or "", body.note or "", body.forbidden, body.case_sensitive, body.status or "approved"
    )


@router.patch("/{pid}/terms/{term_id}")
async def edit_term(pid: str, term_id: int, body: TermIn) -> dict[str, Any]:
    _project(pid)
    if body.source is not None and not body.source.strip():
        raise HTTPException(400, "A term needs a source.")
    try:
        term = projects.get_store().update_term(pid, term_id, **body.model_dump(exclude_unset=True))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, f'"{body.source}" is already in the termbase.') from exc
    if not term:
        raise HTTPException(404, "Term not found")
    return term


@router.delete("/{pid}/terms/{term_id}")
async def delete_term(pid: str, term_id: int) -> dict[str, bool]:
    _project(pid)
    projects.get_store().delete_term(pid, term_id)
    return {"ok": True}


# ---- translation memory ------------------------------------------------------ #


@router.get("/{pid}/tm")
async def concordance(pid: str, q: str = "", limit: int = 50) -> dict[str, Any]:
    """Concordance search (source or target contains `q`); without `q`, the most recent units."""
    project = _project(pid)
    return {"total": project["tm_units"], "units": projects.get_store().concordance(pid, q, min(limit, 200))}


@router.delete("/{pid}/tm/{unit_id}")
async def delete_unit(pid: str, unit_id: int) -> dict[str, bool]:
    _project(pid)
    projects.get_store().delete_unit(pid, unit_id)
    return {"ok": True}


# ---- exchange ---------------------------------------------------------------- #


def _import(pid: str, project: dict, name: str, data: bytes) -> dict[str, Any]:
    ext = Path(name).suffix.lower()
    src, tgt = _codes(project)
    store = projects.get_store()
    try:
        if ext == ".tmx":
            units, warnings = exchange.tmx_import(data, src, tgt)
            added, updated = store.add_units(pid, units)
            return {"kind": "tm", "added": added, "updated": updated, "warnings": warnings}
        if ext in (".tbx", ".csv", ".tsv", ".txt"):
            if ext == ".tbx":
                entries, warnings = exchange.tbx_import(data, src, tgt)
            else:
                entries, warnings = exchange.csv_import(data, src, tgt, project["source_lang"], TARGET_LANG)
            existing = {t["source"] for t in store.terms(pid)}
            for e in entries:
                store.upsert_term(pid, e["source"], e["target"], e.get("note", ""), e.get("forbidden"))
            added = len({e["source"].strip() for e in entries} - existing)
            return {"kind": "terms", "added": added, "updated": len(entries) - added, "warnings": warnings}
    except (ValueError, SyntaxError) as exc:  # lxml's XMLSyntaxError is a SyntaxError
        raise HTTPException(400, f"Could not read {name}: {exc}") from exc
    raise HTTPException(400, f"Unsupported file type {ext or '?'}. Use .tmx (memory), .tbx or .csv (termbase).")


@router.post("/{pid}/import")
async def import_file(pid: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """TMX → translation memory; TBX / CSV → termbase. Returns a report."""
    project = _project(pid)
    data = await file.read(MAX_IMPORT + 1)
    if len(data) > MAX_IMPORT:
        raise HTTPException(413, "File too large (50 MB max).")
    return await asyncio.to_thread(_import, pid, project, file.filename or "import", data)


@router.get("/{pid}/export", response_model=None)
async def export_file(pid: str, format: Literal["tmx", "tbx", "csv"] = "tmx") -> Response:
    project = _project(pid)
    src, tgt = _codes(project)
    store = projects.get_store()
    stem = "".join(c if c.isalnum() or c in "-_ " else "_" for c in project["name"]).strip() or "project"
    if format == "tmx":
        content, media = exchange.tmx_export(store.units(pid), src, tgt), "application/x-tmx+xml"
    elif format == "tbx":
        content, media = exchange.tbx_export(store.terms(pid), src, tgt), "application/x-tbx+xml"
    else:
        content, media = exchange.csv_export(store.terms(pid)), "text/csv; charset=utf-8"
    name = f"{stem}.{src}-{tgt}.{format}"
    return Response(content, media_type=media, headers={"Content-Disposition": content_disposition(name)})

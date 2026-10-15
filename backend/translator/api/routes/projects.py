"""Project API: projects, style guide, termbase and translation memory.
The target language is always English (`config.TARGET_LANG`)."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import projects

router = APIRouter(prefix="/api/projects")


def _project(pid: str) -> dict:
    project = projects.get_store().project(pid)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


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


# Plain `def`: FastAPI runs these in its thread pool, so the SQLite work doesn't block the event loop.


@router.get("/{pid}/tm")
def concordance(pid: str, q: str = "", limit: int = 50) -> dict[str, Any]:
    """Concordance search (source or target contains `q`); without `q`, the most recent units."""
    project = _project(pid)
    return {"total": project["tm_units"], "units": projects.get_store().concordance(pid, q, min(limit, 200))}


class UnitIn(BaseModel):
    source: str
    target: str
    prev_source: str = ""  # the sentence before it, for 101% (context) matches
    ref: str = "import"  # where it comes from


@router.post("/{pid}/tm")
def add_units(pid: str, units: list[UnitIn]) -> dict[str, int]:
    """Add translation-memory units. A unit with the same source after the same previous sentence is updated;
    imported units never replace wording a person confirmed."""
    _project(pid)
    rows = [{**u.model_dump(), "approval": "import"} for u in units if u.source.strip() and u.target.strip()]
    statuses = projects.get_store().add_units(pid, rows)
    return {k: statuses.count(k) for k in ("added", "updated", "unchanged", "kept")}


@router.delete("/{pid}/tm/{unit_id}")
def delete_unit(pid: str, unit_id: int) -> dict[str, bool]:
    _project(pid)
    projects.get_store().delete_unit(pid, unit_id)
    return {"ok": True}

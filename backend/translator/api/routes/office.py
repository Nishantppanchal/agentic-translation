"""Word, PowerPoint and Excel uploads in the Layout view: the file itself (original, or translated as of a version),
what writing it back did, and Excel sheets as grids."""

from __future__ import annotations

import asyncio
import hashlib
import json
import warnings
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ... import exports, office
from ...office.view import sheet_grid
from ..services import artifact_service, load_session

router = APIRouter()
_cache: OrderedDict[str, tuple[bytes, dict]] = OrderedDict()  # rendering a big file takes a moment: the last 20


async def _office(session_id: str, version: int | None):
    session = await load_session(session_id)
    fmt = office.detect(session.state.get("doc:filename", ""))
    if not fmt:
        raise HTTPException(404, "Not a Word, PowerPoint or Excel document.")
    try:
        segments = await exports.segments_at(artifact_service, session, version)
    except exports.ExportError as exc:
        raise HTTPException(404, str(exc)) from exc
    return session, fmt, segments


async def _file(session_id: str, side: str, version: int | None, marks: bool) -> tuple[bytes, dict, str]:
    session, fmt, segments = await _office(session_id, version)
    texts = json.dumps([[s["id"], s.get("target")] for s in segments] if side == "target" else [], ensure_ascii=False)
    key = hashlib.sha1(f"{session_id}|{side}|{marks}|{texts}".encode()).hexdigest()
    if key not in _cache:
        _cache[key] = await exports.office_file(artifact_service, session, segments, side, marks)
        while len(_cache) > 20:
            _cache.popitem(last=False)
    _cache.move_to_end(key)
    content, report = _cache[key]
    return content, report, session.state.get("doc:filename", "")


@router.get("/api/sessions/{session_id}/office/file")
async def office_file(session_id: str, side: str = "target", version: int | None = None, marks: bool = False) -> Response:
    """The file for the Layout view: `side=source` the original, `target` the translation (as of `version`); `marks`:
    Word paragraphs carry hidden `_seg_<id>` bookmarks, to find a segment in the rendered page."""
    if side not in ("source", "target"):
        raise HTTPException(400, "side is source or target")
    content, _report, filename = await _file(session_id, side, version, marks)
    return Response(content, media_type=office.media_type(filename), headers={"Cache-Control": "no-cache"})


@router.get("/api/sessions/{session_id}/office/report")
async def office_report(session_id: str, version: int | None = None) -> dict[str, Any]:
    """What reading the file left out, and what writing the translation back did (skipped, simplified, moved)."""
    session, _fmt, _segments = await _office(session_id, version)
    _content, report, _ = await _file(session_id, "target", version, False)
    return {"extract": session.state.get("doc:office") or {}, "write": report}


@router.get("/api/sessions/{session_id}/office/sheets")
async def office_sheets(session_id: str) -> dict[str, Any]:
    """An Excel upload's sheets as grids; text cells name their segment (`seg`)."""
    session, fmt, segments = await _office(session_id, None)
    if fmt != "xlsx":
        raise HTTPException(404, "Not an Excel workbook.")
    part = await artifact_service.load_artifact(app_name=session.app_name, user_id=session.user_id, session_id=session.id,
                                                filename=session.state["doc:source_artifact"])

    def grid() -> dict:
        with warnings.catch_warnings():  # openpyxl warns about extensions it doesn't read (the view doesn't need them)
            warnings.simplefilter("ignore")
            return sheet_grid(part.inline_data.data, segments)

    return await asyncio.to_thread(grid)

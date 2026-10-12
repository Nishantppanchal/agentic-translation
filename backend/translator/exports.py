"""Export formats for a document version: layout-preserving PDF, DOCX, bilingual review DOCX, HTML, Markdown."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

import pymupdf
from google.adk.artifacts import BaseArtifactService
from google.adk.sessions import Session
from google.genai import types

from . import state as st
from .documents import assemble_markdown
from .filters import office, pdf_layout, reflow, xliff
from .languages import lang_code

FORMATS = [
    {"id": "original", "label": "Translated file — original format", "group": "Original layout", "ext": ""},
    {"id": "pdf", "label": "Translated PDF — original layout", "group": "Original layout", "ext": "pdf"},
    {"id": "docx", "label": "Word document", "group": "Reflowed", "ext": "docx"},
    {"id": "html", "label": "Web page (HTML)", "group": "Reflowed", "ext": "html"},
    {"id": "md", "label": "Markdown (+ figures)", "group": "Reflowed", "ext": "md"},
    {"id": "bilingual", "label": "Bilingual review table (DOCX)", "group": "Review", "ext": "docx"},
    {"id": "xliff", "label": "XLIFF 2.0 — for other CAT tools", "group": "Exchange", "ext": "xlf"},
    {"id": "xliff12", "label": "XLIFF 1.2 — memoQ, older Trados", "group": "Exchange", "ext": "xlf"},
]
DIRECT = {"docx": "Word", "pptx": "PowerPoint", "xlsx": "Excel", "xliff": "XLIFF"}
MEDIA = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "zip": "application/zip",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xliff": "application/xliff+xml",
}


class ExportError(Exception):
    pass


async def _artifact(artifact_service: BaseArtifactService, session: Session, name: str, version: int | None = None):
    return await artifact_service.load_artifact(
        app_name=session.app_name, user_id=session.user_id, session_id=session.id, filename=name, version=version
    )


async def _save(artifact_service: BaseArtifactService, session: Session, name: str, part: types.Part) -> None:
    await artifact_service.save_artifact(
        app_name=session.app_name, user_id=session.user_id, session_id=session.id, filename=name, artifact=part
    )


def layout_capable(session: Session, source: bytes | None) -> bool:
    """A layout-preserving PDF needs a PDF with a text layer (scans and images have no positions to typeset into)."""
    known = session.state.get("doc:layout_capable")
    if known is not None:
        return bool(known)
    if source is None or Path(session.state.get("doc:filename", "")).suffix.lower() != ".pdf":
        return False
    with pymupdf.open(stream=source, filetype="pdf") as doc:
        return any(len(p.get_text().strip()) >= 40 for p in doc)


async def source_bytes(artifact_service: BaseArtifactService, session: Session) -> bytes | None:
    part = await _artifact(artifact_service, session, session.state.get("doc:source_artifact", ""))
    return part.inline_data.data if part and part.inline_data else None


async def available(artifact_service: BaseArtifactService, session: Session) -> list[dict]:
    fmt = session.state.get("doc:format")
    if fmt in DIRECT:
        ext = "xlf" if fmt == "xliff" else fmt
        original = {"label": f"Translated {DIRECT[fmt]} file — original format", "ext": ext, "available": True}
        if tracked := session.state.get("doc:tracked_changes"):
            original["note"] = f"{tracked} tracked change{'s' if tracked != 1 else ''} accepted — the file has no revision marks"
        in_formulas = [s for s in st.get_segments(session.state) if s.get("formula_refs") and s.get("target") and s["target"] != s["source"]]
        if in_formulas:
            n = len(in_formulas)
            original["note"] = (f"Formulas that compare against {n} translated cell text{'s' if n != 1 else ''} "
                                "are updated to the translation, so their results stay right")
        return [{**f, **original} if f["id"] == "original" else {**f, "available": f["id"] != "pdf"} for f in FORMATS]
    pdf_ok = layout_capable(session, await source_bytes(artifact_service, session))
    return [{**f, "available": f["id"] not in ("pdf", "original") or (f["id"] == "pdf" and pdf_ok)} for f in FORMATS]


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


async def layout_pdf(artifact_service: BaseArtifactService, session: Session, version: int) -> tuple[bytes, dict]:
    """Layout-preserving PDF for a version, rendered once and cached as artifacts."""
    stem = f"export-layout-r{pdf_layout.RENDER_VERSION}-v{version}"
    cached_pdf = await _artifact(artifact_service, session, f"{stem}.pdf")
    cached_report = await _artifact(artifact_service, session, f"{stem}.json")
    if cached_pdf and cached_pdf.inline_data and cached_report and cached_report.text:
        return cached_pdf.inline_data.data, json.loads(cached_report.text)
    source = await source_bytes(artifact_service, session)
    if not layout_capable(session, source):
        raise ExportError("A layout-preserving PDF needs a PDF with a text layer.")
    segments = await segments_at(artifact_service, session, version)
    targets = {s["id"]: s.get("target") or "" for s in segments}
    pdf, report = await asyncio.to_thread(pdf_layout.render, source, segments, targets)
    report["version"] = version
    await _save(artifact_service, session, f"{stem}.pdf", types.Part.from_bytes(data=pdf, mime_type="application/pdf"))
    await _save(artifact_service, session, f"{stem}.json", types.Part(text=json.dumps(report)))
    return pdf, report


def _notes(state) -> dict[str, list[str]]:
    """Per-segment review notes for the bilingual table: AI verdict, flags, latest review issues."""
    notes: dict[str, list[str]] = {}
    for report in state.get("doc:review_report") or []:
        for issue in report.get("issues", []):
            cat = f"{issue['category']}, " if issue.get("category") else ""
            notes.setdefault(issue["segment_id"], []).append(f"AI review ({cat}{issue['severity']}): {issue['note']}")
    for seg in st.get_segments(state):
        seg = st.normalize(seg)
        for flag in seg.get("flags") or []:
            notes.setdefault(seg["id"], []).append(f"⚠ {flag}")
        for c in seg.get("comments") or []:
            done = ", resolved" if c.get("resolved") else ""
            notes.setdefault(seg["id"], []).append(f"Comment ({c.get('role', 'translator')}{done}): {c['text']}")
    return notes


async def build(artifact_service: BaseArtifactService, session: Session, fmt: str, version: int | None, field: str = "target") -> tuple[bytes, str, str]:
    """→ (content, media type, file name)."""
    s = session.state
    stem = Path(s.get("doc:filename", "document")).stem
    target_lang = s.get("doc:target_lang", "")
    lang = lang_code(target_lang) if field == "target" else lang_code(s.get("doc:detected_lang") or s.get("doc:source_lang"))
    label = f"{stem}.{target_lang if field == 'target' else 'source'}{f'-v{version}' if version else ''}"

    if fmt == "pdf":
        if version is None:
            raise ExportError("Save a version first.")
        pdf, _ = await layout_pdf(artifact_service, session, version)
        return pdf, MEDIA["pdf"], f"{label}.pdf"

    segments = await segments_at(artifact_service, session, version)
    if fmt == "original":
        doc_fmt = s.get("doc:format")
        if doc_fmt not in DIRECT:
            raise ExportError("Only Word, PowerPoint, Excel and XLIFF documents can be exported in their original format.")
        data = await source_bytes(artifact_service, session)
        if data is None:
            raise ExportError("The original file is missing.")
        chosen = segments if field == "target" else [{**x, "target": x["source"]} for x in segments]
        if doc_fmt == "xliff":
            content, _ = await asyncio.to_thread(xliff.write_back, data, chosen)
            return content, MEDIA["xliff"], f"{label}.xlf"
        content, _ = await asyncio.to_thread(office.write, data, doc_fmt, chosen, lang)
        return content, MEDIA[doc_fmt], f"{label}.{doc_fmt}"
    if fmt in ("xliff", "xliff12"):
        src_code = lang_code(s.get("doc:detected_lang") or s.get("doc:source_lang"))
        v12 = fmt == "xliff12"
        content = xliff.export(segments, src=src_code, tgt=lang_code(target_lang), original=s.get("doc:filename", "document"),
                               notes=_notes(s), version="1.2" if v12 else "2.0")
        suffix = f"{'-xliff12' if v12 else ''}{f'-v{version}' if version else ''}"
        return content, MEDIA["xliff"], f"{stem}.{src_code}-{lang_code(target_lang)}{suffix}.xlf"
    images = await figures(artifact_service, session, segments)
    if fmt == "docx":
        return reflow.to_docx(segments, field, lang, images), MEDIA["docx"], f"{label}.docx"
    if fmt == "html":
        return reflow.to_html(segments, field, lang, label, images).encode(), MEDIA["html"], f"{label}.html"
    if fmt == "bilingual":
        meta = {
            "filename": s.get("doc:filename"),
            "source_lang": s.get("doc:detected_lang") or s.get("doc:source_lang"),
            "target_lang": target_lang,
            "target_code": lang_code(target_lang),
            "version": version,
        }
        return reflow.to_bilingual_docx(segments, meta, _notes(s)), MEDIA["docx"], f"{stem}.bilingual{f'-v{version}' if version else ''}.docx"
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

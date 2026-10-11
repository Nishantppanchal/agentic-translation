"""XLIFF 2.0 and 1.2: export for other CAT tools, re-import as a proposal, and XLIFF files as an input format.

XLIFF 2.0 — codes: our `<g id>` spans are `<pc id>`, `<x id/>` placeholders are `<ph id/>`. Reading other
tools' files, `<sc>`/`<ec>` become placeholders, `<cp>` becomes its character, and annotations (`<mrk>`)
are unwrapped. Status ↔ state: new = initial, draft = translated, confirmed (translator) = reviewed,
reviewed (second linguist) = final; the exact status is also kept in `subState="at:…"`.

XLIFF 1.2 (memoQ, older Trados) — our codes are 1.2's own `<g>`/`<x>`; `<bx>`, `<ex>`, `<ph>`, `<bpt>`,
`<ept>`, `<it>` are placeholders (copied back whole, native code included). Segmentation in
`<seg-source>` (`<mrk mtype="seg">`) gives one segment per marker. Status ↔ state: draft =
needs-review-translation, confirmed = translated, reviewed = signed-off (+ `approved="yes"` once a
person confirmed); the exact status is also kept in `at:status`.

Locked segments get `at:locked="yes"`; non-translatable ones `translate="no"`.
"""

from __future__ import annotations

import copy
import time
import unicodedata

from lxml import etree

from . import inline

NS = "urn:oasis:names:tc:xliff:document:2.0"
NS12 = "urn:oasis:names:tc:xliff:document:1.2"
AT = "urn:agentic-translator:xliff"
STATE12_OF = {"new": "new", "draft": "needs-review-translation", "confirmed": "translated", "reviewed": "signed-off"}
# XLIFF 1.2 states in 2.0 terms (the import rules speak 2.0).
FROM12 = {"new": "initial", "needs-translation": "initial", "needs-adaptation": "initial", "needs-l10n": "initial",
          "needs-review-translation": "translated", "needs-review-adaptation": "translated", "needs-review-l10n": "translated",
          "translated": "reviewed", "signed-off": "final", "final": "final"}
_SPANS = {"pc", "g"}
_PLACEHOLDERS = {"ph", "sc", "x", "bx", "ex", "bpt", "ept", "it"}
STATE_OF = {"new": "initial", "draft": "translated", "confirmed": "reviewed", "reviewed": "final"}
STATUS_OF = {"initial": "draft", "translated": "draft", "reviewed": "confirmed", "final": "reviewed"}
LOC_SEP = "\x1f"  # file id · unit id · segment index


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _q12(tag: str) -> str:
    return f"{{{NS12}}}{tag}"


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, remove_comments=True, huge_tree=True)


def _primary(code: str | None) -> str:
    return (code or "").split("-")[0].split("_")[0].lower()


# --------------------------------------------------------------------------- #
# Inline content
# --------------------------------------------------------------------------- #


def _append_text(parent, text: str) -> None:
    if not text:
        return
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def to_xliff(parent, text: str, originals: dict[str, object] | None = None, version: str = "2.0") -> None:
    """Our text with codes → XLIFF inline content under `parent`. `originals` (id → source element)
    lets a write-back reuse the original file's code elements, attributes and native code."""
    span, placeholder = (_q("pc"), _q("ph")) if version.startswith("2") else (_q12("g"), _q12("x"))

    def build(nodes, into) -> None:
        for n in nodes:
            if n.kind == "text":
                _append_text(into, n.text)
            elif n.kind == "x":
                orig = (originals or {}).get(n.id)
                if orig is not None and etree.QName(orig).localname in _PLACEHOLDERS:
                    el = copy.deepcopy(orig)  # with its native code (1.2 <ph>/<bpt>/<ept> hold some)
                    el.tail = None
                    into.append(el)
                else:
                    etree.SubElement(into, placeholder, id=n.id)
            else:
                orig = (originals or {}).get(n.id)
                if orig is not None and etree.QName(orig).localname in _SPANS:
                    el = etree.SubElement(into, orig.tag, attrib=dict(orig.attrib))
                else:
                    el = etree.SubElement(into, span, id=n.id)
                build(n.children, el)

    build(inline.parse(text), parent)


def from_xliff(el) -> tuple[str, dict[str, object]]:
    """XLIFF inline content → (our text with codes, id → original code element)."""
    out: list[str] = []
    originals: dict[str, object] = {}

    def walk(node) -> None:
        if node.text:
            out.append(node.text)
        for child in node:
            name = etree.QName(child).localname if isinstance(child.tag, str) else ""
            if name in _SPANS:
                cid = child.get("id", "")
                originals[cid] = child
                out.append(f'<g id="{cid}">')
                walk(child)
                out.append("</g>")
            elif name in ("ph", "sc", "x", "bx", "ex", "bpt", "ept", "it"):
                cid = child.get("id", "") or child.get("rid", "")
                if name == "ept":
                    cid += "e"  # an XLIFF 1.2 <ept> shares its <bpt>'s id: keep them apart
                originals[cid] = child
                out.append(f'<x id="{cid}"/>')
            elif name == "ec":
                cid = child.get("id") or f"{child.get('startRef', '')}e"
                originals[cid] = child
                out.append(f'<x id="{cid}"/>')
            elif name == "cp":
                try:
                    out.append(chr(int(child.get("hex", "0"), 16)))
                except ValueError:
                    pass
            elif name:
                walk(child)  # annotations (mrk, sm…): keep the text
            if child.tail:
                out.append(child.tail)

    walk(el)
    return "".join(out), originals


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def parse(data: bytes) -> dict:
    """→ {src, tgt, units: [{loc, file, unit, index, source, target, state, sub_state, translate, codes}]}"""
    try:
        root = etree.fromstring(data, _parser())
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Not valid XML: {exc}") from exc
    if etree.QName(root).localname != "xliff":
        raise ValueError("Not an XLIFF file.")
    version = root.get("version", "")
    if version.startswith("1"):
        return _parse12(root)
    if not version.startswith("2"):
        raise ValueError(f"XLIFF {version or '?'} isn't supported — export XLIFF 2.0 or 1.2 from your CAT tool.")
    units = []
    for f in root.iter(_q("file")):
        for unit in f.iter(_q("unit")):
            translate = unit.get("translate", f.get("translate", "yes")) != "no"
            for k, seg in enumerate(unit.findall(_q("segment"))):
                src_el, tgt_el = seg.find(_q("source")), seg.find(_q("target"))
                if src_el is None:
                    continue
                source, originals = from_xliff(src_el)
                target = from_xliff(tgt_el)[0] if tgt_el is not None else None
                units.append({
                    "loc": LOC_SEP.join([f.get("id", ""), unit.get("id", ""), str(k)]),
                    "file": f.get("original") or f.get("id", ""),
                    "unit": unit.get("id", ""),
                    "index": k,
                    "source": source,
                    "target": target,
                    "state": seg.get("state", "initial" if target is None else "translated"),
                    "sub_state": seg.get("subState", ""),
                    "translate": translate,
                    "codes": {cid: _code_label(el) for cid, el in originals.items()},
                    "locked": unit.get(f"{{{AT}}}locked") == "yes",
                })
    return {"src": root.get("srcLang", ""), "tgt": root.get("trgLang", ""), "units": units, "version": "2.0"}


def _file_id12(f, i: int) -> str:
    return f.get("original") or f"file{i + 1}"


def _seg_pieces(tu) -> list[tuple[int, object, object]]:
    """(index, source element, target element) per segment: `<seg-source>` markers, or the whole unit."""
    src_el, tgt_el, seg_src = tu.find(_q12("source")), tu.find(_q12("target")), tu.find(_q12("seg-source"))
    marks = [m for m in seg_src.iter(_q12("mrk")) if m.get("mtype") == "seg"] if seg_src is not None else []
    if not marks:
        return [(0, src_el, tgt_el)] if src_el is not None else []
    targets = {m.get("mid"): m for m in tgt_el.iter(_q12("mrk")) if m.get("mtype") == "seg"} if tgt_el is not None else {}
    return [(k, m, targets.get(m.get("mid"))) for k, m in enumerate(marks)]


def _parse12(root) -> dict:
    units = []
    files = list(root.iter(_q12("file")))
    for i, f in enumerate(files):
        fid = _file_id12(f, i)
        for tu in f.iter(_q12("trans-unit")):
            tgt_el = tu.find(_q12("target"))
            state12 = tgt_el.get("state", "") if tgt_el is not None else ""
            ours = tu.get(f"{{{AT}}}status", "")
            for k, s_el, t_el in _seg_pieces(tu):
                source, originals = from_xliff(s_el)
                target = from_xliff(t_el)[0] if t_el is not None else None
                state = FROM12.get(state12, "translated" if target else "initial")
                if tu.get("approved") == "yes" and state in ("initial", "translated") and target:
                    state = "reviewed"
                units.append({
                    "loc": LOC_SEP.join([fid, tu.get("id", ""), str(k)]),
                    "file": fid,
                    "unit": tu.get("id", ""),
                    "index": k,
                    "source": source,
                    "target": target,
                    "state": state,
                    "sub_state": f"at:{ours}" if ours else "",
                    "translate": tu.get("translate", "yes") != "no",
                    "codes": {cid: _code_label(el) for cid, el in originals.items()},
                    "locked": tu.get(f"{{{AT}}}locked") == "yes",
                })
    first = files[0] if files else None
    return {"src": first.get("source-language", "") if first is not None else "",
            "tgt": first.get("target-language", "") if first is not None else "", "units": units, "version": "1.2"}


def _code_label(el) -> str:
    name = etree.QName(el).localname
    kind = el.get("type") or el.get("subType") or el.get("ctype") or ""
    disp = el.get("disp") or el.get("equiv") or el.get("equiv-text") or ""
    if name in _SPANS:
        return "link" if "link" in kind else (disp or {"bold": "bold", "italic": "italic", "underlined": "underline"}.get(kind, "format"))
    return disp or {"ui": "UI text", "fmt": "format", "link": "link", "image": "image", "quote": "quote"}.get(kind, "placeholder")


def _status(state: str, sub_state: str) -> str:
    """Our exact status from subState, unless another tool changed the state since (then the state wins)."""
    ours = sub_state[3:] if sub_state.startswith("at:") else ""
    if STATE_OF.get(ours) == state:
        return ours
    return STATUS_OF.get(state, "draft")


def extract(data: bytes) -> tuple[list[dict], dict]:
    """An XLIFF file as the document: one segment per XLIFF segment, keeping existing translations."""
    doc = parse(data)
    files: dict[str, int] = {}
    counters: dict[int, int] = {}
    segments = []
    for u in doc["units"]:
        page = files.setdefault(u["file"], len(files) + 1)
        counters[page] = counters.get(page, 0) + 1
        plain = inline.strip(u["source"])
        if not plain.strip():
            continue
        translatable = u["translate"] and any(c.isalpha() for c in plain)
        has_target = bool(u["target"] and inline.strip(u["target"]).strip())
        seg = {
            "id": f"p{page}.{counters[page]}",
            "page": page,
            "kind": "paragraph",
            "source": u["source"],
            "target": (u["target"] if has_target else None) if translatable else u["source"],
            "translatable": translatable,
            "where": f"{u['file']} · {u['unit']}" + (f" #{u['index'] + 1}" if u["index"] else ""),
            "loc": u["loc"],
        }
        if has_target and translatable:
            seg.update(status=_status(u["state"], u["sub_state"]), origin="xliff")
        if u["locked"]:
            seg["locked"] = True
        if u["codes"]:
            seg["codes"] = u["codes"]
        segments.append(seg)
    info = {"pages": len(files), "with_codes": sum(1 for s in segments if s.get("codes")), "unit": "file",
            "src": doc["src"], "tgt": doc["tgt"], "pretranslated": sum(1 for s in segments if s.get("origin") == "xliff")}
    return segments, info


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def export(segments: list[dict], *, src: str, tgt: str, original: str, notes: dict[str, list[str]] | None = None,
           version: str = "2.0") -> bytes:
    """Our document as XLIFF 2.0 or 1.2 (one unit per segment, unit id = segment id)."""
    if version.startswith("1"):
        return _export12(segments, src=src, tgt=tgt, original=original, notes=notes)
    root = etree.Element(_q("xliff"), nsmap={None: NS, "at": AT}, version="2.0", srcLang=src, trgLang=tgt)
    f = etree.SubElement(root, _q("file"), id="f1", original=original)
    for s in segments:
        unit = etree.SubElement(f, _q("unit"), id=s["id"])
        if not s.get("translatable", True):
            unit.set("translate", "no")
        if s.get("locked"):
            unit.set(f"{{{AT}}}locked", "yes")
        if s.get("kind"):
            unit.set(f"{{{AT}}}kind", s["kind"])
        lines = _notes_for(s, notes)
        if lines:
            notes_el = etree.SubElement(unit, _q("notes"))
            for line in lines:
                etree.SubElement(notes_el, _q("note"), category="location" if line.startswith("Location:") else "qa").text = line
        status = s.get("status") or ("draft" if s.get("target") else "new")
        has_target = bool(s.get("target"))
        seg = etree.SubElement(unit, _q("segment"), state=STATE_OF.get(status, "translated") if has_target else "initial")
        if has_target:
            seg.set("subState", f"at:{status}")
        to_xliff(etree.SubElement(seg, _q("source")), s["source"])
        if has_target:
            to_xliff(etree.SubElement(seg, _q("target")), s["target"])
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _notes_for(s: dict, notes: dict[str, list[str]] | None) -> list[str]:
    return [*([f"Location: {s['where']}"] if s.get("where") else []), *((notes or {}).get(s["id"]) or [])]


def _export12(segments: list[dict], *, src: str, tgt: str, original: str, notes: dict[str, list[str]] | None) -> bytes:
    root = etree.Element(_q12("xliff"), nsmap={None: NS12, "at": AT}, version="1.2")
    f = etree.SubElement(root, _q12("file"), original=original, datatype="plaintext",
                         attrib={"source-language": src, "target-language": tgt})
    body = etree.SubElement(f, _q12("body"))
    for s in segments:
        status = s.get("status") or ("draft" if s.get("target") else "new")
        tu = etree.SubElement(body, _q12("trans-unit"), id=s["id"])
        tu.set(f"{{{AT}}}status", status)
        if not s.get("translatable", True):
            tu.set("translate", "no")
        if s.get("locked"):
            tu.set(f"{{{AT}}}locked", "yes")
        if s.get("target") and status in ("confirmed", "reviewed"):
            tu.set("approved", "yes")
        to_xliff(etree.SubElement(tu, _q12("source")), s["source"], version="1.2")
        if s.get("target"):
            to_xliff(etree.SubElement(tu, _q12("target"), state=STATE12_OF.get(status, "translated")), s["target"], version="1.2")
        for line in _notes_for(s, notes):
            etree.SubElement(tu, _q12("note"), attrib={"from": "location" if line.startswith("Location:") else "qa"}).text = line
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _write_back12(root, segments: list[dict], report: dict) -> None:
    by_loc = {s["loc"]: s for s in segments if s.get("loc")}
    rank = ["new", "draft", "confirmed", "reviewed"]
    for i, f in enumerate(root.iter(_q12("file"))):
        fid = _file_id12(f, i)
        for tu in f.iter(_q12("trans-unit")):
            pieces = _seg_pieces(tu)
            segmented = tu.find(_q12("seg-source")) is not None and pieces and pieces[0][1] is not tu.find(_q12("source"))
            texts: list[tuple[object, str | None, object]] = []  # (source element, our target, existing target element)
            statuses = []
            for k, s_el, t_el in pieces:
                s = by_loc.get(LOC_SEP.join([fid, tu.get("id", ""), str(k)]))
                ours = None
                if s is not None and s.get("target") and s.get("translatable", True):
                    source, _ = from_xliff(s_el)
                    if source != s["source"]:
                        report["mismatch"].append(s["id"])
                    else:
                        ours, fixes = inline.repair(source, s["target"])
                        if fixes:
                            report["repaired"][s["id"]] = fixes
                        statuses.append(s.get("status") or "draft")
                        report["written"] += 1
                texts.append((s_el, ours, t_el))
            if not statuses:
                continue
            old = tu.find(_q12("target"))
            new = etree.Element(_q12("target"))
            if segmented:
                seg_src = tu.find(_q12("seg-source"))
                new.text = seg_src.text
                for s_el, ours, t_el in texts:
                    mrk = etree.SubElement(new, _q12("mrk"), mtype="seg", mid=s_el.get("mid", ""))
                    if ours is not None:
                        to_xliff(mrk, ours, from_xliff(s_el)[1], version="1.2")
                    elif t_el is not None:
                        mrk.text = t_el.text
                        mrk.extend(copy.deepcopy(c) for c in t_el)
                    mrk.tail = s_el.tail
            else:
                s_el, ours, _ = texts[0]
                to_xliff(new, ours, from_xliff(s_el)[1], version="1.2")
            if old is not None:
                tu.replace(old, new)
            else:
                anchor = tu.find(_q12("seg-source")) if tu.find(_q12("seg-source")) is not None else tu.find(_q12("source"))
                anchor.addnext(new)
            status = min(statuses, key=rank.index)
            new.set("state", STATE12_OF.get(status, "translated"))
            tu.set(f"{{{AT}}}status", status)
            if status in ("confirmed", "reviewed"):
                tu.set("approved", "yes")


def write_back(data: bytes, segments: list[dict]) -> tuple[bytes, dict]:
    """Fill our translations (and states) into the original XLIFF file → (file, report)."""
    root = etree.fromstring(data, _parser())
    report = {"written": 0, "mismatch": [], "repaired": {}}
    if root.get("version", "").startswith("1"):
        _write_back12(root, segments, report)
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8"), report
    by_loc = {s["loc"]: s for s in segments if s.get("loc")}
    for f in root.iter(_q("file")):
        for unit in f.iter(_q("unit")):
            for k, seg_el in enumerate(unit.findall(_q("segment"))):
                s = by_loc.get(LOC_SEP.join([f.get("id", ""), unit.get("id", ""), str(k)]))
                src_el = seg_el.find(_q("source"))
                if s is None or src_el is None or not s.get("target") or not s.get("translatable", True):
                    continue
                source, originals = from_xliff(src_el)
                if source != s["source"]:
                    report["mismatch"].append(s["id"])
                    continue
                target, fixes = inline.repair(source, s["target"])
                if fixes:
                    report["repaired"][s["id"]] = fixes
                old = seg_el.find(_q("target"))
                if old is not None:
                    seg_el.remove(old)
                tgt_el = etree.Element(_q("target"))
                src_el.addnext(tgt_el)
                to_xliff(tgt_el, target, originals)
                status = s.get("status") or "draft"
                seg_el.set("state", STATE_OF.get(status, "translated"))
                seg_el.set("subState", f"at:{status}")
                report["written"] += 1
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8"), report


# --------------------------------------------------------------------------- #
# Re-import (as a proposal)
# --------------------------------------------------------------------------- #


def _same_source(a: str, b: str) -> bool:
    norm = lambda t: " ".join(unicodedata.normalize("NFC", inline.strip(t)).split())  # noqa: E731
    return norm(a) == norm(b) and inline.codes(a) == inline.codes(b)


def import_changes(data: bytes, segments: list[dict], *, src: str, tgt: str) -> tuple[list[dict], dict]:
    """Translations from a returned XLIFF → (proposal changes, report). Nothing is applied here.

    Rules: languages must match; unknown units and units whose source changed are reported, not used;
    locked segments are never changed; a segment someone confirmed is only replaced by a `final` unit;
    a translation whose codes don't match its source is reported, not used.
    """
    doc = parse(data)
    if _primary(doc["src"]) != _primary(src) or _primary(doc["tgt"]) != _primary(tgt):
        raise ValueError(f"The file is {doc['src'] or '?'} → {doc['tgt'] or '?'}, this document is {src} → {tgt}.")
    by_loc = {s["loc"]: s for s in segments if s.get("loc")}
    by_id = {s["id"]: s for s in segments}
    report = {"changes": 0, "unchanged": 0, "unknown": [], "source_changed": [], "locked": [], "kept_confirmed": [], "codes": []}
    changes = []
    for u in doc["units"]:
        seg = by_loc.get(u["loc"]) or (by_id.get(u["unit"]) if u["index"] == 0 else None)
        if seg is None:
            report["unknown"].append(u["unit"])
            continue
        if not _same_source(u["source"], seg["source"]):
            report["source_changed"].append(seg["id"])
            continue
        target = inline.normalize(u["target"]) if u["target"] else None
        if not target or not inline.strip(target).strip() or target == seg.get("target"):
            report["unchanged"] += 1
            continue
        if seg.get("locked") or not seg.get("translatable", True):
            report["locked"].append(seg["id"])
            continue
        if seg.get("status") in ("confirmed", "reviewed") and u["state"] != "final":
            report["kept_confirmed"].append(seg["id"])
            continue
        if inline.validate(seg["source"], target):
            report["codes"].append(seg["id"])
            continue
        changes.append({"segment_id": seg["id"], "field": "target", "before": seg.get("target") or "", "after": target,
                        "status": _status(u["state"], u["sub_state"]) if u["state"] != "initial" else "draft"})
    report["changes"] = len(changes)
    return changes, report


def proposal(changes: list[dict], filename: str) -> dict:
    return {"id": f"xliff-{int(time.time())}", "notes": [f"XLIFF import: {filename}"], "changes": changes,
            "glossary": {}, "created_at": time.time(), "origin": "xliff"}

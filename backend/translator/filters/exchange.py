"""CAT-tool exchange formats: TMX 1.4b (translation memory), TBX (termbase), CSV glossaries.

XML from outside is parsed with entity resolution and network access disabled (no XXE / billion
laughs). Language matching uses the primary subtag, so "de-DE" in a file matches a German project.
"""

from __future__ import annotations

import csv
import io
import re
import time
from collections.abc import Iterable

from lxml import etree

from ..text import plain

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
# Header cells that name a language, in English and in the language itself.
LANG_NAMES = {
    "de": {"german", "deutsch"}, "en": {"english", "englisch", "anglais", "inglés", "inglese"},
    "fr": {"french", "français", "francais", "französisch"}, "es": {"spanish", "español", "espanol", "spanisch"},
    "it": {"italian", "italiano", "italienisch"}, "pt": {"portuguese", "português", "portugues"},
    "nl": {"dutch", "nederlands", "niederländisch"}, "pl": {"polish", "polski"}, "sv": {"swedish", "svenska"},
    "tr": {"turkish", "türkçe"}, "ru": {"russian", "русский"}, "uk": {"ukrainian", "українська"},
    "el": {"greek", "ελληνικά"}, "ar": {"arabic", "العربية"}, "he": {"hebrew", "עברית"}, "hi": {"hindi", "हिन्दी"},
    "ja": {"japanese", "日本語"}, "ko": {"korean", "한국어"},
    "zh": {"chinese", "中文", "简体中文", "繁體中文", "chinese (simplified)", "chinese (traditional)"},
}
HEADER_WORDS = {"source", "target", "term", "translation", "note", "notes", "comment", "definition", "forbidden", "do not use", "deprecated"}
TBX3_NS = "urn:iso:std:iso:30042:ed-2"
_INLINE = {"bpt", "ept", "ph", "it", "hi", "ut", "sub"}  # TMX inline markup: codes, not text


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, remove_comments=True)


def _primary(code: str | None) -> str:
    return (code or "").split("-")[0].split("_")[0].lower()


def _local(tag) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _lang(el) -> str:
    return el.get(XML_LANG) or el.get("lang") or ""


# --------------------------------------------------------------------------- #
# TMX
# --------------------------------------------------------------------------- #


def tmx_export(units: Iterable[dict], src: str, tgt: str) -> bytes:
    root = etree.Element("tmx", version="1.4")
    etree.SubElement(
        root, "header", creationtool="AgenticTranslator", creationtoolversion="1", segtype="paragraph",
        attrib={"o-tmf": "agentic-translator", "adminlang": "en", "srclang": src, "datatype": "plaintext"},
    )
    body = etree.SubElement(root, "body")
    for u in units:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(u.get("updated_at") or time.time()))
        tu = etree.SubElement(body, "tu", creationdate=stamp, changedate=stamp)
        if u.get("origin"):
            etree.SubElement(tu, "prop", type="x-origin").text = u["origin"]
        for lang, text in ((src, u["source"]), (tgt, u["target"])):
            tuv = etree.SubElement(tu, "tuv", attrib={XML_LANG: lang})
            etree.SubElement(tuv, "seg").text = plain(text)  # markdown would show literally in other tools
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _seg_text(seg) -> str:
    """Text of a <seg>, skipping inline code elements (but keeping the text that follows them)."""
    parts = [seg.text or ""]
    for child in seg:
        # Inline codes carry no text; unresolved entity references (never expanded, for safety) are dropped.
        if child.tag is not etree.Entity and _local(child.tag) not in _INLINE:
            parts.append(_seg_text(child))
        parts.append(child.tail or "")
    return "".join(parts).strip()


def tmx_import(data: bytes, src: str, tgt: str) -> tuple[list[dict], list[str]]:
    """→ ([{source, target, origin}], warnings). Units without both languages are skipped."""
    root = etree.fromstring(data, _parser())
    if _local(root.tag) != "tmx":
        raise ValueError("Not a TMX file")
    units, skipped = [], 0
    for tu in root.iter("{*}tu", "tu"):
        texts = {}
        for tuv in tu.iter("{*}tuv", "tuv"):
            seg = next(tuv.iter("{*}seg", "seg"), None)
            if seg is not None:
                texts.setdefault(_primary(_lang(tuv)), _seg_text(seg))
        source, target = texts.get(_primary(src)), texts.get(_primary(tgt))
        if source and target:
            origin = next((p.text for p in tu.iter("{*}prop", "prop") if p.get("type") == "x-origin"), "") or "tmx import"
            units.append({"source": source, "target": target, "origin": origin})
        else:
            skipped += 1
    warnings = [f"{skipped} unit(s) skipped: missing {src} or {tgt}"] if skipped else []
    return units, warnings


# --------------------------------------------------------------------------- #
# TBX (import v2 "martif" and v3; export v3 TBX-Basic)
# --------------------------------------------------------------------------- #


def _deprecated(container) -> bool:
    for note in container.iter("{*}termNote", "termNote"):
        if note.get("type") in ("administrativeStatus", "normativeAuthorization") and "deprecated" in (note.text or "").lower():
            return True
    return False


def tbx_import(data: bytes, src: str, tgt: str) -> tuple[list[dict], list[str]]:
    """→ ([{source, target, note, forbidden}], warnings)."""
    root = etree.fromstring(data, _parser())
    if _local(root.tag) not in ("martif", "tbx"):
        raise ValueError("Not a TBX file")
    entries, warnings = [], []
    for entry in [e for e in root.iter() if _local(e.tag) in ("termEntry", "conceptEntry")]:
        note = ""
        for el in entry.iter():
            if (_local(el.tag) == "descrip" and el.get("type") == "definition") or _local(el.tag) == "note":
                note = (el.text or "").strip()
                if note:
                    break
        langs: dict[str, dict[str, list[str]]] = {}
        for lang_el in [e for e in entry if _local(e.tag) in ("langSet", "langSec")]:
            bucket = langs.setdefault(_primary(_lang(lang_el)), {"ok": [], "bad": []})
            for holder in [e for e in lang_el.iter() if _local(e.tag) in ("tig", "ntig", "termSec")]:
                term = next((t for t in holder.iter() if _local(t.tag) == "term"), None)
                if term is not None and (term.text or "").strip():
                    bucket["bad" if _deprecated(holder) else "ok"].append(term.text.strip())
        sources = langs.get(_primary(src), {}).get("ok", [])
        target_bucket = langs.get(_primary(tgt), {"ok": [], "bad": []})
        if not sources:
            continue
        for source in sources:
            entries.append({
                "source": source,
                "target": target_bucket["ok"][0] if target_bucket["ok"] else "",
                "note": note,
                "forbidden": target_bucket["bad"],
            })
    if not entries:
        warnings.append(f"No entries with a {src} term found")
    return entries, warnings


def tbx_export(terms: Iterable[dict], src: str, tgt: str) -> bytes:
    root = etree.Element(f"{{{TBX3_NS}}}tbx", nsmap={None: TBX3_NS}, type="TBX-Basic", style="dca", attrib={XML_LANG: "en"})
    desc = etree.SubElement(etree.SubElement(etree.SubElement(root, "tbxHeader"), "fileDesc"), "sourceDesc")
    etree.SubElement(desc, "p").text = "Exported from Agentic Translator"
    body = etree.SubElement(etree.SubElement(root, "text"), "body")
    for i, t in enumerate(terms, start=1):
        entry = etree.SubElement(body, "conceptEntry", id=f"c{i}")
        if t.get("note"):
            etree.SubElement(entry, "descrip", type="definition").text = t["note"]
        for lang, items in ((src, [(t["source"], "preferredTerm-admn-sts")]),
                            (tgt, ([(t["target"], "preferredTerm-admn-sts")] if t.get("target") else [])
                             + [(bad, "deprecatedTerm-admn-sts") for bad in t.get("forbidden") or []])):
            if not items:
                continue
            sec = etree.SubElement(entry, "langSec", attrib={XML_LANG: lang})
            for text, status in items:
                term_sec = etree.SubElement(sec, "termSec")
                etree.SubElement(term_sec, "term").text = text
                etree.SubElement(term_sec, "termNote", type="administrativeStatus").text = status
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# --------------------------------------------------------------------------- #
# CSV glossaries
# --------------------------------------------------------------------------- #


def csv_import(data: bytes, src: str, tgt: str, src_name: str = "", tgt_name: str = "") -> tuple[list[dict], list[str]]:
    """Columns by header (source/target/note/forbidden, or the language names/codes), else source,target[,note]."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        return [], ["Empty file"]
    header = [c.strip().lower() for c in rows[0]]
    names = lambda code, extra: {code.lower(), _primary(code), (extra or "").lower(), *LANG_NAMES.get(_primary(code), set())}  # noqa: E731
    src_names, tgt_names = names(src, src_name), names(tgt, tgt_name)
    known = HEADER_WORDS | set().union(*LANG_NAMES.values())

    def col(*candidates: str) -> int | None:
        for i, h in enumerate(header):
            if h in candidates:
                return i
        return None

    is_header = any(h in known or h in src_names or h in tgt_names for h in header)
    s_col = col("source", "term", *src_names)
    t_col = col("target", "translation", *tgt_names)
    if s_col is None or t_col is None:
        s_col, t_col = 0, 1  # no language columns named: source, target[, note]
    start = 1 if is_header else 0
    n_col, f_col = col("note", "comment", "definition"), col("forbidden", "do not use", "deprecated")
    entries, warnings = [], []
    for i, row in enumerate(rows[start:], start=start + 1):
        cell = lambda c: row[c].strip() if c is not None and c < len(row) else ""  # noqa: E731
        source, target = cell(s_col), cell(t_col)
        if not source:
            warnings.append(f"Row {i}: no source term")
            continue
        forbidden = [x.strip() for x in re.split(r"[|;]", cell(f_col)) if x.strip()] if f_col is not None else []
        entries.append({"source": source, "target": target, "note": cell(n_col), "forbidden": forbidden})
    return entries, warnings


def csv_export(terms: Iterable[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["source", "target", "note", "forbidden"])
    for t in terms:
        writer.writerow([t["source"], t.get("target", ""), t.get("note", ""), "; ".join(t.get("forbidden") or [])])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel opens UTF-8 correctly

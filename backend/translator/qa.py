"""Deterministic quality assurance: a registry of checks over segments, computed on request.

Two kinds of output:
- **Flags** on freshly translated segments (`untranslated`, `merged`), set by the pipeline.
- **QA issues** for the whole document (`run`): numbers and dates, terminology (approved and forbidden
  terms), markup, punctuation, spacing, consistency and length. Each issue has a stable fingerprint
  (check + segment + text), so a person can ignore it until the text changes.

Severity: an `error` is precise enough to be a forced review issue (the refiner must fix it);
a `warning` is shown in the QA panel only.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Any

from .documents import NO_SPACE_CHARS
from .filters import inline
from .filters.align import markdown_grid
from .text import contains_term

UNTRANSLATED = "untranslated"
MERGED = "merged"

FLAG_NOTES = {
    UNTRANSLATED: "Not translated: the translation is missing or still in the source language → translate this segment.",
    MERGED: "Possibly merged with a neighbouring segment (text moved in or out) → translate exactly this segment's own source text, nothing more or less.",
}

_NO_SPACE = re.compile(f"[{NO_SPACE_CHARS}]")
_WORD = re.compile(r"[^\W\d_]{4,}")
_MIN_MEASURABLE = 15  # chars of source below which length ratios are too noisy


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


# --------------------------------------------------------------------------- #
# Flags on fresh translations (used by the pipeline while translating)
# --------------------------------------------------------------------------- #


def looks_untranslated(source: str, target: str | None) -> bool:
    """Empty, or the source echoed back for a segment that is real prose (not a name, code or number)."""
    if not (target or "").strip():
        return True
    if _norm(source) != _norm(target):
        return False
    return len(_WORD.findall(source)) >= 3 or len(_NO_SPACE.findall(source)) >= 6


def suspect_merges(batch: list[dict], translated: dict[str, str]) -> set[str]:
    """Ids whose translations look shifted between neighbours (one swallowed the next)."""
    def target(seg: dict) -> str:
        return translated.get(seg["id"]) or ""

    ratios = {
        s["id"]: len(target(s)) / len(s["source"]) for s in batch if len(s["source"]) >= _MIN_MEASURABLE and target(s)
    }
    med = median(ratios.values()) if len(ratios) >= 3 else None
    suspects: set[str] = set()

    # Same translation for different source texts.
    seen: dict[str, dict] = {}
    for s in batch:
        key = _norm(target(s))
        if len(key) >= _MIN_MEASURABLE:
            other = seen.get(key)
            if other and _norm(other["source"]) != _norm(s["source"]):
                suspects |= {other["id"], s["id"]}
            seen[key] = s

    for i, s in enumerate(batch):
        long_t = _norm(target(s))
        if not long_t:
            continue
        for j in (i - 1, i + 1):
            if not 0 <= j < len(batch):
                continue
            n = batch[j]
            n_t = _norm(target(n))
            if len(n["source"]) < _MIN_MEASURABLE:
                continue
            # A neighbour's translation repeated inside this one.
            if len(n_t) >= _MIN_MEASURABLE and n_t in long_t and len(long_t) > len(n_t) * 1.3:
                suspects |= {s["id"], n["id"]}
            # This one is unusually long while the neighbour is empty or unusually short.
            r = ratios.get(s["id"])
            if med and r and r > 1.6 * med:
                n_r = ratios.get(n["id"])
                if not n_t or (n_r is not None and n_r < 0.45 * med):
                    suspects |= {s["id"], n["id"]}
    return suspects


def in_source(term: str, segments: list[dict]) -> bool:
    """Does a term the model reported actually occur in these segments' source text?"""
    t = _norm(term)
    return bool(t) and any(t in _norm(s["source"]) for s in segments)


def check_segment(seg: dict, target: str | None, merged: bool = False) -> list[str]:
    """Flags for a freshly translated segment."""
    flags = []
    if looks_untranslated(seg["source"], target):
        flags.append(UNTRANSLATED)
    if merged:
        flags.append(MERGED)
    return flags


# --------------------------------------------------------------------------- #
# Numbers and dates
# --------------------------------------------------------------------------- #

MONTHS: dict[str, int] = {}
for _names in (
    "january february march april may june july august september october november december",  # en
    "januar februar märz april mai juni juli august september oktober november dezember",  # de
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",  # fr
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",  # es
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre",  # it
    "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro",  # pt
    "januari februari maart april mei juni juli augustus september oktober november december",  # nl
):
    for _i, _name in enumerate(_names.split(), start=1):
        MONTHS.setdefault(_name, _i)
for _abbr, _i in {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
                  "oct": 10, "okt": 10, "nov": 11, "dec": 12, "dez": 12, "jän": 1, "mrz": 3}.items():
    MONTHS.setdefault(_abbr, _i)
_MONTH = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))

# Month words that are also ordinary words ("2 may be", "Mar"): dates only when a year follows.
_AMBIGUOUS_MONTHS = {"may", "mar", "march", "jan", "dec", "sep", "sept", "august"}


def _textual(day: str, month: str, year: str | None) -> list[tuple]:
    if month.lower() in _AMBIGUOUS_MONTHS and not year:
        return []
    return [(int(day), MONTHS[month.lower()], int(year) if year else None)]


_DATE_PATTERNS: list[tuple[re.Pattern, Callable[[re.Match], list[tuple]]]] = [
    # 2026-04-30 (ISO)
    (re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"), lambda m: [(int(m[3]), int(m[2]), int(m[1]))]),
    # 2026年4月30日 / 4月30日
    (re.compile(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]"),
     lambda m: [(int(m[3]), int(m[2]), int(m[1]) if m[1] else None)]),
    # 30.04.2026 · 30/04/26 · 04/30/2026 (day and month may be either way round)
    (re.compile(r"(?<![\d.])(\d{1,2})([./-])(\d{1,2})\2(\d{4}|\d{2})(?![\d])"),
     lambda m: [(int(m[1]), int(m[3]), int(m[4])), (int(m[3]), int(m[1]), int(m[4]))]),
    # 30 April 2026 · 30. April · 30th of April 2026 · 30 de abril de 2026
    (re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th|er|\.|º)?\s+(?:of\s+|de\s+)?({_MONTH})\.?(?:,?\s+(?:de\s+)?(\d{{4}}))?(?![\w])", re.I),
     lambda m: _textual(m[1], m[2], m[3])),
    # April 30, 2026 · April 30th
    (re.compile(rf"(?<![\w])({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?!\d)", re.I),
     lambda m: _textual(m[2], m[1], m[3])),
    # 30.04. (German day and month without a year) · 30/04
    (re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(?!\d)"), lambda m: [(int(m[1]), int(m[2]), None)]),
    (re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])"), lambda m: [(int(m[1]), int(m[2]), None), (int(m[2]), int(m[1]), None)]),
]
_TIME = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?:\s*([ap])\.?m\.?)?(?![\d:])", re.I)
_NUMBER = re.compile(r"(?<![\d])\d{1,3}(?:[   ']\d{3})+(?![\d])|\d+(?:[.,]\d+)*")

# An extracted item: (the readings it may have, the text as written).
Item = tuple[frozenset, str]


def _dates_and_rest(text: str) -> tuple[list[Item], list[Item], str]:
    """→ (dates, times, the text with both removed)."""
    text = unicodedata.normalize("NFKC", text or "")
    dates: list[Item] = []
    for pattern, read in _DATE_PATTERNS:
        def take(m: re.Match) -> str:
            readings = frozenset((d, mo, y % 100 if y is not None else None) for d, mo, y in read(m) if 1 <= d <= 31 and 1 <= mo <= 12)
            if not readings:
                return m[0]
            dates.append((readings, m[0].strip()))
            return " "
        text = pattern.sub(take, text)
    times: list[Item] = []

    def take_time(m: re.Match) -> str:
        h = int(m[1])
        if m[3]:
            h = h % 12 + (12 if m[3].lower() == "p" else 0)
        times.append((frozenset({f"{h}:{m[2]}"}), m[0]))
        return " "

    return dates, times, _TIME.sub(take_time, text)


def _canon(whole: str, frac: str = "") -> str:
    return format(Decimal(f"{whole}.{frac}" if frac else whole).normalize(), "f")


def _readings(token: str) -> frozenset:
    """What a number may mean ("1.500" → {"1500", "1.5"}; "1.000,5" → {"1000.5"}; "4.2.7" stays an identifier)."""
    token = re.sub(r"[   ']", "", token)
    seps = re.findall(r"[.,]", token)
    groups = re.split(r"[.,]", token)
    if not seps:
        return frozenset({_canon(token)})
    if len(set(seps)) == 2:  # both kinds: the last one is the decimal separator
        return frozenset({_canon("".join(groups[:-1]), groups[-1])})
    if len(seps) > 1:
        if len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:]):
            return frozenset({_canon("".join(groups))})  # 1.234.567
        return frozenset({".".join(_canon(g) for g in groups)})  # an identifier like 4.2.7
    if len(groups[1]) == 3:  # 1.500 / 1,500: thousands, or a decimal with three places
        return frozenset({_canon("".join(groups)), _canon(groups[0], groups[1])})
    return frozenset({_canon(groups[0], groups[1])})


def _numbers(text: str) -> tuple[list[Item], list[Item], list[Item]]:
    dates, times, rest = _dates_and_rest(text)
    return dates, times, [(_readings(t), t) for t in _NUMBER.findall(rest)]


def _same_date(a: Item, b: Item) -> bool:
    return any(d1 == d2 and m1 == m2 and (y1 is None or y2 is None or y1 == y2) for d1, m1, y1 in a[0] for d2, m2, y2 in b[0])


def _same(a: Item, b: Item) -> bool:
    return bool(a[0] & b[0])


def _match(src: list[Item], tgt: list[Item], same: Callable[[Item, Item], bool]) -> tuple[list[Item], list[Item]]:
    """Greedy multiset matching → (unmatched source items, unmatched target items)."""
    left = list(tgt)
    missing = []
    for item in src:
        hit = next((i for i, t in enumerate(left) if same(item, t)), None)
        if hit is None:
            missing.append(item)
        else:
            left.pop(hit)
    return missing, left


# --------------------------------------------------------------------------- #
# Check registry
# --------------------------------------------------------------------------- #


@dataclass
class Context:
    segments: list[dict]  # all segments, document order
    terms: list[dict]  # project terms + document glossary: {source, target, forbidden, case_sensitive}
    target_lang: str = ""


@dataclass(frozen=True)
class Check:
    id: str
    label: str
    category: str  # MQM category a forced review issue gets
    run: Callable[[dict, Context], Iterable[tuple[str, str, str]]] | None = None  # per segment → (severity, message, detail)
    run_document: Callable[[Context], Iterable[tuple[str, str, str, str]]] | None = None  # → (segment_id, severity, message, detail)


CHECKS: list[Check] = []


def check(id: str, label: str, category: str, document: bool = False):
    def register(fn):
        CHECKS.append(Check(id, label, category, None if document else fn, fn if document else None))
        return fn

    return register


@check("untranslated", "Untranslated", "accuracy")
def _untranslated(seg: dict, ctx: Context):
    if UNTRANSLATED in (seg.get("flags") or []) or looks_untranslated(seg["source"], seg.get("target")):
        yield "error", "Not translated (empty, or still in the source language).", ""


@check("merged", "Merged segments", "accuracy")
def _merged(seg: dict, ctx: Context):
    if MERGED in (seg.get("flags") or []):
        yield "error", "Looks merged with a neighbouring segment: text moved in or out.", ""


@check("numbers", "Numbers & dates", "accuracy")
def _numbers_check(seg: dict, ctx: Context):
    if seg.get("kind") == "figure" and not seg.get("target"):
        return
    s_dates, s_times, s_nums = _numbers(seg["source"])
    t_dates, t_times, t_nums = _numbers(seg.get("target") or "")
    for missing, extra, kind in (
        (*_match(s_dates, t_dates, _same_date), "Date"),
        (*_match(s_times, t_times, _same), "Time"),
        (*_match(s_nums, t_nums, _same), "Number"),
    ):
        for _, shown in missing:
            yield "error", f"{kind} {shown} from the source is missing or different in the translation.", f"missing:{shown}"
        for _, shown in extra:
            yield "warning", f"{kind} {shown} is in the translation but not in the source.", f"extra:{shown}"


@check("terminology", "Terminology", "terminology")
def _terminology(seg: dict, ctx: Context):
    target = seg.get("target") or ""
    folded = _norm(target)
    for t in ctx.terms:
        if not contains_term(seg["source"], t["source"], t.get("case_sensitive", False)):
            continue
        forbidden = [bad for bad in t.get("forbidden") or [] if contains_term(target, bad)]
        for bad in forbidden:
            use = f' → use "{t["target"]}"' if t.get("target") else ""
            yield "error", f'Forbidden translation "{bad}" for "{t["source"]}"{use}.', f"forbidden:{t['source']}:{bad}"
        # Substring, not whole word: inflected forms ("cable trays", "Kabelpritschen") still count.
        # A proposed term (an AI recommendation nobody confirmed) is a suggestion, not a rule.
        if t.get("target") and t.get("status") != "proposed" and not forbidden and _norm(t["target"]) not in folded:
            yield "warning", f'"{t["source"]}" should be translated as "{t["target"]}".', f"missing:{t['source']}"


_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s", re.M)
@check("markup", "Markup & tags", "markup")
def _markup(seg: dict, ctx: Context):
    source, target = seg["source"], seg.get("target") or ""
    if not target:
        return
    s_h, t_h = _HEADING.match(source), _HEADING.match(target)
    if (s_h and s_h[1]) != (t_h and t_h[1]):
        want = f"a level-{len(s_h[1])} heading ({s_h[1]})" if s_h else "not a heading"
        yield "error", f"Heading markup differs from the source: should be {want}.", "heading"
    if seg.get("kind") == "table":
        s_grid, t_grid = markdown_grid(source), markdown_grid(target)
        if len(s_grid) != len(t_grid) or [len(r) for r in s_grid] != [len(r) for r in t_grid]:
            yield "error", f"Table shape differs: {len(s_grid)}×{max(map(len, s_grid), default=0)} in the source, " \
                           f"{len(t_grid)}×{max(map(len, t_grid), default=0)} in the translation.", "table"
    if _LIST_ITEM.search(source) and len(_LIST_ITEM.findall(source)) != len(_LIST_ITEM.findall(target)):
        yield "warning", "Number of list items differs from the source.", "list"
    problems = inline.validate(source, target) if inline.has_codes(source) or inline.has_codes(target) else []
    if problems:
        detail = "; ".join(problems)
        yield "error", f"Inline codes don't match the source: {detail}.", "codes:" + detail
    source, target = inline.strip(source), inline.strip(target)
    if source.count("**") != target.count("**"):
        yield "warning", "Bold markup (**) differs from the source.", "bold"


_END_STRIP = re.compile(r"[\s*_`\"'’”»)\]）」』|]+$")
_EQUIV = {"。": ".", "．": ".", "！": "!", "？": "?", "：": ":", "；": ";", "…": ".",
          "।": ".", "॥": ".", "۔": ".", "။": ".", "։": ".",  # Devanagari/Bengali danda, Urdu, Myanmar, Armenian
          "؟": "?", "؛": ";", "\u037e": "?"}  # Arabic question mark and semicolon; Greek question mark (;)
# Thai, Lao and Khmer end sentences with a space, not a mark: no final punctuation to compare.
_NO_FINAL_MARK = re.compile(r"[\u0e00-\u0eff\u1780-\u17ff]")


# A full stop that belongs to an abbreviation ("No.", "approx.", "e.g.") isn't sentence punctuation.
_ABBREV_END = re.compile(r"(?:^|\W)(?:no|nos|nr|approx|ca|etc|co|ltd|inc|corp|vs|cf|fig|figs|ref|art|para|sec|vol|"
                         r"pp|p|e\.g|i\.e|incl|excl|max|min|dept|est|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.$", re.I)


def _final(text: str) -> str:
    text = _END_STRIP.sub("", text or "")
    if _ABBREV_END.search(text):
        return ""
    ch = text[-1:] if text else ""
    ch = _EQUIV.get(ch, ch)
    return ch if ch in ".!?:;" else ""


@check("punctuation", "Punctuation", "fluency")
def _punctuation(seg: dict, ctx: Context):
    if seg.get("kind") in ("table", "figure") or not seg.get("target"):
        return
    s, t = _final(seg["source"]), _final(seg["target"])
    if not s and _NO_FINAL_MARK.search(_END_STRIP.sub("", seg["source"])[-1:]):
        return
    if s != t:
        yield "warning", f"Ends with “{t or 'no punctuation'}” but the source ends with “{s or 'no punctuation'}”.", f"{s}{t}"


@check("spaces", "Spaces", "fluency")
def _spaces(seg: dict, ctx: Context):
    target = seg.get("target") or ""
    if re.search(r"[^\s|] {2,}\S", target) and not re.search(r"[^\s|] {2,}\S", seg["source"]):
        yield "warning", "Double space in the translation.", "double"
    if re.search(r" [,.;:!?](?:\s|$)", target) and not (ctx.target_lang or "").startswith("French"):
        yield "warning", "Space before punctuation.", "before-punct"


@check("consistency", "Consistency", "fluency", document=True)
def _consistency(ctx: Context):
    by_source: dict[str, list[dict]] = defaultdict(list)
    for s in ctx.segments:
        if s.get("translatable", True) and s.get("target") and len(_norm(s["source"])) >= 3:
            by_source[_norm(s["source"])].append(s)
    for group in by_source.values():
        versions = {_norm(s["target"]) for s in group}
        if len(versions) > 1:
            ids = ", ".join(s["id"] for s in group)
            for s in group:
                yield s["id"], "warning", f"Same source translated {len(versions)} different ways ({ids}).", ids


@check("length", "Length", "accuracy", document=True)
def _length(ctx: Context):
    measured = [s for s in ctx.segments if s.get("translatable", True) and s.get("target") and len(s["source"]) >= 20
                and s.get("kind") not in ("table", "figure")]
    ratios = {s["id"]: len(s["target"]) / len(s["source"]) for s in measured}
    if len(ratios) < 4:
        return
    med = median(ratios.values())
    for s in measured:
        r = ratios[s["id"]] / med
        if r > 2.2 or r < 0.45:
            word = "long" if r > 1 else "short"
            yield s["id"], "warning", f"Unusually {word} translation (×{r:.1f} the document's usual length ratio).", word


CHECK_BY_ID = {c.id: c for c in CHECKS}


def _fingerprint(check_id: str, seg: dict, detail: str) -> str:
    raw = "\x1f".join([check_id, seg["id"], _norm(seg["source"]), _norm(seg.get("target") or ""), detail])
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def run(segments: list[dict], terms: list[dict], target_lang: str = "", ignored: Iterable[str] = (),
        only: Iterable[str] | None = None) -> list[dict]:
    """QA issues for these segments: [{id, check, label, category, severity, segment_id, message, ignored}]."""
    ctx = Context(segments=segments, terms=terms, target_lang=target_lang)
    ignored = set(ignored)
    wanted = set(only) if only is not None else None
    by_id = {s["id"]: s for s in segments}
    out: list[dict] = []

    def add(c: Check, seg: dict, severity: str, message: str, detail: str) -> None:
        fp = _fingerprint(c.id, seg, detail)
        out.append({"id": fp, "check": c.id, "label": c.label, "category": c.category, "severity": severity,
                    "segment_id": seg["id"], "message": message, "ignored": fp in ignored})

    # Text checks look at the words only; the markup check sees the codes.
    plain = {s["id"]: {**s, "source": inline.strip(s["source"]), "target": inline.strip(s.get("target")) if s.get("target") else s.get("target")}
             for s in segments if inline.has_codes(s["source"]) or inline.has_codes(s.get("target"))}
    ctx_plain = Context(segments=[plain.get(s["id"], s) for s in segments], terms=terms, target_lang=target_lang)
    for c in CHECKS:
        if wanted is not None and c.id not in wanted:
            continue
        if c.run:
            for seg in segments:
                if seg.get("translatable", True):
                    view = seg if c.id == "markup" else plain.get(seg["id"], seg)
                    for severity, message, detail in c.run(view, ctx):
                        add(c, seg, severity, message, detail)
        else:
            for seg_id, severity, message, detail in c.run_document(ctx_plain):
                add(c, by_id[seg_id], severity, message, detail)
    order = {s["id"]: i for i, s in enumerate(segments)}
    out.sort(key=lambda x: (order.get(x["segment_id"], 0), x["severity"] != "error"))
    return out


def summary(issues: list[dict]) -> dict:
    active = [i for i in issues if not i["ignored"]]
    return {
        "errors": sum(i["severity"] == "error" for i in active),
        "warnings": sum(i["severity"] == "warning" for i in active),
        "ignored": len(issues) - len(active),
        "by_check": {c.id: sum(i["check"] == c.id for i in active) for c in CHECKS},
    }


# --------------------------------------------------------------------------- #
# Document-level helpers (state → QA)
# --------------------------------------------------------------------------- #


def terms_for(state: Mapping[str, Any], sources: list[str]) -> list[dict]:
    """Project terms that occur in these sources, plus the document glossary's confirmed targets."""
    from . import projects  # local: projects imports qa-free modules only

    pid = projects.project_id(state)
    terms = projects.get_store().terms_in(pid, sources) if pid else []
    known = {t["source"] for t in terms}
    for source, entry in (state.get("doc:glossary") or {}).items():
        if source not in known and entry.get("target"):
            terms.append({"source": source, "target": entry["target"], "forbidden": [], "case_sensitive": False})
    return terms


def document_qa(state: Mapping[str, Any], segments: list[dict] | None = None, only: Iterable[str] | None = None) -> list[dict]:
    from . import state as st

    segments = segments if segments is not None else [st.normalize(s) for s in st.get_segments(state)]
    return run(segments, terms_for(state, [s["source"] for s in segments]), state.get("doc:target_lang") or "",
               state.get("doc:qa_ignored") or [], only)


# Checks precise enough to force a fix in review. Document-level warnings never do.
FORCED = ("untranslated", "merged", "numbers", "terminology", "markup")


def forced_review_issues(state: Mapping[str, Any], segments: list[dict]) -> list[dict]:
    """QA errors on these segments as major review issues (the refiner must address them)."""
    issues = [i for i in document_qa(state, segments, FORCED) if i["severity"] == "error" and not i["ignored"]]
    out = []
    for i in issues:
        note = FLAG_NOTES.get(i["check"]) or f"Automatic QA ({i['label'].lower()}): {i['message']} → fix this in the translation."
        out.append({"segment_id": i["segment_id"], "severity": "major", "category": i["category"], "note": note, "auto": True})
    return out


def flag_issues(segments: list[dict]) -> list[dict]:
    """Review issues for flagged segments (always major)."""
    return [
        {"segment_id": s["id"], "severity": "major", "category": "accuracy", "note": FLAG_NOTES[f], "auto": True}
        for s in segments
        for f in s.get("flags") or []
        if f in FLAG_NOTES
    ]

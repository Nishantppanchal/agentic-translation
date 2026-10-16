"""Projects, termbase and translation memory — a small SQLite store next to the ADK sessions.

ADK session state stays the per-document working copy. Project data is shared across documents
and needs indexes (a TM can hold tens of thousands of units), so it lives in `data/projects.db`.

A project has one source language; the target is always English (`config.TARGET_LANG`). It holds
the style guide, the termbase and the translation memory shared by its documents.

TM matching (scores as translators know them from CAT tools):
  101  same source and same preceding segment (context match)
  100  same source
  75-99 fuzzy: candidates by a fast character ratio, rescored per word (per character for CJK)
Only segments a *person* confirmed (or reviewed) are written to the TM, so it stays clean. Each unit records how:
`approval` is segment (confirmed one by one), review (a reviewer's), proposal (an agent's change accepted with
Confirm), bulk (one click over many segments) or import. A lower approval never overwrites a higher one's
wording, and `ref` says where a unit came from (file#segment, or "import").
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process
from rapidfuzz.distance import Levenshtein

from .config import TARGET_LANG, get_settings
from .document.pages import NO_SPACE_CHARS
from .text import contains_term, norm

FUZZY_MIN = 75
_NO_SPACE = re.compile(f"[{NO_SPACE_CHARS}]")

SCHEMA = """
create table if not exists projects (
  id text primary key, name text not null, source_lang text default '', instructions text default '', created_at real);
create table if not exists project_documents (
  session_id text primary key, project_id text not null references projects(id) on delete cascade, created_at real);
create table if not exists terms (
  id integer primary key, project_id text not null references projects(id) on delete cascade,
  source text not null, target text not null default '', note text default '', forbidden text default '[]',
  case_sensitive integer default 0, status text default 'approved', created_at real, updated_at real,
  unique(project_id, source));
create table if not exists tm_units (
  id integer primary key, project_id text not null references projects(id) on delete cascade,
  source text not null, target text not null, source_key text not null, prev_key text default '',
  ref text default '', approval text default 'segment', prev_source text default '',
  created_at real, updated_at real, unique(project_id, source_key, prev_key));
create table if not exists app_settings (key text primary key, value text not null, updated_at real);
create table if not exists assist_usage (
  session_id text not null, step text not null, model_id text not null, effort text not null default '',
  calls integer default 0, prompt_tokens integer default 0, completion_tokens integer default 0,
  reasoning_tokens integer default 0, updated_at real, primary key (session_id, step, model_id, effort));
"""
# How a unit was approved, weakest first: a weaker approval never replaces a stronger one's wording.
APPROVALS = ("bulk", "import", "proposal", "segment", "review")
# Columns added after the first release (added to existing databases on open).
SETTINGS = {
    "auto_confirm_context": "integer default 1",  # 101% TM matches start as confirmed (CAT-tool default)
    "lqa_threshold": "real default 90",  # LQA pass mark: 100 − penalty points per 1000 source words
}

# Databases from the multilingual version (terms and TM units per target language): keep the English
# entries (or untagged ones from before that) and drop the rest — English is the only target now.
_MIGRATE = {  # table: (columns in the new table, the same columns in the old one)
    "terms": ("id, project_id, source, target, note, forbidden, case_sensitive, status, created_at, updated_at",) * 2,
    "tm_units": ("id, project_id, source, target, source_key, prev_key, ref, created_at, updated_at",
                 "id, project_id, source, target, source_key, prev_key, origin, created_at, updated_at"),
}


def _tokens(text: str) -> list[str]:
    """Words for spaced scripts, characters for CJK/Thai… (what a 'word' edit means in each)."""
    text = (text or "").casefold()
    if len(_NO_SPACE.findall(text)) > len(text) / 4:
        return [c for c in text if not c.isspace()]
    return re.findall(r"\w+", text)


def _term(row: sqlite3.Row) -> dict:
    return {**dict(row), "forbidden": json.loads(row["forbidden"] or "[]"), "case_sensitive": bool(row["case_sensitive"])}


class ProjectStore:
    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("pragma foreign_keys = on")
        if str(path) != ":memory:":
            self._db.execute("pragma journal_mode = wal")
        self._db.executescript(SCHEMA)
        self._migrate()
        self._lock = threading.RLock()
        self._tm_cache: dict[str, tuple[int, list[str], list[sqlite3.Row]]] = {}
        self._tm_version: dict[str, int] = {}

    def _migrate(self) -> None:
        have = {r["name"] for r in self._db.execute("pragma table_info(projects)")}
        for column, decl in SETTINGS.items():
            if column not in have:
                self._db.execute(f"alter table projects add column {column} {decl}")
        for table, (cols, old_cols) in _MIGRATE.items():
            if "target_lang" not in {r["name"] for r in self._db.execute(f"pragma table_info({table})")}:
                continue
            create = SCHEMA.split(f"create table if not exists {table} (", 1)[1].split(");", 1)[0]
            self._db.executescript(
                f"begin; create table {table}_new ({create});"
                f" insert or ignore into {table}_new ({cols}) select {old_cols} from {table}"
                f" where target_lang = '' or target_lang like '{TARGET_LANG}%' order by target_lang desc;"
                f" drop table {table}; alter table {table}_new rename to {table}; commit;"
            )
        # TM units before `ref` / `approval`: `origin` held the provenance.
        tm = {r["name"] for r in self._db.execute("pragma table_info(tm_units)")}
        if "origin" in tm and "ref" not in tm:
            self._db.execute("alter table tm_units rename column origin to ref")
        if "approval" not in tm:
            self._db.execute("alter table tm_units add column approval text default 'segment'")
            self._db.execute("update tm_units set approval = 'import' where ref = 'import'")
        if "prev_source" not in tm:
            self._db.execute("alter table tm_units add column prev_source text default ''")

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _w(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, args)

    # ---- app settings (app_settings.py) ----------------------------------- #

    def get_setting(self, key: str) -> Any:
        rows = self._q("select value from app_settings where key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else None

    def set_setting(self, key: str, value: Any) -> None:
        self._w("insert into app_settings (key, value, updated_at) values (?, ?, ?) on conflict(key) do update set "
                "value = excluded.value, updated_at = excluded.updated_at", (key, json.dumps(value), time.time()))

    # ---- AI assist usage (agents/assist.py) ---------------------------------- #
    # Suggestions, completions and translation summaries are model calls outside a run: they leave no session event, so
    # their tokens are counted here (and merged into the document's usage).

    def record_assist_usage(self, session_id: str, step: str, model_id: str, effort: str | None, prompt_tokens: int,
                            completion_tokens: int, reasoning_tokens: int) -> None:
        self._w(
            "insert into assist_usage (session_id, step, model_id, effort, calls, prompt_tokens, completion_tokens,"
            " reasoning_tokens, updated_at) values (?, ?, ?, ?, 1, ?, ?, ?, ?) on conflict(session_id, step, model_id, effort)"
            " do update set calls = calls + 1, prompt_tokens = prompt_tokens + excluded.prompt_tokens,"
            " completion_tokens = completion_tokens + excluded.completion_tokens,"
            " reasoning_tokens = reasoning_tokens + excluded.reasoning_tokens, updated_at = excluded.updated_at",
            (session_id, step, model_id, effort or "", prompt_tokens, completion_tokens, reasoning_tokens, time.time()),
        )

    def assist_usage(self, session_id: str) -> list[dict]:
        rows = self._q("select step, model_id, effort, calls, prompt_tokens, completion_tokens, reasoning_tokens"
                       " from assist_usage where session_id = ?", (session_id,))
        return [{**dict(r), "effort": r["effort"] or None} for r in rows]

    # ---- projects -------------------------------------------------------- #

    def create_project(self, name: str, source_lang: str = "", instructions: str = "", **settings: Any) -> dict:
        pid = uuid.uuid4().hex[:12]
        self._w(
            "insert into projects (id, name, source_lang, instructions, created_at) values (?, ?, ?, ?, ?)",
            (pid, name.strip() or "Untitled project", source_lang, instructions, time.time()),
        )
        return self.update_project(pid, **settings)

    def project(self, pid: str) -> dict | None:
        rows = self._q(
            """select p.*,
                 (select count(*) from project_documents d where d.project_id = p.id) as documents,
                 (select count(*) from terms t where t.project_id = p.id) as terms,
                 (select count(*) from tm_units u where u.project_id = p.id) as tm_units
               from projects p where p.id = ?""",
            (pid,),
        )
        if not rows:
            return None
        out = {k: v for k, v in dict(rows[0]).items() if k not in ("target_lang", "target_langs")}  # old databases
        out["auto_confirm_context"] = bool(out["auto_confirm_context"])
        return out

    def project_name(self, pid: str) -> str | None:
        rows = self._q("select name from projects where id = ?", (pid,))
        return rows[0]["name"] if rows else None

    def projects(self) -> list[dict]:
        return [self.project(r["id"]) for r in self._q("select id from projects order by created_at desc")]

    def update_project(self, pid: str, **fields: Any) -> dict | None:
        editable = {"name", "source_lang", "instructions", *SETTINGS}
        allowed = {k: v for k, v in fields.items() if k in editable and v is not None}
        if allowed:
            sets = ", ".join(f"{k} = ?" for k in allowed)
            self._w(f"update projects set {sets} where id = ?", (*allowed.values(), pid))
        return self.project(pid)

    def delete_project(self, pid: str) -> None:
        self._w("delete from projects where id = ?", (pid,))
        self._tm_cache.pop(pid, None)

    # ---- documents ------------------------------------------------------- #

    def attach(self, session_id: str, pid: str) -> None:
        self._w("insert or replace into project_documents values (?, ?, ?)", (session_id, pid, time.time()))

    def detach(self, session_id: str) -> None:
        self._w("delete from project_documents where session_id = ?", (session_id,))

    def project_of(self, session_id: str) -> str | None:
        rows = self._q("select project_id from project_documents where session_id = ?", (session_id,))
        return rows[0]["project_id"] if rows else None

    # ---- termbase -------------------------------------------------------- #

    def terms(self, pid: str) -> list[dict]:
        return [_term(r) for r in self._q("select * from terms where project_id = ? order by source collate nocase", (pid,))]

    def upsert_term(
        self, pid: str, source: str, target: str = "", note: str = "", forbidden: list[str] | None = None,
        case_sensitive: bool | None = None, status: str = "approved",
    ) -> dict:
        """Add a term, or merge into the existing entry for this source: non-empty fields win, forbidden
        variants accumulate. (Imports and write-through from clarifications never erase a target.)
        Status "proposed" (an AI recommendation nobody changed) never overrides an approved entry."""
        source, target, note = source.strip(), target.strip(), note.strip()
        now = time.time()
        with self._lock:
            rows = self._q("select * from terms where project_id = ? and source = ?", (pid, source))
            if rows:
                old = _term(rows[0])
                if status == "proposed" and old["status"] == "approved" and old["target"]:
                    return old
                bad = list(dict.fromkeys([*old["forbidden"], *(forbidden or [])]))
                self._w(
                    """update terms set target = ?, note = ?, forbidden = ?, case_sensitive = ?, status = ?, updated_at = ?
                       where id = ?""",
                    (target or old["target"], note or old["note"], json.dumps(bad, ensure_ascii=False),
                     int(old["case_sensitive"] if case_sensitive is None else case_sensitive),
                     status if target else old["status"], now, old["id"]),
                )
            else:
                self._w(
                    """insert into terms (project_id, source, target, note, forbidden, case_sensitive, status, created_at, updated_at)
                       values (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (pid, source, target, note, json.dumps(forbidden or [], ensure_ascii=False), int(bool(case_sensitive)),
                     status, now, now),
                )
            return _term(self._q("select * from terms where project_id = ? and source = ?", (pid, source))[0])

    def update_term(self, pid: str, term_id: int, **fields: Any) -> dict | None:
        """Replace fields of one entry (a person editing the termbase)."""
        cols = {"source", "target", "note", "forbidden", "case_sensitive", "status"}
        values = {k: v for k, v in fields.items() if k in cols and v is not None}
        if "forbidden" in values:
            values["forbidden"] = json.dumps([x.strip() for x in values["forbidden"] if x.strip()], ensure_ascii=False)
        if "case_sensitive" in values:
            values["case_sensitive"] = int(values["case_sensitive"])
        for k in ("source", "target", "note"):
            if k in values:
                values[k] = values[k].strip()
        if values:
            sets = ", ".join(f"{k} = ?" for k in values)
            self._w(f"update terms set {sets}, updated_at = ? where project_id = ? and id = ?", (*values.values(), time.time(), pid, term_id))
        rows = self._q("select * from terms where project_id = ? and id = ?", (pid, term_id))
        return _term(rows[0]) if rows else None

    def delete_term(self, pid: str, term_id: int) -> None:
        self._w("delete from terms where project_id = ? and id = ?", (pid, term_id))

    def terms_in(self, pid: str, texts: list[str]) -> list[dict]:
        """Terms whose source occurs in any of these texts (keeps prompts small with big termbases)."""
        return [t for t in self.terms(pid) if any(contains_term(x, t["source"], t["case_sensitive"]) for x in texts)]

    # ---- translation memory ---------------------------------------------- #

    def add_unit(self, pid: str, source: str, target: str, prev_source: str = "", ref: str = "",
                 approval: str = "segment") -> str:
        """Store one unit. → "added" | "updated" | "unchanged" | "kept" (see add_units)."""
        unit = {"source": source, "target": target, "prev_source": prev_source, "ref": ref, "approval": approval}
        return self.add_units(pid, [unit])[0]

    def add_units(self, pid: str, units: list[dict]) -> list[str]:
        """Insert or update units in one transaction (same source after the same previous source = the same unit).
        Per unit: "added"; "updated" (new wording); "unchanged" (same wording: its ref is kept, its approval may
        rise); "kept" (a weaker approval doesn't replace a stronger one's wording); "skipped" (empty)."""
        out: list[str] = []
        now = time.time()
        rank = {a: i for i, a in enumerate(APPROVALS)}
        with self._lock:
            self._db.execute("begin")
            try:
                for u in units:
                    key, prev = norm(u["source"]), norm(u.get("prev_source") or "")
                    target = (u.get("target") or "").strip()
                    if not key or not target:
                        out.append("skipped")
                        continue
                    approval = u.get("approval") if u.get("approval") in rank else "segment"
                    row = self._db.execute(
                        "select id, target, approval from tm_units where project_id = ? and source_key = ? and prev_key = ?",
                        (pid, key, prev),
                    ).fetchone()
                    if row is None:
                        self._db.execute(
                            """insert into tm_units (project_id, source, target, source_key, prev_key, ref, approval,
                                 prev_source, created_at, updated_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (pid, u["source"], target, key, prev, u.get("ref") or "", approval, u.get("prev_source") or "", now, now),
                        )
                        out.append("added")
                    elif row["target"] == target:
                        if rank[approval] > rank.get(row["approval"], 0):
                            self._db.execute("update tm_units set approval = ?, updated_at = ? where id = ?", (approval, now, row["id"]))
                        out.append("unchanged")
                    elif rank[approval] < rank.get(row["approval"], 0):
                        out.append("kept")
                    else:
                        self._db.execute(
                            "update tm_units set target = ?, source = ?, ref = ?, approval = ?, updated_at = ? where id = ?",
                            (target, u["source"], u.get("ref") or "", approval, now, row["id"]),
                        )
                        out.append("updated")
                self._db.execute("commit")
            except Exception:
                self._db.execute("rollback")
                raise
            self._tm_version[pid] = self._tm_version.get(pid, 0) + 1
        return out

    def _candidates(self, pid: str) -> tuple[list[str], list[sqlite3.Row]]:
        version = self._tm_version.get(pid, 0)
        cached = self._tm_cache.get(pid)
        if cached and cached[0] == version:
            return cached[1], cached[2]
        rows = self._q("select * from tm_units where project_id = ? order by updated_at desc", (pid,))
        keys = [r["source_key"] for r in rows]
        self._tm_cache[pid] = (version, keys, rows)
        return keys, rows

    def lookup(self, pid: str, source: str, prev_source: str = "", limit: int = 5) -> list[dict]:
        """Best TM matches for a segment: [{id, score, source, target, ref, approval}], best first."""
        key = norm(source)
        if not key:
            return []
        keys, rows = self._candidates(pid)
        prev = norm(prev_source)
        found: dict[int, dict] = {}
        for i, k in enumerate(keys):
            if k == key:
                r = rows[i]
                score = 101 if prev and r["prev_key"] == prev else 100
                if score > found.get(r["id"], {}).get("score", 0):
                    found[r["id"]] = _match(r, score)
        words = _tokens(source)
        for _, _, i in process.extract(key, keys, scorer=fuzz.ratio, limit=20, score_cutoff=60):
            r = rows[i]
            if r["id"] in found:
                continue
            score = min(99, round(100 * Levenshtein.normalized_similarity(words, _tokens(r["source"]))))
            if score >= FUZZY_MIN:
                found[r["id"]] = _match(r, score)
        best: dict[str, dict] = {}  # one entry per distinct source (prefer the higher score)
        for m in sorted(found.values(), key=lambda m: -m["score"]):
            best.setdefault(norm(m["source"]), m)
        return list(best.values())[:limit]

    def concordance(self, pid: str, query: str, limit: int = 30) -> list[dict]:
        q = f"%{query.strip()}%"
        rows = self._q(
            "select * from tm_units where project_id = ? and (source like ? or target like ?) order by updated_at desc limit ?",
            (pid, q, q, limit),
        )
        return [dict(r) for r in rows]

    def units(self, pid: str) -> list[dict]:
        return [dict(r) for r in self._q("select * from tm_units where project_id = ? order by id", (pid,))]

    def delete_unit(self, pid: str, unit_id: int) -> None:
        self._w("delete from tm_units where project_id = ? and id = ?", (pid, unit_id))
        self._tm_version[pid] = self._tm_version.get(pid, 0) + 1


def _match(row: sqlite3.Row, score: int) -> dict:
    return {"id": row["id"], "score": score, "source": row["source"], "target": row["target"], "ref": row["ref"],
            "approval": row["approval"]}


_store: ProjectStore | None = None


def get_store() -> ProjectStore:
    global _store
    if _store is None:
        path = get_settings().data_dir / "projects.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        _store = ProjectStore(path)
    return _store


def set_store(store: ProjectStore | None) -> None:
    """Swap the store (tests use an in-memory one)."""
    global _store
    _store = store


# ---- prompt helpers ------------------------------------------------------- #


def project_id(state) -> str | None:
    """The document's project, if it still exists (a deleted project leaves a dangling id in old sessions)."""
    pid = state.get("doc:project_id")
    return pid if pid and get_store().project_name(pid) is not None else None


def termbase_prompt(pid: str | None, sources: list[str], skip: set[str] = frozenset()) -> str:
    """Project terms relevant to these source texts, with forbidden alternatives. `skip`: terms the document's own glossary already covers (more specific, and newer)."""
    if not pid:
        return ""
    lines = []
    for t in get_store().terms_in(pid, sources):
        if t["source"] in skip:
            continue
        if t["target"] and t["status"] == "proposed":  # an accepted AI recommendation, not checked by a person
            lines.append(f"- {t['source']} → {t['target']} (suggested, not confirmed: use it unless this context clearly needs another rendering)")
        elif t["target"]:
            note = f" — {t['note']}" if t["note"] else ""
            lines.append(f"- {t['source']} → {t['target']}{note}")
        elif t["note"]:
            lines.append(f"- {t['source']}: {t['note']}")
        for bad in t["forbidden"]:
            lines.append(f"- NEVER translate {t['source']} as \"{bad}\"" + (f" (use \"{t['target']}\")" if t["target"] else ""))
    return "\n".join(lines)


def instructions_for(state) -> str:
    pid = state.get("doc:project_id")
    project = get_store().project(pid) if pid else None
    return ((project or {}).get("instructions") or "").strip() or "(none)"


def glossary_for(state, sources: list[str], doc_glossary: dict | None = None) -> str:
    """Document glossary (clarifications) + the project termbase entries that occur in `sources`."""
    from .document import state as st  # local: state imports nothing from here, but keep the module graph flat

    doc = doc_glossary if doc_glossary is not None else state.get("doc:glossary") or {}
    base = st.glossary_text({"doc:glossary": doc})
    project = termbase_prompt(project_id(state), sources, skip=set(doc))
    if not project:
        return base
    return project if base == "(empty)" else f"{base}\n{project}"

"use client";

import { Ban, Check, FileText, Loader2, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { projectsApi } from "@/lib/api";
import type { Project, SessionSummary, Term, TmUnit } from "@/lib/types";
import { StatusBadge } from "../shell/StatusBadge";

type Tab = "documents" | "style" | "terms" | "memory" | "settings";

const input = "rounded-md border border-border bg-bg px-2 py-1 text-sm outline-none focus:border-accent";

const splitList = (text: string) =>
  text
    .split(/[;|,]/)
    .map((x) => x.trim())
    .filter(Boolean);

/** New project: name, source language (the target is always English), style guide. */
export function ProjectCreate({ languages, onCreated }: { languages: string[]; onCreated: (p: Project) => void }) {
  const [name, setName] = useState("");
  const [source, setSource] = useState("German");
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      onCreated(await projectsApi.create({ name, source_lang: source, instructions }));
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="w-full max-w-xl">
        <h1 className="text-2xl font-semibold tracking-tight">New project</h1>
        <p className="mt-1 text-sm text-muted">
          A project shares a style guide, a termbase and a translation memory across its documents. Every segment a
          person confirms is added to the memory and reused in the next document.
        </p>
        <label className="mt-6 block text-sm">
          <span className="text-muted">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme substation reports" className={`mt-1 w-full ${input} py-2`} autoFocus />
        </label>
        <label className="mt-3 block text-sm">
          <span className="text-muted">Source language (documents are translated into English)</span>
          <select value={source} onChange={(e) => setSource(e.target.value)} className={`mt-1 w-full ${input} py-2`}>
            {languages.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </label>
        <label className="mt-3 block text-sm">
          <span className="text-muted">Style guide (optional)</span>
          <textarea
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            rows={4}
            placeholder="e.g. British spelling. Formal register. Keep LV position numbers unchanged."
            className={`mt-1 w-full ${input} py-2`}
          />
        </label>
        {error && <p className="mt-3 text-sm text-del-fg">{error}</p>}
        <button
          disabled={!name.trim() || busy}
          onClick={create}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white disabled:opacity-40"
        >
          {busy && <Loader2 size={16} className="animate-spin" />}
          Create project
        </button>
      </div>
    </div>
  );
}

const STATUS_CHIP: Record<Term["status"], string> = {
  approved: "bg-ins text-ins-fg",
  proposed: "bg-warn text-warn-fg",
  note: "bg-sidebar text-muted",
};

function TermRow({ pid, term, onSaved, onDeleted }: { pid: string; term: Term; onSaved: (t: Term) => void; onDeleted: () => void }) {
  const [editing, setEditing] = useState(false);
  const [f, setF] = useState({ source: term.source, target: term.target, forbidden: term.forbidden.join("; "), note: term.note });
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    try {
      // Editing a term is a person's decision: a note with a target, or a proposed term, becomes approved.
      const status = f.target.trim() && term.status !== "approved" ? "approved" : term.status;
      onSaved(await projectsApi.updateTerm(pid, term.id, { ...f, forbidden: splitList(f.forbidden), status }));
      setEditing(false);
    } catch (e) {
      setError(String(e));
    }
  };

  if (editing) {
    return (
      <tr className="align-top">
        {(["source", "target", "forbidden", "note"] as const).map((k) => (
          <td key={k} className="py-1 pr-2">
            <input
              value={f[k]}
              onChange={(e) => setF({ ...f, [k]: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") setEditing(false);
              }}
              className={`w-full ${input}`}
            />
            {k === "source" && error && <div className="mt-1 text-xs text-del-fg">{error}</div>}
          </td>
        ))}
        <td />
        <td className="py-1 whitespace-nowrap">
          <button onClick={save} className="p-1 text-ins-fg" title="Save">
            <Check size={14} />
          </button>
          <button onClick={() => setEditing(false)} className="p-1 text-muted" title="Cancel">
            <X size={14} />
          </button>
        </td>
      </tr>
    );
  }
  return (
    <tr className="group align-top">
      <td className="py-1.5 pr-2 font-medium">{term.source}</td>
      <td className="py-1.5 pr-2">{term.target || <span className="text-muted">—</span>}</td>
      <td className="py-1.5 pr-2">
        {term.forbidden.map((b) => (
          <span key={b} className="mr-1 mb-0.5 inline-flex items-center gap-0.5 rounded bg-del px-1 text-xs text-del-fg">
            <Ban size={10} /> {b}
          </span>
        ))}
      </td>
      <td className="py-1.5 pr-2 text-xs text-muted">{term.note}</td>
      <td className="py-1.5 pr-2 whitespace-nowrap">
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${STATUS_CHIP[term.status]}`}
          title={term.status === "proposed" ? "An AI recommendation accepted without changes: used as a suggestion, not enforced by QA" : undefined}
        >
          {term.status}
        </span>
        {term.status === "proposed" && term.target && (
          <button
            onClick={async () => onSaved(await projectsApi.updateTerm(pid, term.id, { status: "approved" }))}
            className="ml-1.5 inline-flex items-center gap-0.5 rounded border border-border px-1 text-[10px] text-muted hover:border-accent hover:text-fg"
            title="Confirm this translation: it becomes a rule for every document in the project"
          >
            <Check size={10} /> Approve
          </button>
        )}
      </td>
      <td className="py-1.5 whitespace-nowrap opacity-0 group-hover:opacity-100">
        <button onClick={() => setEditing(true)} className="p-1 text-muted hover:text-fg" title="Edit">
          <Pencil size={13} />
        </button>
        <button
          onClick={async () => {
            await projectsApi.deleteTerm(pid, term.id);
            onDeleted();
          }}
          className="p-1 text-muted hover:text-del-fg"
          title="Delete"
        >
          <Trash2 size={13} />
        </button>
      </td>
    </tr>
  );
}

function TermbaseTab({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [terms, setTerms] = useState<Term[]>([]);
  const [filter, setFilter] = useState("");
  const [draft, setDraft] = useState({ source: "", target: "", forbidden: "", note: "" });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    projectsApi.terms(project.id).then(setTerms).catch((e) => setError(String(e)));
  }, [project.id]);
  useEffect(load, [load]);

  const add = async () => {
    if (!draft.source.trim()) return;
    setError(null);
    try {
      await projectsApi.addTerm(project.id, { ...draft, forbidden: splitList(draft.forbidden) });
      setDraft({ source: "", target: "", forbidden: "", note: "" });
      load();
      onChanged();
    } catch (e) {
      setError(String(e));
    }
  };

  const q = filter.trim().toLowerCase();
  const shown = q ? terms.filter((t) => `${t.source} ${t.target} ${t.note} ${t.forbidden.join(" ")}`.toLowerCase().includes(q)) : terms;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs">
          <Search size={12} className="text-muted" />
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter terms…" className="w-44 bg-transparent outline-none" />
        </label>
        <span className="text-xs text-muted">{terms.length} terms</span>
      </div>
      {error && <div className="mb-3 rounded bg-del px-2 py-1 text-xs text-del-fg">{error}</div>}
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted">
          <tr>
            <th className="w-[22%] pb-1 font-medium">{project.source_lang || "Source"}</th>
            <th className="w-[22%] pb-1 font-medium">English</th>
            <th className="w-[20%] pb-1 font-medium">Never use</th>
            <th className="pb-1 font-medium">Note</th>
            <th className="w-16 pb-1 font-medium">Status</th>
            <th className="w-14" />
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          <tr className="align-top">
            {(["source", "target", "forbidden", "note"] as const).map((k) => (
              <td key={k} className="py-1.5 pr-2">
                <input
                  value={draft[k]}
                  onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                  onKeyDown={(e) => e.key === "Enter" && add()}
                  placeholder={{ source: "New term", target: "Translation", forbidden: "a; b", note: "Definition / usage" }[k]}
                  className={`w-full ${input}`}
                />
              </td>
            ))}
            <td />
            <td className="py-1.5">
              <button onClick={add} disabled={!draft.source.trim()} className="rounded-md bg-accent p-1.5 text-white disabled:opacity-40" title="Add term">
                <Plus size={13} />
              </button>
            </td>
          </tr>
          {shown.map((t) => (
            <TermRow
              key={t.id}
              pid={project.id}
              term={t}
              onSaved={(saved) => setTerms((all) => all.map((x) => (x.id === saved.id ? saved : x)))}
              onDeleted={() => {
                load();
                onChanged();
              }}
            />
          ))}
        </tbody>
      </table>
      {terms.length === 0 && (
        <p className="py-6 text-center text-sm text-muted">
          No terms yet. Add them here, or answer the agents&apos; questions — answers are kept here.
        </p>
      )}
    </div>
  );
}

function MemoryTab({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [q, setQ] = useState("");
  const [result, setResult] = useState<{ total: number; units: TmUnit[] }>({ total: 0, units: [] });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (query: string) => projectsApi.tm(project.id, query).then(setResult).catch((e) => setError(String(e))),
    [project.id],
  );
  useEffect(() => {
    const t = setTimeout(() => load(q), 200);
    return () => clearTimeout(t);
  }, [q, load]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs">
          <Search size={12} className="text-muted" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Concordance search…" className="w-56 bg-transparent outline-none" />
        </label>
        <span className="text-xs text-muted">
          {result.total} translation unit{result.total === 1 ? "" : "s"}
          {q ? ` · ${result.units.length} match${result.units.length === 1 ? "" : "es"}` : ""}
        </span>
      </div>
      {error && <div className="mb-3 rounded bg-del px-2 py-1 text-xs text-del-fg">{error}</div>}
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted">
          <tr>
            <th className="w-[40%] pb-1 font-medium">{project.source_lang}</th>
            <th className="w-[40%] pb-1 font-medium">English</th>
            <th className="pb-1 font-medium">From</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {result.units.map((u) => (
            <tr key={u.id} className="group align-top">
              <td className="py-1.5 pr-3 whitespace-pre-line">{u.source}</td>
              <td className="py-1.5 pr-3 whitespace-pre-line">{u.target}</td>
              <td className="py-1.5 pr-2 text-xs text-muted">
                <div className="max-w-40 truncate" title={u.origin}>
                  {u.origin || "—"}
                </div>
                {new Date(u.updated_at * 1000).toLocaleDateString()}
              </td>
              <td className="py-1.5">
                <button
                  onClick={async () => {
                    await projectsApi.deleteUnit(project.id, u.id);
                    load(q);
                    onChanged();
                  }}
                  className="p-1 text-muted opacity-0 group-hover:opacity-100 hover:text-del-fg"
                  title="Delete unit"
                >
                  <Trash2 size={13} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.total === 0 && (
        <p className="py-6 text-center text-sm text-muted">
          The memory is empty. It fills up as you confirm segments (Ctrl+Enter in the Segments tab).
        </p>
      )}
    </div>
  );
}

function StyleGuideTab({ project, onSaved }: { project: Project; onSaved: (p: Project) => void }) {
  const [text, setText] = useState(project.instructions);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  return (
    <div>
      <p className="mb-2 text-sm text-muted">
        Instructions every agent follows for this project&apos;s documents (translator, reviewer and the chat editor): register,
        spelling, units, what to leave untranslated, client preferences.
      </p>
      <textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setState("idle");
        }}
        rows={12}
        className={`w-full ${input} py-2 font-mono text-[13px]`}
        placeholder="e.g. British spelling. Formal register. Keep LV position numbers unchanged."
      />
      <button
        disabled={text === project.instructions || state === "saving"}
        onClick={async () => {
          setState("saving");
          onSaved(await projectsApi.update(project.id, { instructions: text }));
          setState("saved");
        }}
        className="mt-2 rounded-md bg-accent px-3 py-1.5 text-sm text-white disabled:opacity-40"
      >
        {state === "saved" ? "Saved" : "Save style guide"}
      </button>
    </div>
  );
}

function SettingsTab({ project, onSaved }: { project: Project; onSaved: (p: Project) => void }) {
  const [threshold, setThreshold] = useState(String(project.lqa_threshold));
  const [error, setError] = useState<string | null>(null);
  const save = async (fields: Partial<Project>) => {
    setError(null);
    try {
      onSaved(await projectsApi.update(project.id, fields));
    } catch (e) {
      setError(String(e));
    }
  };
  const value = Number(threshold);
  const valid = threshold.trim() !== "" && value >= 0 && value <= 100;
  return (
    <div className="max-w-2xl space-y-6 text-sm">
      <div>
        <div className="font-medium">Languages</div>
        <p className="mt-0.5 text-muted">
          {project.source_lang || "Any language"} → English. Every document in this project is translated into English.
        </p>
      </div>
      <label className="flex items-start gap-3">
        <input
          type="checkbox"
          className="mt-1"
          checked={project.auto_confirm_context}
          onChange={(e) => save({ auto_confirm_context: e.target.checked })}
        />
        <span>
          <span className="font-medium">Auto-confirm 101% matches</span>
          <span className="mt-0.5 block text-xs text-muted">
            A 101% (context) match is a sentence a person already confirmed, after the same previous sentence. When on, it
            starts as <b>confirmed</b>, as in Trados and memoQ; the grid still shows &ldquo;TM 101%&rdquo;. Turn it off for
            clients who want every segment confirmed again in each document. 100% matches always start as draft.
          </span>
        </span>
      </label>
      <div>
        <label className="flex items-center gap-3">
          <span className="font-medium">LQA pass threshold</span>
          <input
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            onBlur={() => valid && value !== project.lqa_threshold && save({ lqa_threshold: value })}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            inputMode="decimal"
            className={`w-20 ${input} ${valid ? "" : "border-del-fg"}`}
          />
        </label>
        <p className="mt-0.5 text-xs text-muted">
          Score = 100 − MQM penalty points per 1000 source words (minor 1, major 5, critical 25). At {valid ? value : "…"}, a document
          passes with up to {valid ? Math.max(0, 100 - value) : "…"} penalty points per 1000 words.
        </p>
      </div>
      {error && <div className="rounded bg-del px-2 py-1 text-xs text-del-fg">{error}</div>}
    </div>
  );
}

export function ProjectView({
  projectId,
  sessions,
  onOpenDocument,
  onTranslate,
  onChanged,
  onDeleted,
}: {
  projectId: string;
  sessions: SessionSummary[];
  onOpenDocument: (id: string) => void;
  onTranslate: (projectId: string) => void;
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [tab, setTab] = useState<Tab>("documents");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    projectsApi
      .get(projectId)
      .then((p) => {
        setProject(p);
        setName(p.name);
      })
      .catch((e) => setError(String(e)));
  }, [projectId]);
  useEffect(refresh, [refresh]);

  const changed = () => {
    refresh();
    onChanged();
  };

  if (error) return <div className="p-8 text-sm text-del-fg">{error}</div>;
  if (!project) return <div className="p-8 text-sm text-muted">Loading…</div>;
  const docs = sessions.filter((s) => s.project_id === project.id);
  const tabs: [Tab, string][] = [
    ["documents", `Documents (${docs.length})`],
    ["style", "Style guide"],
    ["terms", `Termbase (${project.terms})`],
    ["memory", `Translation memory (${project.tm_units})`],
    ["settings", "Settings"],
  ];

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-8 pt-6">
        <div className="flex items-center gap-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={async () => {
              if (name.trim() && name !== project.name) {
                setProject(await projectsApi.update(project.id, { name }));
                onChanged();
              } else setName(project.name);
            }}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            className="min-w-0 flex-1 rounded-md bg-transparent text-xl font-semibold tracking-tight outline-none focus:bg-sidebar"
            aria-label="Project name"
          />
          <button
            onClick={async () => {
              if (!window.confirm(`Delete "${project.name}" with its termbase and translation memory? Its documents are kept.`)) return;
              await projectsApi.remove(project.id);
              onDeleted();
            }}
            className="rounded-md p-1.5 text-muted hover:text-del-fg"
            title="Delete project"
          >
            <Trash2 size={16} />
          </button>
        </div>
        <p className="mt-0.5 text-sm text-muted">
          {project.source_lang} → English · {docs.length} document{docs.length === 1 ? "" : "s"} · {project.terms} term
          {project.terms === 1 ? "" : "s"} · {project.tm_units} TM unit{project.tm_units === 1 ? "" : "s"}
        </p>
        <nav className="mt-4 flex gap-4 text-sm">
          {tabs.map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`border-b-2 pb-2 ${tab === id ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"}`}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>
      <div className="scroll-thin flex-1 overflow-y-auto px-8 py-5">
        {tab === "documents" && (
          <div>
            <button onClick={() => onTranslate(project.id)} className="mb-4 flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white">
              <Plus size={15} /> Translate a document in this project
            </button>
            {docs.length === 0 && <p className="text-sm text-muted">No documents yet.</p>}
            <div className="divide-y divide-border">
              {docs.map((d) => {
                const c = d.counts;
                const done = c ? c.confirmed + c.reviewed : 0;
                return (
                  <button key={d.id} onClick={() => onOpenDocument(d.id)} className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-sidebar/60">
                    <FileText size={16} className="shrink-0 text-muted" />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">{d.filename}</span>
                    {c && c.total > 0 && (
                      <span className="text-xs text-muted">
                        {done}/{c.total} confirmed
                      </span>
                    )}
                    <StatusBadge status={d.status} compact />
                  </button>
                );
              })}
            </div>
          </div>
        )}
        {tab === "style" && <StyleGuideTab project={project} onSaved={(p) => setProject(p)} />}
        {tab === "terms" && <TermbaseTab project={project} onChanged={changed} />}
        {tab === "memory" && <MemoryTab project={project} onChanged={changed} />}
        {tab === "settings" && <SettingsTab project={project} onSaved={(p) => setProject(p)} />}
      </div>
    </div>
  );
}

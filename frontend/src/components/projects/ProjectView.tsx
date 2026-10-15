"use client";

import { Ban, BookMarked, Check, Database, FileText, FolderPlus, Loader2, Pencil, Plus, Search, Settings2, Trash2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/settings/Modal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { projectsApi } from "@/lib/api";
import { rise } from "@/lib/motion";
import type { Project, SessionSummary, Term, TmUnit } from "@/lib/types";
import { docTitle } from "../shell/Sidebar";
import { StatusBadge } from "../shell/StatusBadge";

type Tab = "documents" | "style" | "terms" | "memory" | "settings";

const splitList = (text: string) =>
  text
    .split(/[;|,]/)
    .map((x) => x.trim())
    .filter(Boolean);

function IconAction({ label, onClick, children, danger = false }: { label: string; onClick: () => void; children: React.ReactNode; danger?: boolean }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon-xs" onClick={onClick} aria-label={label} className={danger ? "text-muted-foreground hover:bg-del hover:text-del-fg" : "text-muted-foreground hover:text-foreground"}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/** New project: name, source language (the target is always English), style guide. */
export function ProjectCreate({ languages, onCreated }: { languages: string[]; onCreated: (p: Project) => void }) {
  const [name, setName] = useState("");
  const [source, setSource] = useState(languages.includes("German") ? "German" : (languages[0] ?? "German"));
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      onCreated(await projectsApi.create({ name, source_lang: source, instructions }));
      toast.success("Project created");
    } catch (e) {
      setError(String(e).replace(/^Error: /, ""));
      setBusy(false);
    }
  };

  return (
    <div className="scroll-thin flex h-full justify-center overflow-y-auto p-8">
      <motion.div {...rise} className="my-auto w-full max-w-xl py-6">
        <span className="flex size-11 items-center justify-center rounded-full bg-primary-soft text-primary">
          <FolderPlus size={20} />
        </span>
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">New project</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          A project shares a style guide, a termbase and a translation memory across its documents. Every segment a person confirms
          is added to the memory and reused in the next document.
        </p>
        <div className="mt-6 grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="project-name">Name</Label>
            <Input id="project-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme substation reports" autoFocus className="bg-card" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="project-source">Source language</Label>
            <Select value={source} onValueChange={setSource}>
              <SelectTrigger id="project-source" className="w-full bg-card">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {languages.map((l) => (
                  <SelectItem key={l} value={l}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-xs text-muted-foreground">Documents are translated into English.</span>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="project-style">
              Style guide <span className="font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Textarea
              id="project-style"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={4}
              placeholder="e.g. British spelling. Formal register. Keep LV position numbers unchanged."
              className="bg-card"
            />
          </div>
        </div>
        {error && <p className="mt-4 rounded-lg bg-del px-3 py-2 text-sm text-del-fg">{error}</p>}
        <Button size="lg" disabled={!name.trim() || busy} onClick={create} className="mt-6 w-full">
          {busy && <Loader2 className="animate-spin" />}
          Create project
        </Button>
      </motion.div>
    </div>
  );
}

const STATUS_CHIP: Record<Term["status"], string> = {
  approved: "bg-ins text-ins-fg",
  proposed: "bg-warn text-warn-fg",
  note: "bg-muted text-muted-foreground",
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
      setError(String(e).replace(/^Error: /, ""));
    }
  };

  if (editing) {
    return (
      <tr className="bg-primary-soft/40 align-top">
        {(["source", "target", "forbidden", "note"] as const).map((k) => (
          <td key={k} className="px-2 py-1.5">
            <Input
              value={f[k]}
              onChange={(e) => setF({ ...f, [k]: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") setEditing(false);
              }}
              className="h-8 bg-card text-sm"
              aria-label={k}
            />
            {k === "source" && error && <div className="mt-1 text-xs text-del-fg">{error}</div>}
          </td>
        ))}
        <td />
        <td className="px-2 py-1.5 whitespace-nowrap">
          <IconAction label="Save" onClick={save}>
            <Check className="text-ins-fg" />
          </IconAction>
          <IconAction label="Cancel" onClick={() => setEditing(false)}>
            <X />
          </IconAction>
        </td>
      </tr>
    );
  }
  return (
    <tr className="group align-top transition-colors hover:bg-muted/50">
      <td className="px-2 py-2 font-medium">{term.source}</td>
      <td className="px-2 py-2">{term.target || <span className="text-muted-foreground">—</span>}</td>
      <td className="px-2 py-2">
        {term.forbidden.map((b) => (
          <span key={b} className="mr-1 mb-0.5 inline-flex items-center gap-0.5 rounded-full bg-del px-1.5 text-xs text-del-fg">
            <Ban size={10} /> {b}
          </span>
        ))}
      </td>
      <td className="px-2 py-2 text-xs text-muted-foreground">{term.note}</td>
      <td className="px-2 py-2 whitespace-nowrap">
        <Tooltip>
          <TooltipTrigger asChild>
            <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${STATUS_CHIP[term.status]}`}>{term.status}</span>
          </TooltipTrigger>
          <TooltipContent>
            {term.status === "proposed"
              ? "An AI recommendation accepted without changes: used as a suggestion, not enforced by QA"
              : term.status === "approved"
                ? "A rule for every document in the project (QA checks it)"
                : "An explanation only"}
          </TooltipContent>
        </Tooltip>
        {term.status === "proposed" && term.target && (
          <Button
            variant="outline"
            size="xs"
            onClick={async () => onSaved(await projectsApi.updateTerm(pid, term.id, { status: "approved" }))}
            className="ml-1.5 h-5 px-1.5 text-[10px]"
            title="Confirm this translation: it becomes a rule for every document in the project"
          >
            <Check /> Approve
          </Button>
        )}
      </td>
      <td className="px-2 py-1.5 whitespace-nowrap opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
        <IconAction label="Edit" onClick={() => setEditing(true)}>
          <Pencil />
        </IconAction>
        <IconAction
          label="Delete"
          danger
          onClick={async () => {
            await projectsApi.deleteTerm(pid, term.id);
            onDeleted();
          }}
        >
          <Trash2 />
        </IconAction>
      </td>
    </tr>
  );
}

function SearchBox({ value, onChange, placeholder, label }: { value: string; onChange: (v: string) => void; placeholder: string; label: string }) {
  return (
    <div className="relative">
      <Search size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={label} className="h-8 w-64 bg-card pl-8 text-sm" />
    </div>
  );
}

const TABLE = "w-full text-sm [&_thead_th]:px-2 [&_thead_th]:pb-2 [&_thead_th]:text-left [&_thead_th]:text-xs [&_thead_th]:font-medium [&_thead_th]:text-muted-foreground";

function TermbaseTab({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [terms, setTerms] = useState<Term[] | null>(null);
  const [filter, setFilter] = useState("");
  const [draft, setDraft] = useState({ source: "", target: "", forbidden: "", note: "" });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    projectsApi
      .terms(project.id)
      .then(setTerms)
      .catch((e) => setError(String(e)));
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
      setError(String(e).replace(/^Error: /, ""));
    }
  };

  const q = filter.trim().toLowerCase();
  const all = terms ?? [];
  const shown = q ? all.filter((t) => `${t.source} ${t.target} ${t.note} ${t.forbidden.join(" ")}`.toLowerCase().includes(q)) : all;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <SearchBox value={filter} onChange={setFilter} placeholder="Filter terms…" label="Filter terms" />
        <span className="text-xs text-muted-foreground tabular-nums">{all.length} terms</span>
      </div>
      {error && <div className="mb-3 rounded-lg bg-del px-3 py-2 text-xs text-del-fg">{error}</div>}
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <table className={TABLE}>
          <thead className="border-b border-border bg-muted/40 [&_th]:pt-2">
            <tr>
              <th className="w-[22%]">{project.source_lang || "Source"}</th>
              <th className="w-[22%]">English</th>
              <th className="w-[20%]">Never use</th>
              <th>Note</th>
              <th className="w-20">Status</th>
              <th className="w-16" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            <tr className="align-top">
              {(["source", "target", "forbidden", "note"] as const).map((k) => (
                <td key={k} className="px-2 py-2">
                  <Input
                    value={draft[k]}
                    onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                    onKeyDown={(e) => e.key === "Enter" && add()}
                    placeholder={{ source: "New term", target: "Translation", forbidden: "a; b", note: "Definition / usage" }[k]}
                    aria-label={{ source: "New term", target: "Translation", forbidden: "Never use", note: "Note" }[k]}
                    className="h-8 text-sm"
                  />
                </td>
              ))}
              <td />
              <td className="px-2 py-2">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button size="icon-sm" onClick={add} disabled={!draft.source.trim()} aria-label="Add the term">
                      <Plus />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Add the term</TooltipContent>
                </Tooltip>
              </td>
            </tr>
            {terms === null ? (
              <tr>
                <td colSpan={6} className="p-3">
                  <Skeleton className="h-6 w-full" />
                </td>
              </tr>
            ) : (
              shown.map((t) => (
                <TermRow
                  key={t.id}
                  pid={project.id}
                  term={t}
                  onSaved={(saved) => setTerms((x) => (x ?? []).map((y) => (y.id === saved.id ? saved : y)))}
                  onDeleted={() => {
                    load();
                    onChanged();
                  }}
                />
              ))
            )}
          </tbody>
        </table>
        {terms !== null && all.length === 0 && (
          <p className="border-t border-border py-8 text-center text-sm text-muted-foreground">
            No terms yet. Add them here, or answer the agents&apos; questions: answers are kept here.
          </p>
        )}
      </div>
    </div>
  );
}

function MemoryTab({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [q, setQ] = useState("");
  const [result, setResult] = useState<{ total: number; units: TmUnit[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (query: string) =>
      projectsApi
        .tm(project.id, query)
        .then(setResult)
        .catch((e) => setError(String(e))),
    [project.id],
  );
  useEffect(() => {
    const t = setTimeout(() => load(q), 200);
    return () => clearTimeout(t);
  }, [q, load]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <SearchBox value={q} onChange={setQ} placeholder="Concordance search…" label="Search the translation memory" />
        {result && (
          <span className="text-xs text-muted-foreground tabular-nums">
            {result.total} translation unit{result.total === 1 ? "" : "s"}
            {q ? ` · ${result.units.length} match${result.units.length === 1 ? "" : "es"}` : ""}
          </span>
        )}
      </div>
      {error && <div className="mb-3 rounded-lg bg-del px-3 py-2 text-xs text-del-fg">{error}</div>}
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <table className={TABLE}>
          <thead className="border-b border-border bg-muted/40 [&_th]:pt-2">
            <tr>
              <th className="w-[40%]">{project.source_lang}</th>
              <th className="w-[40%]">English</th>
              <th>From</th>
              <th className="w-10" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {result === null ? (
              <tr>
                <td colSpan={4} className="p-3">
                  <Skeleton className="h-6 w-full" />
                </td>
              </tr>
            ) : (
              result.units.map((u) => (
                <tr key={u.id} className="group align-top transition-colors hover:bg-muted/50">
                  <td className="px-2 py-2 whitespace-pre-line">{u.source}</td>
                  <td className="px-2 py-2 whitespace-pre-line">{u.target}</td>
                  <td className="px-2 py-2 text-xs text-muted-foreground">
                    <div className="max-w-40 truncate" title={u.ref}>
                      {u.ref || "—"}
                    </div>
                    <div className="mt-0.5 flex items-center gap-1">
                      {u.approval === "bulk" && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="rounded-full bg-warn px-1.5 text-[10px] text-warn-fg">bulk</span>
                          </TooltipTrigger>
                          <TooltipContent>Confirmed in bulk: a match from it never confirms a segment by itself</TooltipContent>
                        </Tooltip>
                      )}
                      <span className="tabular-nums">{new Date(u.updated_at * 1000).toLocaleDateString()}</span>
                    </div>
                  </td>
                  <td className="px-2 py-1.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                    <IconAction
                      label="Delete the unit"
                      danger
                      onClick={async () => {
                        await projectsApi.deleteUnit(project.id, u.id);
                        load(q);
                        onChanged();
                      }}
                    >
                      <Trash2 />
                    </IconAction>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {result?.total === 0 && (
          <p className="border-t border-border py-8 text-center text-sm text-muted-foreground">
            The memory is empty. It fills up as you confirm segments (Ctrl+Enter in the Segments tab).
          </p>
        )}
      </div>
    </div>
  );
}

function StyleGuideTab({ project, onSaved }: { project: Project; onSaved: (p: Project) => void }) {
  const [text, setText] = useState(project.instructions);
  const [saving, setSaving] = useState(false);
  return (
    <div className="max-w-3xl">
      <p className="mb-3 text-sm text-muted-foreground">
        Instructions every agent follows for this project&apos;s documents (translator, reviewer and the chat editor): register,
        spelling, units, what to leave untranslated, client preferences.
      </p>
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={14}
        className="bg-card font-mono text-[13px]"
        placeholder="e.g. British spelling. Formal register. Keep LV position numbers unchanged."
        aria-label="Style guide"
      />
      <div className="mt-3 flex items-center gap-3">
        <Button
          disabled={text === project.instructions || saving}
          onClick={async () => {
            setSaving(true);
            try {
              onSaved(await projectsApi.update(project.id, { instructions: text }));
              toast.success("Style guide saved");
            } finally {
              setSaving(false);
            }
          }}
        >
          {saving && <Loader2 className="animate-spin" />} Save style guide
        </Button>
        {text !== project.instructions && <span className="text-xs text-muted-foreground">Unsaved changes</span>}
      </div>
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
      setError(String(e).replace(/^Error: /, ""));
    }
  };
  const value = Number(threshold);
  const valid = threshold.trim() !== "" && value >= 0 && value <= 100;
  return (
    <div className="max-w-2xl divide-y divide-border rounded-xl border border-border bg-card text-sm">
      <div className="p-4">
        <div className="font-medium">Languages</div>
        <p className="mt-0.5 text-muted-foreground">
          {project.source_lang || "Any language"} → English. Every document in this project is translated into English.
        </p>
      </div>
      <label className="flex items-start gap-3 p-4">
        <Switch checked={project.auto_confirm_context} onCheckedChange={(on) => save({ auto_confirm_context: on })} className="mt-0.5" />
        <span>
          <span className="font-medium">Auto-confirm 101% matches</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">
            A 101% (context) match is a sentence a person already confirmed, after the same previous sentence. When on, it starts as{" "}
            <b>confirmed</b>, as in Trados and memoQ; the grid still shows &ldquo;TM 101%&rdquo;. Turn it off for clients who want every
            segment confirmed again in each document. 100% matches always start as draft.
          </span>
        </span>
      </label>
      <div className="p-4">
        <div className="flex items-center gap-3">
          <Label htmlFor="lqa-threshold" className="font-medium">
            LQA pass threshold
          </Label>
          <Input
            id="lqa-threshold"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            onBlur={() => valid && value !== project.lqa_threshold && save({ lqa_threshold: value })}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            inputMode="decimal"
            aria-invalid={!valid}
            className="h-8 w-20 tabular-nums"
          />
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          Score = 100 − MQM penalty points per 1000 source words (minor 1, major 5, critical 25). At {valid ? value : "…"}, a document
          passes with up to {valid ? Math.max(0, 100 - value) : "…"} penalty points per 1000 words.
        </p>
      </div>
      {error && <div className="p-4 text-xs text-del-fg">{error}</div>}
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
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState(false);

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
  if (!project)
    return (
      <div className="space-y-3 px-8 pt-8">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-4 w-96" />
        <Skeleton className="mt-6 h-40 w-full" />
      </div>
    );
  const docs = sessions.filter((s) => s.project_id === project.id).sort((a, b) => b.updated_at - a.updated_at);

  return (
    <motion.div {...rise} className="flex h-full flex-col">
      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="flex min-h-0 flex-1 flex-col gap-0">
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
              className="-mx-1.5 min-w-0 flex-1 rounded-md bg-transparent px-1.5 text-xl font-semibold tracking-tight outline-none hover:bg-muted/60 focus:bg-muted focus-visible:ring-[3px] focus-visible:ring-ring/50"
              aria-label="Project name"
            />
            <Button onClick={() => onTranslate(project.id)}>
              <Plus /> Translate a document
            </Button>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" onClick={() => setDeleting(true)} aria-label="Delete the project" className="text-muted-foreground hover:bg-del hover:text-del-fg">
                  <Trash2 />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Delete the project</TooltipContent>
            </Tooltip>
          </div>
          <p className="mt-0.5 text-sm text-muted-foreground tabular-nums">
            {project.source_lang} → English · {docs.length} document{docs.length === 1 ? "" : "s"} · {project.terms} term
            {project.terms === 1 ? "" : "s"} · {project.tm_units} TM unit{project.tm_units === 1 ? "" : "s"}
          </p>
          <TabsList variant="line" className="mt-4 -mb-px h-10 gap-4 p-0">
            <TabsTrigger value="documents" className="px-0">
              <FileText /> Documents <span className="text-muted-foreground tabular-nums">{docs.length}</span>
            </TabsTrigger>
            <TabsTrigger value="style" className="px-0">
              <Pencil /> Style guide
            </TabsTrigger>
            <TabsTrigger value="terms" className="px-0">
              <BookMarked /> Termbase <span className="text-muted-foreground tabular-nums">{project.terms}</span>
            </TabsTrigger>
            <TabsTrigger value="memory" className="px-0">
              <Database /> Translation memory <span className="text-muted-foreground tabular-nums">{project.tm_units}</span>
            </TabsTrigger>
            <TabsTrigger value="settings" className="px-0">
              <Settings2 /> Settings
            </TabsTrigger>
          </TabsList>
        </header>
        <div className="scroll-thin flex-1 overflow-y-auto px-8 py-6">
          <TabsContent value="documents">
            {docs.length === 0 ? (
              <div className="flex flex-col items-center rounded-xl border border-dashed border-border py-12 text-center">
                <FileText className="text-muted-foreground" />
                <p className="mt-2 text-sm font-medium">No documents yet</p>
                <p className="mt-1 text-xs text-muted-foreground">Translate one: it uses this project&apos;s style guide, termbase and memory.</p>
                <Button variant="outline" className="mt-4" onClick={() => onTranslate(project.id)}>
                  <Plus /> Translate a document
                </Button>
              </div>
            ) : (
              <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
                <AnimatePresence initial={false}>
                  {docs.map((d) => {
                    const c = d.counts;
                    const done = c ? c.confirmed + c.reviewed : 0;
                    const title = docTitle(d);
                    return (
                      <motion.button
                        key={d.id}
                        {...rise}
                        onClick={() => onOpenDocument(d.id)}
                        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
                      >
                        {d.running ? <Loader2 size={16} className="shrink-0 animate-spin text-primary" /> : <FileText size={16} className="shrink-0 text-muted-foreground" />}
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">{title}</span>
                          {title !== d.filename && <span className="block truncate text-xs text-muted-foreground">{d.filename}</span>}
                        </span>
                        {c && c.total > 0 && (
                          <span className="flex items-center gap-2 text-xs text-muted-foreground tabular-nums">
                            <span className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                              <span className="block h-full rounded-full bg-primary/70" style={{ width: `${Math.round((done / c.total) * 100)}%` }} />
                            </span>
                            {done}/{c.total} confirmed
                          </span>
                        )}
                        {d.open_questions > 0 && (
                          <Badge variant="secondary" className="bg-warn text-warn-fg">
                            {d.open_questions} question{d.open_questions === 1 ? "" : "s"}
                          </Badge>
                        )}
                        <StatusBadge status={d.status} compact />
                      </motion.button>
                    );
                  })}
                </AnimatePresence>
              </div>
            )}
          </TabsContent>
          <TabsContent value="style">
            <StyleGuideTab project={project} onSaved={(p) => setProject(p)} />
          </TabsContent>
          <TabsContent value="terms">
            <TermbaseTab project={project} onChanged={changed} />
          </TabsContent>
          <TabsContent value="memory">
            <MemoryTab project={project} onChanged={changed} />
          </TabsContent>
          <TabsContent value="settings">
            <SettingsTab project={project} onSaved={(p) => setProject(p)} />
          </TabsContent>
        </div>
      </Tabs>

      <Modal open={deleting} onClose={() => setDeleting(false)} title={`Delete “${project.name}”?`} width={460}>
        <p className="text-sm text-muted-foreground">
          Its termbase and translation memory are deleted. Its documents are kept, outside any project.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setDeleting(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await projectsApi.remove(project.id);
                setDeleting(false);
                toast.success("Project deleted");
                onDeleted();
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy && <Loader2 className="animate-spin" />} Delete project
          </Button>
        </div>
      </Modal>
    </motion.div>
  );
}

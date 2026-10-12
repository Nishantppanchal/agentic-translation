"use client";

import { ChevronDown, ChevronRight, FileText, Folder, FolderOpen, Loader2, MessageCircleQuestion, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { Project, SessionSummary } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

function DocumentRow({
  s,
  active,
  nested,
  onSelect,
  onDelete,
}: {
  s: SessionSummary;
  active: boolean;
  nested: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(s.id)}
      onKeyDown={(e) => e.key === "Enter" && onSelect(s.id)}
      className={`group mb-0.5 flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 text-sm ${
        active ? "bg-panel shadow-sm" : "hover:bg-panel/60"
      } ${nested ? "ml-4" : ""}`}
    >
      {s.running ? (
        <Loader2 size={15} className="mt-0.5 shrink-0 animate-spin text-accent" />
      ) : (
        <FileText size={15} className="mt-0.5 shrink-0 text-muted" />
      )}
      <div className="min-w-0 flex-1">
        <div className="truncate" title={s.filename}>
          {s.filename}
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
          {!nested && <span className="truncate">{s.source_lang}</span>}
          <StatusBadge status={s.status} compact />
          {s.open_questions > 0 && (
            <span className="flex items-center gap-0.5 text-warn-fg" title="Open questions">
              <MessageCircleQuestion size={12} />
              {s.open_questions}
            </span>
          )}
        </div>
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete(s.id);
        }}
        className="invisible rounded p-1 text-muted hover:text-del-fg group-hover:visible"
        title="Delete"
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}

/** Projects with their documents underneath (most recent first), then documents outside any project. */
export function Sidebar({
  sessions,
  projects,
  activeId,
  activeProject,
  onSelect,
  onSelectProject,
  onNewProject,
  onNew,
  onDelete,
}: {
  sessions: SessionSummary[];
  projects: Project[];
  activeId: string | null;
  activeProject: string | null;
  onSelect: (id: string) => void;
  onSelectProject: (id: string) => void;
  onNewProject: () => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const known = new Set(projects.map((p) => p.id));
  const loose = sessions.filter((s) => !s.project_id || !known.has(s.project_id));
  const toggle = (id: string) =>
    setCollapsed((c) => {
      const next = new Set(c);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-sidebar">
      <div className="flex items-center justify-between px-4 pt-4 pb-3">
        <span className="text-sm font-semibold tracking-tight">Agentic Translator</span>
        <span className="text-[10px] text-muted">→ English</span>
      </div>
      <div className="px-3">
        <button
          onClick={onNew}
          className="flex w-full items-center gap-2 rounded-lg border border-border bg-panel px-3 py-2 text-sm font-medium hover:border-accent"
        >
          <Plus size={16} /> New translation
        </button>
      </div>
      <nav className="scroll-thin mt-4 flex-1 overflow-y-auto px-2 pb-4">
        <div className="flex items-center justify-between px-2 text-xs font-medium tracking-wide text-muted uppercase">
          Projects
          <button onClick={onNewProject} className="rounded p-0.5 hover:text-fg" title="New project">
            <Plus size={14} />
          </button>
        </div>
        {projects.length === 0 && (
          <button onClick={onNewProject} className="px-2 py-1.5 text-left text-xs text-muted hover:text-fg">
            Create a project to share a style guide, termbase and translation memory across documents.
          </button>
        )}
        {projects.map((p) => {
          const docs = sessions.filter((s) => s.project_id === p.id);
          const open = !collapsed.has(p.id) || docs.some((d) => d.id === activeId);
          return (
            <div key={p.id} className="mt-1">
              <div
                className={`flex items-start gap-1 rounded-lg px-1 py-1.5 text-sm ${p.id === activeProject ? "bg-panel shadow-sm" : "hover:bg-panel/60"}`}
              >
                <button
                  onClick={() => toggle(p.id)}
                  className="mt-0.5 rounded p-0.5 text-muted hover:text-fg"
                  title={open ? "Hide documents" : "Show documents"}
                >
                  {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                </button>
                <button onClick={() => onSelectProject(p.id)} className="flex min-w-0 flex-1 items-start gap-1.5 text-left" title="Open the project">
                  {p.id === activeProject ? (
                    <FolderOpen size={15} className="mt-0.5 shrink-0 text-accent" />
                  ) : (
                    <Folder size={15} className="mt-0.5 shrink-0 text-muted" />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium" title={p.name}>
                      {p.name}
                    </span>
                    <span className="block truncate text-xs text-muted">
                      {p.source_lang} · {p.terms} terms · {p.tm_units} TM
                    </span>
                  </span>
                </button>
              </div>
              {open &&
                docs.map((s) => (
                  <DocumentRow key={s.id} s={s} active={s.id === activeId} nested onSelect={onSelect} onDelete={onDelete} />
                ))}
            </div>
          );
        })}
        {loose.length > 0 && (
          <>
            <div className="mt-4 px-2 text-xs font-medium tracking-wide text-muted uppercase">
              {projects.length ? "Other documents" : "Documents"}
            </div>
            {loose.map((s) => (
              <DocumentRow key={s.id} s={s} active={s.id === activeId} nested={false} onSelect={onSelect} onDelete={onDelete} />
            ))}
          </>
        )}
        {sessions.length === 0 && <p className="px-2 py-3 text-sm text-muted">No documents yet.</p>}
      </nav>
    </aside>
  );
}

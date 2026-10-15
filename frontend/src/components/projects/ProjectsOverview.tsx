"use client";

import { BookMarked, Database, FileText, FolderKanban, FolderPlus, Languages, Loader2 } from "lucide-react";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { rise, stagger } from "@/lib/motion";
import type { Project, SessionSummary } from "@/lib/types";
import { docTitle } from "../shell/Sidebar";

function Stat({ icon: Icon, value, label }: { icon: typeof FileText; value: number; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <Icon size={13} />
      <span className="font-medium text-foreground tabular-nums">{value}</span> {label}
    </span>
  );
}

/** Every project as a card (its language, documents, termbase and translation memory); a card opens the project. */
export function ProjectsOverview({
  projects,
  sessions,
  onOpenProject,
  onNewProject,
}: {
  projects: Project[];
  sessions: SessionSummary[];
  onOpenProject: (id: string) => void;
  onNewProject: () => void;
}) {
  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-8 py-8">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
              <FolderKanban className="text-primary" size={22} /> Projects
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              A project shares a style guide, a termbase and a translation memory across its documents. Every segment a person
              confirms is reused in the next document.
            </p>
          </div>
          <Button onClick={onNewProject}>
            <FolderPlus /> New project
          </Button>
        </div>

        {projects.length === 0 ? (
          <motion.div {...rise} className="mt-8 flex flex-col items-center rounded-xl border border-dashed border-border py-16 text-center">
            <span className="flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary">
              <FolderKanban size={22} />
            </span>
            <p className="mt-3 text-sm font-medium">No projects yet</p>
            <p className="mt-1 max-w-sm text-xs text-muted-foreground">
              Create one for a client or a series of documents, so their terms and confirmed translations carry over.
            </p>
            <Button variant="outline" className="mt-4" onClick={onNewProject}>
              <FolderPlus /> New project
            </Button>
          </motion.div>
        ) : (
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p, i) => {
              const docs = sessions.filter((s) => s.project_id === p.id).sort((a, b) => b.updated_at - a.updated_at);
              const running = docs.some((d) => d.running);
              return (
                <motion.button
                  key={p.id}
                  {...rise}
                  transition={{ ...rise.transition, delay: i * stagger }}
                  whileHover={{ y: -2 }}
                  onClick={() => onOpenProject(p.id)}
                  className="group flex flex-col rounded-xl border border-border bg-card p-4 text-left shadow-xs transition-[border-color,box-shadow] outline-none hover:border-primary/40 hover:shadow-sm focus-visible:ring-[3px] focus-visible:ring-ring/50"
                >
                  <div className="flex items-start gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm font-semibold group-hover:text-primary">{p.name}</span>
                    {running && <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin text-primary" aria-label="A document is running" />}
                  </div>
                  <span className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Languages size={13} /> {p.source_lang || "Any language"} → English
                  </span>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
                    <Stat icon={FileText} value={p.documents} label={p.documents === 1 ? "document" : "documents"} />
                    <Stat icon={BookMarked} value={p.terms} label={p.terms === 1 ? "term" : "terms"} />
                    <Stat icon={Database} value={p.tm_units} label="TM units" />
                  </div>
                  {docs.length > 0 && (
                    <div className="mt-3 space-y-1 border-t border-border pt-3">
                      {docs.slice(0, 2).map((d) => (
                        <span key={d.id} className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
                          <FileText size={12} className="shrink-0" />
                          <span className="truncate">{docTitle(d)}</span>
                        </span>
                      ))}
                      {docs.length > 2 && <span className="block text-[11px] text-muted-foreground">and {docs.length - 2} more</span>}
                    </div>
                  )}
                </motion.button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

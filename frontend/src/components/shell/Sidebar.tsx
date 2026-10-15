"use client";

import { FileText, Folder, FolderKanban, Loader2, MessageCircleQuestion, PanelLeftClose, PanelLeftOpen, Plus, Search, Settings, Trash2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { cn } from "cn";
import { useEffect, useRef, useState } from "react";
import { ThemeControl } from "@/components/settings/ThemeControl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { rise } from "@/lib/motion";
import {
  clampSidebarWidth,
  getSidebarCollapsed,
  previewSidebarWidth,
  setSidebarCollapsed,
  setSidebarWidth,
  SIDEBAR_DEFAULT,
  SIDEBAR_MAX,
  SIDEBAR_MIN,
  useSidebarWidth,
} from "@/lib/prefs";
import type { Project, SessionSummary } from "@/lib/types";
import { Logo } from "./Logo";
import { StatusBadge } from "./StatusBadge";

const SHORTCUT = "⌘/Ctrl+\\";
const ALL = "all";
const FILTER_KEY = "sidebarProject"; // the project filter, remembered per browser

/** Collapse or expand; after a click, focus moves to the toggle that is now visible. */
export function toggleSidebar(fromClick: boolean) {
  const collapse = !getSidebarCollapsed();
  setSidebarCollapsed(collapse);
  if (fromClick) requestAnimationFrame(() => document.getElementById(collapse ? "sidebar-expand" : "sidebar-collapse")?.focus());
}

/** What a document is called: the English title the analysis gave it, else its file name. */
export const docTitle = (s: SessionSummary) => s.title?.trim() || s.filename;

const norm = (s: string) => s.toLocaleLowerCase();
/** A document matches the search by its title, file name, project or language. */
export const docMatches = (s: SessionSummary, q: string) =>
  !q || [s.title, s.filename, s.project_name, s.source_lang].some((x) => x && norm(x).includes(q));

/** Today / Yesterday / Earlier, by when the document last changed. */
function whenGroup(updatedAt: number): string {
  const day = new Date();
  day.setHours(0, 0, 0, 0);
  const t = updatedAt * 1000;
  if (t >= day.getTime()) return "Today";
  if (t >= day.getTime() - 86_400_000) return "Yesterday";
  return "Earlier";
}

function IconButton({
  label,
  onClick,
  children,
  side = "top",
  id,
  className,
  ...aria
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  side?: "top" | "right" | "bottom";
  id?: string;
  className?: string;
  "aria-controls"?: string;
  "aria-expanded"?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button id={id} variant="ghost" size="icon-sm" onClick={onClick} aria-label={label} className={cn("text-muted-foreground hover:text-foreground", className)} {...aria}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent side={side}>{label}</TooltipContent>
    </Tooltip>
  );
}

function DocumentRow({
  s,
  active,
  onSelect,
  onDelete,
  onFilterProject,
}: {
  s: SessionSummary;
  active: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onFilterProject: (id: string) => void;
}) {
  const title = docTitle(s);
  const named = title !== s.filename;
  return (
    <motion.div
      {...rise}
      layout="position"
      role="button"
      tabIndex={0}
      aria-current={active ? "page" : undefined}
      onClick={() => onSelect(s.id)}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onSelect(s.id);
        }
      }}
      title={named ? s.filename : undefined}
      className={cn(
        "group relative mb-0.5 flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 text-sm outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50",
        active ? "bg-card shadow-xs ring-1 ring-border" : "hover:bg-sidebar-accent",
      )}
    >
      {active && <span className="absolute top-2 bottom-2 left-0 w-0.5 rounded-full bg-primary" aria-hidden />}
      {s.running ? (
        <Loader2 size={15} className="mt-0.5 shrink-0 animate-spin text-primary" aria-label="Running" />
      ) : (
        <FileText size={15} className="mt-0.5 shrink-0 text-muted-foreground" />
      )}
      <div className="min-w-0 flex-1">
        <div className={cn("truncate leading-snug", active && "font-medium")}>{title}</div>
        {named && <div className="truncate text-[11px] text-muted-foreground">{s.filename}</div>}
        <div className="mt-1 flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground">
          <StatusBadge status={s.status} compact />
          {s.open_questions > 0 && (
            <span className="flex items-center gap-0.5 text-warn-fg" title={`${s.open_questions} open question${s.open_questions === 1 ? "" : "s"}`}>
              <MessageCircleQuestion size={12} />
              {s.open_questions}
            </span>
          )}
          {s.project_id && s.project_name ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onFilterProject(s.project_id!);
              }}
              className="flex min-w-0 items-center gap-0.5 truncate rounded-full bg-muted px-1.5 py-px hover:bg-primary-soft hover:text-primary"
              title={`Show only “${s.project_name}”`}
            >
              <Folder size={10} className="shrink-0" />
              <span className="truncate">{s.project_name}</span>
            </button>
          ) : (
            <span className="truncate">{s.source_lang}</span>
          )}
        </div>
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(s.id);
            }}
            className="invisible shrink-0 rounded-md p-1 text-muted-foreground group-focus-within:visible group-hover:visible hover:bg-del hover:text-del-fg focus-visible:visible"
            aria-label={`Delete ${title}`}
          >
            <Trash2 size={13} />
          </button>
        </TooltipTrigger>
        <TooltipContent side="right">Delete</TooltipContent>
      </Tooltip>
    </motion.div>
  );
}

/** The expanded sidebar's right edge: drag to resize (208–420 px), double-click for the default, or focus it and use
 * ←/→ (16 px), Home / End. The width is a CSS variable, so the main area reflows without React re-rendering. */
function ResizeHandle({ onResizing }: { onResizing: (on: boolean) => void }) {
  const width = useSidebarWidth();
  const drag = useRef<{ x: number; w: number; now: number } | null>(null);
  const end = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    setSidebarWidth(drag.current.now);
    drag.current = null;
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
    onResizing(false);
  };
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the sidebar"
      aria-valuenow={width}
      aria-valuemin={SIDEBAR_MIN}
      aria-valuemax={SIDEBAR_MAX}
      tabIndex={0}
      title="Drag to resize · double-click to reset"
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        const w = e.currentTarget.parentElement?.getBoundingClientRect().width ?? width;
        drag.current = { x: e.clientX, w, now: w };
        document.body.style.userSelect = "none";
        document.body.style.cursor = "col-resize";
        onResizing(true);
      }}
      onPointerMove={(e) => {
        if (!drag.current) return;
        drag.current.now = clampSidebarWidth(drag.current.w + e.clientX - drag.current.x);
        previewSidebarWidth(drag.current.now);
      }}
      onPointerUp={end}
      onPointerCancel={end}
      onDoubleClick={() => setSidebarWidth(SIDEBAR_DEFAULT)}
      onKeyDown={(e) => {
        const next =
          e.key === "ArrowLeft" ? width - 16 : e.key === "ArrowRight" ? width + 16 : e.key === "Home" ? SIDEBAR_MIN : e.key === "End" ? SIDEBAR_MAX : null;
        if (next === null) return;
        e.preventDefault();
        setSidebarWidth(next);
      }}
      className="group/resize absolute top-0 -right-[3px] z-20 h-full w-1.5 cursor-col-resize outline-none sidebar-collapsed:hidden"
    >
      <span className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 bg-primary/40 opacity-0 transition-opacity group-hover/resize:opacity-100 group-focus-visible/resize:opacity-100 group-active/resize:opacity-100" />
    </div>
  );
}

function GroupLabel({ children }: { children: React.ReactNode }) {
  return <div className="px-2 pt-3 pb-1 text-[10px] font-semibold tracking-wider text-muted-foreground/80 uppercase">{children}</div>;
}

/** New translation, a search and a project filter, Projects, then every document by recency (Today / Yesterday /
 * Earlier); Settings and the theme below. Collapses to an icon rail (⌘/Ctrl+\); the pre-paint script sets the
 * collapsed state, so the first paint is right. */
export function Sidebar({
  sessions,
  projects,
  activeId,
  projectsActive,
  onSelect,
  onOpenProjects,
  onNew,
  onDelete,
  onOpenSettings,
  onOpenPalette,
}: {
  sessions: SessionSummary[];
  projects: Project[];
  activeId: string | null;
  projectsActive: boolean; // the Projects page or a project is open
  onSelect: (id: string) => void;
  onOpenProjects: () => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onOpenSettings: () => void;
  onOpenPalette: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.code === "Backslash" && !e.isComposing) {
        e.preventDefault();
        toggleSidebar(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const runningCount = sessions.filter((s) => s.running).length;
  const [resizing, setResizing] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const [filter, setFilterState] = useState<string>(() => {
    try {
      return localStorage.getItem(FILTER_KEY) || ALL;
    } catch {
      return ALL;
    }
  });
  const setFilter = (id: string) => {
    setFilterState(id);
    try {
      if (id === ALL) localStorage.removeItem(FILTER_KEY);
      else localStorage.setItem(FILTER_KEY, id);
    } catch {
      // storage unavailable: the filter just isn't remembered
    }
  };
  // A remembered project that has since been deleted shows everything.
  const project = projects.find((p) => p.id === filter) ?? null;
  const active = project ? project.id : ALL;

  const q = norm(query.trim());
  const docs = [...sessions].filter((s) => docMatches(s, q) && (active === ALL || s.project_id === active)).sort((a, b) => b.updated_at - a.updated_at);
  const groups = new Map<string, SessionSummary[]>();
  for (const s of docs) groups.set(whenGroup(s.updated_at), [...(groups.get(whenGroup(s.updated_at)) ?? []), s]);
  const byWhen = [...groups];

  return (
    <aside
      id="sidebar"
      aria-label="Documents"
      data-resizing={resizing || undefined}
      // The width is --sidebar-w (set before paint, dragged by the edge); collapse and expand animate, a drag doesn't.
      className="relative flex h-full w-[var(--sidebar-w,16rem)] shrink-0 flex-col border-r border-sidebar-border bg-sidebar motion-safe:transition-[width] motion-safe:duration-200 motion-safe:ease-out data-[resizing]:transition-none sidebar-collapsed:w-12"
    >
      <ResizeHandle onResizing={setResizing} />
      {/* Collapsed: an icon rail. Both bodies are rendered; CSS picks one, so the first paint is already right. */}
      <div className="hidden h-full flex-col items-center gap-1 py-3 sidebar-collapsed:flex">
        <span className="mb-2 p-1">
          <Logo size={24} />
        </span>
        <IconButton id="sidebar-expand" label={`Show sidebar (${SHORTCUT})`} onClick={() => toggleSidebar(true)} side="right" aria-controls="sidebar" aria-expanded={false}>
          <PanelLeftOpen />
        </IconButton>
        <IconButton label="New translation" onClick={onNew} side="right">
          <Plus />
        </IconButton>
        <IconButton label="Search (⌘K)" onClick={onOpenPalette} side="right">
          <Search />
        </IconButton>
        <IconButton label="Projects" onClick={onOpenProjects} side="right" className={projectsActive ? "bg-card text-primary" : ""}>
          <FolderKanban />
        </IconButton>
        {runningCount > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="p-2 text-primary" aria-label={`${runningCount} running`}>
                <Loader2 size={16} className="animate-spin" />
              </span>
            </TooltipTrigger>
            <TooltipContent side="right">
              {runningCount} document{runningCount > 1 ? "s" : ""} running
            </TooltipContent>
          </Tooltip>
        )}
        <div className="flex-1" />
        <ThemeControl compact side="right" />
        <IconButton label="Settings" onClick={onOpenSettings} side="right">
          <Settings />
        </IconButton>
      </div>

      <div className="flex min-h-0 flex-1 flex-col sidebar-collapsed:hidden">
        <div className="relative flex items-center gap-3 pt-5 pb-3 pr-10 pl-4">
          <Logo size={34} float />
          {/* lifted by the logo's shadow gap, so the word lines up with the orb's middle */}
          <span className="mb-1 text-[13px] font-semibold tracking-[0.32em] text-foreground/75">TRANSLATE</span>
          <IconButton
            id="sidebar-collapse"
            label={`Hide sidebar (${SHORTCUT})`}
            onClick={() => toggleSidebar(true)}
            side="right"
            aria-controls="sidebar"
            aria-expanded
            className="absolute top-1/2 right-2 -translate-y-1/2"
          >
            <PanelLeftClose />
          </IconButton>
        </div>

        <div className="space-y-2 px-3">
          <Button variant="outline" onClick={onNew} className="w-full justify-start gap-2 bg-card shadow-xs">
            <Plus /> New translation
          </Button>
          <div className="flex gap-1.5">
            <div className="relative min-w-0 flex-1">
              <Search size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    setQuery("");
                    searchRef.current?.blur();
                  }
                }}
                placeholder="Search"
                aria-label="Search documents (⌘K for everything)"
                className="h-8 bg-card pr-7 pl-8 text-sm"
              />
              {query && (
                <button
                  onClick={() => setQuery("")}
                  className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
                  aria-label="Clear the search"
                >
                  <X size={13} />
                </button>
              )}
            </div>
            <Select value={active} onValueChange={setFilter}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <SelectTrigger
                    size="sm"
                    aria-label="Show the documents of one project"
                    className={cn("w-[92px] shrink-0 gap-1 bg-card px-2 text-xs", project && "border-primary/40 text-primary")}
                  >
                    <Folder size={13} className={project ? "text-primary" : ""} />
                    <span className="min-w-0 truncate">{project ? project.name : "All"}</span>
                  </SelectTrigger>
                </TooltipTrigger>
                <TooltipContent>{project ? `Only “${project.name}”` : "Filter by project"}</TooltipContent>
              </Tooltip>
              <SelectContent position="popper" align="end" className="min-w-48">
                <SelectItem value={ALL}>All projects</SelectItem>
                {projects.length > 0 && <SelectSeparator />}
                {projects.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <button
            onClick={onOpenProjects}
            aria-current={projectsActive ? "page" : undefined}
            className={cn(
              "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors",
              projectsActive ? "bg-card font-medium shadow-xs ring-1 ring-border" : "text-muted-foreground hover:bg-sidebar-accent hover:text-foreground",
            )}
          >
            <FolderKanban size={15} className={projectsActive ? "text-primary" : ""} />
            <span className="flex-1 text-left">Projects</span>
            <span className="rounded-full bg-muted px-1.5 text-[11px] text-muted-foreground tabular-nums">{projects.length}</span>
          </button>
        </div>

        <nav className="scroll-thin mt-1 flex-1 overflow-y-auto px-2 pb-4" aria-label="Documents">
          {project && (
            <div className="mx-1 mt-2 flex items-center gap-1.5 rounded-md bg-primary-soft px-2 py-1 text-[11px] text-primary">
              <Folder size={11} />
              <span className="min-w-0 flex-1 truncate">{project.name}</span>
              <button onClick={() => setFilter(ALL)} className="rounded p-0.5 hover:bg-primary/10" aria-label="Show all projects">
                <X size={11} />
              </button>
            </div>
          )}
          <AnimatePresence initial={false}>
            {byWhen.map(([label, list]) => (
              <div key={label}>
                <GroupLabel>{label}</GroupLabel>
                {list.map((s) => (
                  <DocumentRow key={s.id} s={s} active={s.id === activeId} onSelect={onSelect} onDelete={onDelete} onFilterProject={setFilter} />
                ))}
              </div>
            ))}
          </AnimatePresence>
          {docs.length === 0 && (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">
              {q || project ? "No document matches." : "No documents yet. Start with New translation."}
            </p>
          )}
        </nav>

        <div className="flex items-center justify-between border-t border-sidebar-border px-2 py-2">
          <Button variant="ghost" size="sm" onClick={onOpenSettings} className="gap-2 text-muted-foreground hover:text-foreground">
            <Settings /> Settings
          </Button>
          <ThemeControl compact />
        </div>
      </div>
    </aside>
  );
}

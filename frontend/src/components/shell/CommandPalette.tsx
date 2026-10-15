"use client";

import { Brain, FileText, Folder, FolderPlus, Loader2, MoveHorizontal, PanelLeft, Plus, Settings } from "lucide-react";
import { useEffect } from "react";
import { THEME_OPTIONS } from "@/components/settings/ThemeControl";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import { setSidebarWidth, setTheme, SIDEBAR_DEFAULT } from "@/lib/prefs";
import type { Project, SessionSummary } from "@/lib/types";
import { docTitle, toggleSidebar } from "./Sidebar";
import { StatusBadge } from "./StatusBadge";

/** ⌘K: jump to a document or a project, or run an action (new translation, settings, theme, sidebar). */
export function CommandPalette({
  open,
  onOpenChange,
  sessions,
  projects,
  onSelectDocument,
  onSelectProject,
  onNew,
  onNewProject,
  onOpenSettings,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sessions: SessionSummary[];
  projects: Project[];
  onSelectDocument: (id: string) => void;
  onSelectProject: (id: string) => void;
  onNew: () => void;
  onNewProject: () => void;
  onOpenSettings: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k" && !e.isComposing) {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  const run = (action: () => void) => () => {
    onOpenChange(false);
    action();
  };
  const recent = [...sessions].sort((a, b) => b.updated_at - a.updated_at);

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Search" description="Find a document or a project, or run an action" className="sm:max-w-xl">
      <CommandInput placeholder="Search documents, projects and actions…" />
      <CommandList className="max-h-[420px]">
        <CommandEmpty>Nothing matches.</CommandEmpty>
        <CommandGroup heading="Actions">
          <CommandItem onSelect={run(onNew)} value="New translation upload document">
            <Plus /> New translation
          </CommandItem>
          <CommandItem onSelect={run(onNewProject)} value="New project">
            <FolderPlus /> New project
          </CommandItem>
          <CommandItem onSelect={run(onOpenSettings)} value="Settings dictionary appearance">
            <Settings /> Settings
          </CommandItem>
          <CommandItem onSelect={run(onOpenSettings)} value="Models reasoning levels thinking effort">
            <Brain /> Models and reasoning levels
          </CommandItem>
          <CommandItem onSelect={run(() => toggleSidebar(false))} value="Toggle sidebar show hide">
            <PanelLeft /> Show or hide the sidebar
            <CommandShortcut>⌘\</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={run(() => setSidebarWidth(SIDEBAR_DEFAULT))} value="Reset sidebar width default size">
            <MoveHorizontal /> Reset sidebar width
          </CommandItem>
          {THEME_OPTIONS.map(({ value, label, Icon }) => (
            <CommandItem key={value} onSelect={run(() => setTheme(value))} value={`Theme ${label} appearance`}>
              <Icon /> Theme: {label}
            </CommandItem>
          ))}
        </CommandGroup>
        {recent.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Documents">
              {recent.map((s) => (
                <CommandItem
                  key={s.id}
                  onSelect={run(() => onSelectDocument(s.id))}
                  value={`${docTitle(s)} ${s.filename} ${s.project_name ?? ""} ${s.source_lang} ${s.id}`}
                >
                  {s.running ? <Loader2 className="animate-spin text-primary" /> : <FileText />}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{docTitle(s)}</span>
                    {docTitle(s) !== s.filename && <span className="block truncate text-xs text-muted-foreground">{s.filename}</span>}
                  </span>
                  <StatusBadge status={s.status} compact />
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
        {projects.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Projects">
              {projects.map((p) => (
                <CommandItem key={p.id} onSelect={run(() => onSelectProject(p.id))} value={`${p.name} ${p.source_lang} project ${p.id}`}>
                  <Folder />
                  <span className="min-w-0 flex-1 truncate">{p.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {p.documents} doc{p.documents === 1 ? "" : "s"}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}

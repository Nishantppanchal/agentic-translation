"use client";

import { Loader2, WifiOff } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ArtifactPanel, type Tab } from "@/components/document/ArtifactPanel";
import { Chat } from "@/components/chat/Chat";
import { useProposalPick } from "@/components/chat/proposalPick";
import { ProjectCreate, ProjectView } from "@/components/projects/ProjectView";
import { ProjectsOverview } from "@/components/projects/ProjectsOverview";
import { Modal } from "@/components/settings/Modal";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { docTitle, Sidebar } from "@/components/shell/Sidebar";
import { TopBar } from "@/components/shell/TopBar";
import { UploadPanel } from "@/components/shell/UploadPanel";
import { Button } from "@/components/ui/button";
import { ease } from "@/lib/motion";
import { api, projectsApi, subscribe, type SettingsUpdate } from "@/lib/api";
import { OFFICE_FORMATS, type Answer, type Progress, type Project, type QaIssue, type SessionDetail, type SessionSummary, type StreamEvent, type TimelineItem } from "@/lib/types";

// Source languages (everything is translated into English).
const FALLBACK_LANGUAGES = ["German", "Chinese (Simplified)", "French", "Spanish", "Italian", "Portuguese", "Japanese", "Korean", "Hindi", "Arabic"];

/** Insert or replace a timeline item by id; a final assistant message drops that author's streaming draft. */
function upsert(items: TimelineItem[], item: TimelineItem): TimelineItem[] {
  let next = items;
  if (item.kind === "assistant" && !item.partial) {
    next = next.filter((i) => !(i.kind === "assistant" && i.partial && i.author === item.author));
  }
  if (item.kind === "user") {
    // Replace the optimistic copy of this message.
    next = next.filter((i) => !(i.kind === "user" && i.id.startsWith("local-") && i.text === item.text));
  }
  const idx = next.findIndex((i) => i.id === item.id);
  if (idx === -1) return [...next, item];
  const copy = [...next];
  copy[idx] = item;
  return copy;
}

export default function Home() {
  const [languages, setLanguages] = useState<string[]>(FALLBACK_LANGUAGES);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectView, setProjectView] = useState<string | null>(null); // a project id, "new", or "all" (the Projects page)
  const [uploadProject, setUploadProject] = useState<string | null>(null); // preselected on the upload page
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);

  const [artifactOpen, setArtifactOpen] = useState(true);
  const [wide, setWide] = useState(false); // segment editor full width (chat hidden)
  const [tab, setTab] = useState<Tab>("translation");
  // When a document stops for the source check, open its page images next to the reading (once per check).
  const checkFor = detail?.summary.status === "awaiting_source_check" ? detail.summary.id : null;
  const [shownCheck, setShownCheck] = useState<string | null>(null);
  if (checkFor !== shownCheck) {
    setShownCheck(checkFor);
    if (checkFor) {
      setTab("source");
      setArtifactOpen(true);
    }
  }
  const [diffTarget, setDiffTarget] = useState<number | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [panelWidth, setPanelWidth] = useState(() => {
    try {
      return Number(localStorage.getItem("panelWidth")) || 0; // px; 0 = the default share
    } catch {
      return 0;
    }
  });
  const mainRef = useRef<HTMLElement>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [deleting, setDeleting] = useState<SessionSummary | null>(null); // asking before a document is deleted
  const [deleteBusy, setDeleteBusy] = useState(false);
  // Show the Reading view once per run, when translation starts; a tab picked after that is left alone.
  const translatingShown = useRef(false);

  const unsubRef = useRef<(() => void) | null>(null);
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRef = useRef<string | null>(null);

  const refreshSessions = useCallback(() => {
    api
      .listSessions()
      .then((s) => {
        setSessions(s);
        setBackendError(null);
      })
      .catch((e) => setBackendError(String(e)));
  }, []);

  const refreshProjects = useCallback(() => {
    projectsApi
      .list()
      .then(setProjects)
      .catch(() => {});
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    const d = await api.getSession(id);
    if (activeRef.current !== id) return;
    setDetail(d);
    setTimeline((prev) => {
      // Keep live streaming drafts that aren't persisted yet.
      let merged = d.timeline;
      for (const item of prev) if (item.kind === "assistant" && item.partial) merged = upsert(merged, item);
      return merged;
    });
    setProgress(d.summary.progress);
    return d;
  }, []);

  const scheduleRefetch = useCallback(
    (id: string) => {
      if (refetchTimer.current) clearTimeout(refetchTimer.current);
      refetchTimer.current = setTimeout(() => loadDetail(id).catch(() => {}), 400);
    },
    [loadDetail],
  );

  const attach = useCallback(
    (id: string) => {
      unsubRef.current?.();
      setRunning(true);
      translatingShown.current = false;
      unsubRef.current = subscribe(id, (ev: StreamEvent) => {
        if (activeRef.current !== id) return;
        switch (ev.type) {
          case "timeline":
            setTimeline((t) => upsert(t, ev.item));
            if (ev.item.kind === "version") scheduleRefetch(id);
            break;
          case "progress":
            setProgress(ev.progress);
            if (ev.status) {
              const status = ev.status;
              setDetail((d) => (d ? { ...d, summary: { ...d.summary, status } } : d));
              if (status === "translating" && !translatingShown.current) {
                translatingShown.current = true;
                setTab("translation");
                setArtifactOpen(true);
              }
            }
            break;
          case "state":
            scheduleRefetch(id);
            break;
          case "idle":
          case "done":
            setRunning(false);
            setProgress(null);
            loadDetail(id).catch(() => {});
            refreshSessions();
            refreshProjects();
            break;
          case "error":
            setRunning(false);
            setTimeline((t) => [...t, { kind: "error", id: `err-${Date.now()}`, text: ev.message, ts: Date.now() / 1000 }]);
            break;
        }
      });
    },
    [loadDetail, refreshProjects, refreshSessions, scheduleRefetch],
  );

  const select = useCallback(
    async (id: string | null) => {
      unsubRef.current?.();
      activeRef.current = id;
      setActiveId(id);
      if (id) setProjectView(null);
      setDetail(null);
      setTimeline([]);
      setProgress(null);
      setRunning(false);
      setHighlight(null);
      setDiffTarget(null);
      setTab("translation");
      if (!id) return;
      try {
        const d = await loadDetail(id);
        if (d?.document.format && OFFICE_FORMATS.includes(d.document.format)) setTab("layout"); // the file itself, side by side
        if (d?.summary.running) attach(id);
      } catch (e) {
        setBackendError(String(e));
      }
    },
    [attach, loadDetail],
  );

  useEffect(() => {
    api
      .config()
      .then((c) => c.languages.length && setLanguages(c.languages.filter((l) => l !== c.target_lang)))
      .catch(() => {});
    refreshSessions();
    refreshProjects();
    return () => unsubRef.current?.();
  }, [refreshSessions, refreshProjects]);

  // Keep the sidebar fresh while something is running in the background.
  useEffect(() => {
    if (!sessions.some((s) => s.running)) return;
    const t = setInterval(refreshSessions, 4000);
    return () => clearInterval(t);
  }, [sessions, refreshSessions]);

  const onUpload = async (file: File, source: string, projectId: string | null, overrides?: SettingsUpdate) => {
    const s = await api.createSession(file, source, projectId, overrides);
    refreshSessions();
    refreshProjects();
    await select(s.id);
    attach(s.id);
  };

  const onSend = async (text: string) => {
    if (!activeId) return;
    setTimeline((t) => [...t, { kind: "user", id: `local-${Date.now()}`, text, ts: Date.now() / 1000 }]);
    try {
      await api.sendMessage(activeId, text);
      attach(activeId);
    } catch (e) {
      setTimeline((t) => [...t, { kind: "error", id: `err-${Date.now()}`, text: String(e), ts: Date.now() / 1000 }]);
    }
  };

  const onAnswer = async (questionId: string, answer: Answer | null) => {
    if (!activeId) return;
    try {
      await api.answerQuestion(activeId, questionId, answer);
      if (answer) attach(activeId);
      else loadDetail(activeId);
    } catch (e) {
      setTimeline((t) => [...t, { kind: "error", id: `err-${Date.now()}`, text: String(e), ts: Date.now() / 1000 }]);
    }
  };

  const onClarify = async (answers: Record<string, Answer | null>) => {
    if (!activeId) return;
    try {
      await api.submitClarifications(activeId, answers);
      attach(activeId);
    } catch (e) {
      setTimeline((t) => [...t, { kind: "error", id: `err-${Date.now()}`, text: String(e), ts: Date.now() / 1000 }]);
    }
  };

  const onDecideSourceFix = async (page: number, accept: boolean) => {
    if (!activeId) return;
    try {
      await api.decideSourceFix(activeId, page, accept);
      await loadDetail(activeId);
    } catch (e) {
      setTimeline((t) => [...t, { kind: "error", id: `err-${Date.now()}`, text: String(e), ts: Date.now() / 1000 }]);
    }
  };
  const onContinueSourceCheck = async () => {
    if (!activeId) return;
    try {
      await api.continueAfterSourceCheck(activeId);
      attach(activeId);
    } catch (e) {
      setTimeline((t) => [...t, { kind: "error", id: `err-${Date.now()}`, text: String(e), ts: Date.now() / 1000 }]);
    }
  };
  const onRetry = async () => {
    if (!activeId) return;
    try {
      await api.retry(activeId);
      attach(activeId);
      loadDetail(activeId);
    } catch (e) {
      setTimeline((t) => [...t, { kind: "error", id: `err-${Date.now()}`, text: String(e), ts: Date.now() / 1000 }]);
    }
  };

  const onAcceptProposal = async (changes: string[] | null, choices: Record<string, number> | null, confirm = false) => {
    if (!activeId) return;
    try {
      await api.acceptProposal(activeId, changes, choices, confirm);
    } catch (e) {
      setTimeline((t) => [...t, { kind: "error", id: `err-${Date.now()}`, text: String(e), ts: Date.now() / 1000 }]);
    }
    await loadDetail(activeId);
    refreshSessions();
  };

  const onRejectProposal = async () => {
    if (!activeId) return;
    try {
      await api.rejectProposal(activeId);
    } catch (e) {
      setTimeline((t) => [...t, { kind: "error", id: `err-${Date.now()}`, text: String(e), ts: Date.now() / 1000 }]);
    }
    await loadDetail(activeId);
  };

  // Deleting asks first (in a dialog, not the browser's confirm).
  const onDelete = (id: string) => setDeleting(sessions.find((s) => s.id === id) ?? null);
  const confirmDelete = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      await api.deleteSession(deleting.id);
      if (deleting.id === activeId) select(null);
      toast.success("Document deleted", { description: docTitle(deleting) });
      setDeleting(null);
    } catch (e) {
      toast.error("Couldn't delete it", { description: String(e).replace(/^Error: /, "") });
    } finally {
      setDeleteBusy(false);
      refreshSessions();
      refreshProjects();
    }
  };

  const openProject = (id: string | null) => {
    select(null);
    setProjectView(id);
  };

  const newDocument = (projectId: string | null) => {
    select(null);
    setProjectView(null);
    setUploadProject(projectId);
  };

  const jumpTo = (segmentId: string) => {
    setArtifactOpen(true);
    if (tab === "changes" || tab === "checks") setTab("parallel");
    setHighlight(segmentId);
    setTimeout(() => setHighlight((h) => (h === segmentId ? null : h)), 2500);
  };

  const summary = detail?.summary ?? sessions.find((s) => s.id === activeId);
  const docName = summary ? summary.title || summary.filename : null;
  useEffect(() => {
    document.title = activeId ? (docName ?? "Translate") : "New translation";
  }, [activeId, docName]);
  const pick = useProposalPick(detail?.document.proposal ?? null);

  /** Ask the editor what a source segment says (an answer for someone who doesn't read the source language). */
  const onExplain = (segmentId: string) => {
    setWide(false);
    onSend(`Explain ${segmentId}: what does the source say, in plain English, and does the translation carry it faithfully?`);
  };

  /** One QA issue → a chat request; the editor proposes the fix for approval. */
  const onFixIssue = (segmentId: string, issue: QaIssue) => {
    setWide(false);
    onSend(`Fix the QA ${issue.severity} in ${segmentId} (${issue.label}): ${issue.message}`);
  };

  /** Drag the divider between chat and document; the width is remembered. */
  const startResize = (e: React.PointerEvent) => {
    e.preventDefault();
    const main = mainRef.current?.getBoundingClientRect();
    if (!main) return;
    const move = (ev: PointerEvent) => {
      const width = Math.round(Math.min(main.width - 340, Math.max(420, main.right - ev.clientX)));
      setPanelWidth(width);
      try {
        localStorage.setItem("panelWidth", String(width));
      } catch {
        // storage unavailable: the width just isn't remembered
      }
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.cursor = "";
    };
    document.body.style.cursor = "col-resize";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div className="flex h-full">
      <Sidebar
        sessions={sessions}
        projects={projects}
        activeId={activeId}
        projectsActive={!activeId && !!projectView}
        onSelect={(id) => select(id)}
        onOpenProjects={() => openProject("all")}
        onNew={() => newDocument(null)}
        onDelete={onDelete}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenPalette={() => setPaletteOpen(true)}
      />
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        sessions={sessions}
        projects={projects}
        onSelectDocument={(id) => select(id)}
        onSelectProject={(id) => openProject(id)}
        onNew={() => newDocument(null)}
        onNewProject={() => openProject("new")}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <Modal open={!!deleting} onClose={() => !deleteBusy && setDeleting(null)} title="Delete this document?" width={460}>
        <p className="text-sm">{deleting ? docTitle(deleting) : ""}</p>
        <p className="mt-1 text-sm text-muted-foreground">Its translation, versions and chat history are deleted. This can&apos;t be undone.</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setDeleting(null)} disabled={deleteBusy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={confirmDelete} disabled={deleteBusy}>
            {deleteBusy && <Loader2 className="animate-spin" />} Delete
          </Button>
        </div>
      </Modal>
      <main ref={mainRef} className="relative flex min-w-0 flex-1">
        <AnimatePresence>
          {backendError && !activeId && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="absolute top-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full border border-del-fg/20 bg-del px-3 py-1.5 text-xs text-del-fg shadow-sm"
              role="alert"
            >
              <WifiOff size={13} /> The backend is unreachable: {backendError.replace(/^(Type)?Error: /, "")}
            </motion.div>
          )}
        </AnimatePresence>
        {!activeId && projectView === "all" ? (
          <div className="min-w-0 flex-1">
            <ProjectsOverview projects={projects} sessions={sessions} onOpenProject={(id) => openProject(id)} onNewProject={() => openProject("new")} />
          </div>
        ) : !activeId && projectView === "new" ? (
          <div className="flex-1">
            <ProjectCreate
              languages={languages}
              onCreated={(p) => {
                refreshProjects();
                setProjectView(p.id);
              }}
            />
          </div>
        ) : !activeId && projectView ? (
          <div className="min-w-0 flex-1">
            <ProjectView
              key={projectView}
              projectId={projectView}
              sessions={sessions}
              onOpenDocument={(id) => select(id)}
              onTranslate={(pid) => newDocument(pid)}
              onChanged={refreshProjects}
              onDeleted={() => {
                refreshProjects();
                refreshSessions();
                openProject("all");
              }}
            />
          </div>
        ) : !activeId ? (
          <div className="flex-1">
            <UploadPanel
              key={uploadProject ?? "none"}
              languages={languages}
              projects={projects}
              initialProject={uploadProject}
              onSubmit={onUpload}
            />
          </div>
        ) : (
          <div className="flex min-w-0 flex-1 flex-col">
            {summary && (
              <TopBar
                summary={summary}
                settings={detail?.document.settings}
                busy={running || !!summary.running}
                onSettingsSaved={() => activeId && loadDetail(activeId)}
                panelOpen={artifactOpen}
                onTogglePanel={
                  detail
                    ? () => {
                        if (artifactOpen) setWide(false); // hiding the document brings the chat back
                        setArtifactOpen(!artifactOpen);
                      }
                    : null
                }
              />
            )}
            <div className="flex min-h-0 flex-1">
            <div className={`relative min-w-[340px] flex-1 ${wide && artifactOpen ? "hidden" : ""}`}>
              <Chat
                sessionId={activeId}
                proposal={detail?.document.proposal ?? null}
                pick={pick}
                onAcceptProposal={onAcceptProposal}
                onRejectProposal={onRejectProposal}
                timeline={timeline}
                running={running}
                serverRunning={detail?.summary.running ?? true}
                status={detail?.summary.status}
                progress={progress}
                questions={detail?.document.questions ?? []}
                segments={detail?.document.segments ?? []}
                onSend={onSend}
                onAnswer={onAnswer}
                onClarify={onClarify}
                onRetry={onRetry}
                sourceFixes={Object.values(detail?.document.source_fixes ?? {}).sort((a, b) => a.page - b.page)}
                onDecideSourceFix={onDecideSourceFix}
                onContinueSourceCheck={onContinueSourceCheck}
                onShowDiff={(v) => {
                  setArtifactOpen(true);
                  setDiffTarget(v);
                  setTab("changes");
                }}
                onJump={jumpTo}
                draft={draft}
                setDraft={setDraft}
                lqa={detail?.document.lqa ?? null}
                format={detail?.document.format ?? null}
                versionCount={detail?.document.versions.length ?? 0}
                onOpenSegments={() => {
                  setArtifactOpen(true);
                  setTab("segments");
                }}
                onRunLqa={async () => {
                  if (!activeId) return;
                  await api.runLqa(activeId);
                  setArtifactOpen(true);
                  setTab("quality");
                  attach(activeId);
                }}
                onRunTask={async (kind) => {
                  if (!activeId) return;
                  await api.runTask(activeId, kind);
                  attach(activeId);
                }}
                settings={detail?.document.settings ?? null}
                onSettingsChanged={() => activeId && loadDetail(activeId).catch(() => {})}
              />
            </div>
            {artifactOpen && summary && detail && !wide && (
              <div
                onPointerDown={startResize}
                role="separator"
                aria-orientation="vertical"
                aria-label="Drag to resize the document panel"
                className="group relative w-px shrink-0 cursor-col-resize bg-border"
              >
                {/* a wider grab area, and a highlight while hovering */}
                <span className="absolute inset-y-0 -right-1.5 -left-1.5 z-10" />
                <span className="absolute inset-y-0 -left-px w-[3px] bg-primary/40 opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
            )}
            <AnimatePresence initial={false}>
            {artifactOpen && summary && detail && (
              <motion.div
                key="panel"
                initial={{ opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 24 }}
                transition={{ duration: 0.2, ease }}
                className={wide ? "min-w-0 flex-1" : panelWidth ? "min-w-[420px] shrink-0" : "w-[60%] max-w-[1100px] min-w-[420px]"}
                // The remembered width never squeezes the chat below its minimum (e.g. after the sidebar expands).
                style={!wide && panelWidth ? { width: `min(${panelWidth}px, calc(100% - 344px))` } : undefined}
              >
                <ArtifactPanel
                  key={summary.id} // per-document view state (picked version, compare range) starts fresh
                  session={summary}
                  doc={detail.document}
                  tab={tab}
                  setTab={setTab}
                  diffTarget={diffTarget}
                  highlight={highlight}
                  onReference={(id) => setDraft(`${draft}${draft && !draft.endsWith(" ") ? " " : ""}[${id}] `)}
                  onClose={() => setArtifactOpen(false)}
                  onDraft={(text) => {
                    setWide(false);
                    setDraft(text);
                    document.querySelector<HTMLTextAreaElement>("textarea")?.focus();
                  }}
                  onSend={(text) => {
                    setWide(false);
                    onSend(text);
                  }}
                  editable={!running && !summary.running && ["ready", "error"].includes(summary.status)}
                  canComment={!running && !summary.running}
                  wide={wide}
                  onToggleWide={() => setWide((w) => !w)}
                  onSegment={(seg, humanDirty) =>
                    setDetail((d) =>
                      d
                        ? {
                            ...d,
                            document: {
                              ...d.document,
                              human_dirty: humanDirty,
                              segments: d.document.segments.map((s) => (s.id === seg.id ? seg : s)),
                            },
                          }
                        : d,
                    )
                  }
                  onReload={() => activeId && loadDetail(activeId)}
                  onRunLqa={async () => {
                    if (!activeId) return;
                    await api.runLqa(activeId);
                    attach(activeId);
                  }}
                  proposal={detail.document.proposal}
                  pick={pick}
                  onAcceptProposal={onAcceptProposal}
                  onRejectProposal={onRejectProposal}
                  onExplain={onExplain}
                  onFixIssue={onFixIssue}
                  onRunTask={async (kind, ids, instruction, n) => {
                    if (!activeId) return;
                    await api.runTask(activeId, kind, ids, instruction, n);
                    setArtifactOpen(true);
                    setWide(false); // the proposal appears in the chat
                    attach(activeId);
                  }}
                />
              </motion.div>
            )}
            </AnimatePresence>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

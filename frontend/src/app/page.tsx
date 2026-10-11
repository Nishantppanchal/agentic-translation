"use client";

import { PanelRightOpen } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArtifactPanel, type Tab } from "@/components/ArtifactPanel";
import { Chat } from "@/components/Chat";
import { useProposalPick } from "@/components/proposalPick";
import { ProjectCreate, ProjectView } from "@/components/ProjectView";
import { Sidebar } from "@/components/Sidebar";
import { UploadPanel } from "@/components/UploadPanel";
import { api, projectsApi, subscribe } from "@/lib/api";
import type { Answer, Progress, Project, QaIssue, SessionDetail, SessionSummary, StreamEvent, TimelineItem } from "@/lib/types";

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
  const [projectView, setProjectView] = useState<string | null>(null); // a project id, or "new"
  const [uploadProject, setUploadProject] = useState<string | null>(null); // preselected on the upload page
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);

  const [artifactOpen, setArtifactOpen] = useState(true);
  const [wide, setWide] = useState(false); // segment editor full width (chat hidden)
  const [tab, setTab] = useState<Tab>("translation");
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

  const onUpload = async (file: File, source: string, projectId: string | null) => {
    const s = await api.createSession(file, source, projectId);
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

  const onAcceptProposal = async (changes: string[] | null, choices: Record<string, number> | null) => {
    if (!activeId) return;
    try {
      await api.acceptProposal(activeId, changes, choices);
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

  const onDelete = async (id: string) => {
    if (!window.confirm("Delete this document and its history?")) return;
    await api.deleteSession(id);
    if (id === activeId) select(null);
    refreshSessions();
    refreshProjects();
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
        activeProject={activeId ? null : projectView}
        onSelect={(id) => select(id)}
        onSelectProject={(id) => openProject(id)}
        onNewProject={() => openProject("new")}
        onNew={() => newDocument(null)}
        onDelete={onDelete}
      />
      <main ref={mainRef} className="flex min-w-0 flex-1">
        {backendError && !activeId && (
          <div className="absolute top-3 left-1/2 z-10 -translate-x-1/2 rounded-lg bg-del px-3 py-1.5 text-xs text-del-fg">
            Backend unreachable: {backendError}
          </div>
        )}
        {!activeId && projectView === "new" ? (
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
                openProject(null);
              }}
            />
          </div>
        ) : !activeId ? (
          <div className="flex-1">
            <UploadPanel key={uploadProject ?? "none"} languages={languages} projects={projects} initialProject={uploadProject} onSubmit={onUpload} />
          </div>
        ) : (
          <>
            <div className={`relative min-w-[340px] flex-1 ${wide && artifactOpen ? "hidden" : ""}`}>
              {!artifactOpen && (
                <button
                  onClick={() => setArtifactOpen(true)}
                  className="absolute top-3 right-3 z-10 flex items-center gap-1.5 rounded-lg border border-border bg-panel px-2.5 py-1.5 text-xs shadow-sm hover:border-accent"
                >
                  <PanelRightOpen size={14} /> Show translation
                </button>
              )}
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
              />
            </div>
            {artifactOpen && summary && detail && !wide && (
              <div
                onPointerDown={startResize}
                className="w-1 shrink-0 cursor-col-resize bg-border/60 transition-colors hover:bg-accent/50"
                title="Drag to resize"
              />
            )}
            {artifactOpen && summary && detail && (
              <div
                className={wide ? "min-w-0 flex-1" : panelWidth ? "min-w-[420px] shrink-0" : "w-[60%] max-w-[1100px] min-w-[420px]"}
                style={!wide && panelWidth ? { width: panelWidth } : undefined}
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
                  editable={!running && !summary.running && ["ready", "error"].includes(summary.status)}
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
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

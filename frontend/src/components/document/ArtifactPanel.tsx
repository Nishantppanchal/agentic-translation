"use client";

import { FileSearch, FileText, Maximize2, Minimize2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { fade } from "@/lib/motion";
import { OFFICE_FORMATS, type DocumentState, type Proposal, type QaIssue, type Role, type Segment, type SessionSummary, type TaskKind } from "@/lib/types";
import { CommentThread } from "../cat/CommentThread";
import { SegmentGrid } from "../cat/SegmentGrid";
import { useQa } from "../cat/useQa";
import { UsageChip } from "../cat/UsageChip";
import type { ProposalPick } from "../chat/proposalPick";
import { ExportMenu } from "./ExportMenu";
import { LayoutView } from "./layout/LayoutView";
import { Markdown } from "./Markdown";
import { QualityView } from "./QualityView";
import { RichDiff } from "./RichDiff";
import { CellTable } from "./CellTable";
import { AltLine, FigureBlock, PageBreak, pairAltText, SegmentShell, type CommentsUi, type ShellActions } from "./SegmentShell";
import { SelectionToolbar } from "./SelectionToolbar";
import { ChecksView, SourceView } from "./SourceViews";

export type Tab = "segments" | "quality" | "layout" | "translation" | "parallel" | "source" | "changes" | "checks";

/** Five top-level tabs; the document and source tabs have views you switch between inside them. */
const GROUPS: { id: string; label: string; views: { id: Tab; label: string }[] }[] = [
  { id: "segments", label: "Segments", views: [{ id: "segments", label: "Segments" }] },
  {
    id: "document",
    label: "Document",
    views: [
      { id: "layout", label: "Layout" }, // Word / PowerPoint / Excel: the files themselves, side by side
      { id: "translation", label: "Reading" },
      { id: "parallel", label: "Side by side" },
    ],
  },
  { id: "quality", label: "Quality", views: [{ id: "quality", label: "Quality" }] },
  { id: "history", label: "History", views: [{ id: "changes", label: "Changes" }] },
  {
    id: "source",
    label: "Source & notes",
    views: [
      { id: "source", label: "Page images & OCR" },
      { id: "checks", label: "Brief, terms & checks" },
    ],
  },
];

type Snapshot = Record<string, string>;

/** Version snapshots, fetched on demand. A version that can't be loaded is `null` (shown as unavailable). */
function useSnapshots(sessionId: string, versions: number[]) {
  const cache = useRef(new Map<string, Snapshot | null>());
  const [, force] = useState(0);
  const key = versions.join(",");
  useEffect(() => {
    let cancelled = false;
    for (const v of versions) {
      const k = `${sessionId}:${v}`;
      if (v > 0 && !cache.current.has(k)) {
        api
          .getVersion(sessionId, v)
          .then((snap) => cache.current.set(k, snap.segments))
          .catch(() => cache.current.set(k, null))
          .finally(() => !cancelled && force((n) => n + 1));
      }
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, key]);
  return (v: number) => cache.current.get(`${sessionId}:${v}`);
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          className="flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          aria-label={label}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/** The document panel: the segment editor, the document as it reads (and the Office files as they look), the
 * quality checks, the history of versions, and the source with the agents' notes. The document's name, status and
 * models are in the page's top bar. */
export function ArtifactPanel({
  session,
  doc,
  tab,
  setTab,
  diffTarget,
  highlight,
  onReference,
  onClose,
  onDraft,
  onSend,
  editable,
  canComment,
  wide,
  onToggleWide,
  onSegment,
  onReload,
  onRunLqa,
  onRunTask,
  proposal,
  pick,
  onAcceptProposal,
  onRejectProposal,
  onExplain,
  onFixIssue,
}: {
  session: SessionSummary;
  doc: DocumentState;
  tab: Tab;
  setTab: (t: Tab) => void;
  diffTarget: number | null;
  highlight: string | null;
  onReference: (id: string) => void;
  onClose: () => void;
  onDraft: (text: string) => void;
  onSend: (text: string) => void; // a chat message (Explain from the selection toolbar)
  editable: boolean;
  canComment: boolean; // comments (and the chat) are open whenever no run is active
  wide: boolean;
  onToggleWide: () => void;
  onSegment: (seg: Segment, humanDirty: string[]) => void;
  onReload: () => void;
  onRunLqa: () => Promise<void>;
  onRunTask: (kind: TaskKind, segmentIds: string[], instruction: string, n: number) => Promise<void>;
  proposal: Proposal | null;
  pick: ProposalPick;
  onAcceptProposal: (changes: string[] | null, choices: Record<string, number> | null, confirm?: boolean) => Promise<void>;
  onRejectProposal: () => Promise<void>;
  onExplain: (segmentId: string) => void;
  onFixIssue: (segmentId: string, issue: QaIssue) => void;
}) {
  // The view last picked in each tab group, so switching back returns to it.
  const [lastView, setLastView] = useState<Record<string, Tab>>({});
  // Word / PowerPoint / Excel uploads get the Layout view, and have no page images to check.
  const isOffice = !!doc.format && OFFICE_FORMATS.includes(doc.format);
  const groups = GROUPS.map((g) => ({
    ...g,
    views: g.views.filter((v) => (v.id === "layout" ? isOffice : v.id === "source" ? !isOffice : true)),
  }));
  const groupOf = (t: Tab) => groups.find((g) => g.views.some((v) => v.id === t)) ?? groups[0];
  const group = groupOf(tab);
  const pickView = (id: Tab) => {
    setLastView((l) => ({ ...l, [groupOf(id).id]: id }));
    setTab(id);
  };
  const ready = ["ready", "error"].includes(session.status);
  const checking = session.status === "awaiting_source_check"; // nothing translated yet: show the reading
  const qa = useQa(session.id, doc.segments, ready && (tab === "segments" || tab === "quality"));
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null);
  const openSegment = (id: string) => {
    setTab("segments");
    setFocus((f) => ({ id, n: (f?.n ?? 0) + 1 })); // a new object each time, so the same segment can be re-opened
  };
  const [role, setRole] = useState<Role>("translator"); // what confirming means in the grid, and who comments
  const [openThread, setOpenThread] = useState<string | null>(null);
  const comments: CommentsUi = {
    open: openThread,
    toggle: (id) => setOpenThread((t) => (t === id ? null : id)),
    thread: (seg) => (
      <CommentThread
        sessionId={session.id}
        segId={seg.id}
        comments={seg.comments ?? []}
        canComment={canComment}
        role={role}
        onChanged={(updated) => (updated ? onSegment(updated, doc.human_dirty) : onReload())}
        onClose={() => setOpenThread(null)}
        autoFocus={!seg.comments?.length}
        className="mt-1 mb-2"
      />
    ),
  };
  const actions: ShellActions = { onReference, comments, editable, onRunTask };
  const latest = doc.versions.at(-1)?.version ?? 0;
  const known = new Set(doc.versions.map((v) => v.version));
  const [picks, setViewVersion] = useState<number | "latest">("latest");
  // Only versions this document has (a retried document starts its versions again).
  const viewVersion = picks !== "latest" && known.has(picks) ? picks : "latest";
  // The diff view defaults to the requested version (from a chat "View diff" click) or the latest,
  // compared with its predecessor; a manual pick sticks until that default changes.
  const baseTo = diffTarget && known.has(diffTarget) ? diffTarget : latest;
  const [picked, setPicked] = useState<{ base: number; from: number; to: number } | null>(null);
  const compare =
    picked && picked.base === baseTo && known.has(picked.from) && known.has(picked.to)
      ? picked
      : { base: baseTo, from: Math.max(1, baseTo - 1), to: baseTo };
  const setCompare = (update: (c: typeof compare) => typeof compare) => setPicked(update(compare));

  const getSnap = useSnapshots(session.id, [
    ...(viewVersion === "latest" ? [] : [viewVersion]),
    ...(tab === "changes" ? [compare.from, compare.to] : []),
  ]);

  // Segments for the version being viewed (sources never change between versions, except OCR fixes).
  const segments = useMemo(() => {
    if (viewVersion === "latest") return doc.segments;
    const snap = getSnap(viewVersion);
    if (!snap) return doc.segments;
    return doc.segments.map((s) => ({ ...s, target: snap[s.id] ?? s.target }));
  }, [doc.segments, viewVersion, getSnap]);
  // A picture's alt text (Word / PowerPoint / Excel) shows with the picture it belongs to.
  const { altOf, paired } = useMemo(() => pairAltText(segments), [segments]);

  useEffect(() => {
    if (!highlight) return;
    document.getElementById(`seg-${highlight}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlight, tab]);

  /** The segments in order, with page breaks; a Word or PowerPoint table's cells (one segment per paragraph) are
   * put back into their table (`cell`), each paragraph still rendered on its own. */
  const withPageBreaks = (render: (s: Segment) => React.ReactNode, cell: (s: Segment) => React.ReactNode) => {
    const out: React.ReactNode[] = [];
    let page: number | null = null;
    const shown = segments.filter((s) => !paired.has(s.id));
    for (let i = 0; i < shown.length; i++) {
      const s = shown[i];
      if (page !== null && s.page !== page) out.push(<PageBreak key={`pb-${s.page}`} page={s.page} label={doc.page_labels?.[s.page - 1]} />);
      page = s.page;
      if (!s.cell) {
        out.push(render(s));
        continue;
      }
      // A run of cells (a table nested in another comes after it): one table each.
      const tables = new Map<string, Segment[]>();
      for (; i < shown.length && shown[i].cell && shown[i].page === page; i++) {
        const c = shown[i];
        tables.set(c.cell!.table, [...(tables.get(c.cell!.table) ?? []), c]);
      }
      i--;
      for (const [table, cells] of tables) out.push(<CellTable key={`${table}-${cells[0].id}`} cells={cells} render={cell} />);
    }
    return out;
  };

  /** A segment's text in the Reading view: the translation, or the source with why it isn't translated yet. */
  const readingText = (s: Segment) =>
    s.target ? (
      <Markdown text={s.target} />
    ) : checking ? (
      <Markdown text={s.source} />
    ) : session.status === "awaiting_answers" ? (
      <div className="flex items-baseline gap-1.5 text-muted-foreground">
        <span className="shrink-0 text-[10px]">not translated yet</span>
        <Markdown text={s.source} className="min-w-0 text-sm" />
      </div>
    ) : (
      <div className="animate-pulse text-sm text-muted-foreground italic">translating {s.id}…</div>
    );

  const scrollRef = useRef<HTMLDivElement>(null);
  const empty = segments.length === 0;
  const reading = tab === "translation" || tab === "parallel";

  return (
    <section className="flex h-full min-w-0 flex-col border-l border-border bg-card">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border pr-2 pl-3">
        <Tabs value={group.id} onValueChange={(id) => id !== group.id && setTab(lastView[id] ?? groups.find((g) => g.id === id)!.views[0].id)} className="min-w-0 flex-1">
          <TabsList variant="line" className="scroll-thin w-full justify-start gap-0 overflow-x-auto p-0 group-data-[orientation=horizontal]/tabs:h-11">
            {groups.map((g) => (
              <TabsTrigger key={g.id} value={g.id} className="h-full flex-none rounded-none px-2.5 text-[13px] group-data-[orientation=horizontal]/tabs:after:bottom-0">
                {g.label}
                {g.id === "quality" && qa.report && qa.report.summary.errors > 0 && (
                  <span className="rounded-full bg-del px-1.5 text-[10px] font-medium text-del-fg tabular-nums">{qa.report.summary.errors}</span>
                )}
                {g.id === "segments" && proposal && proposal.changes.length > 0 && (
                  <span className="rounded-full bg-primary-soft px-1.5 text-[10px] font-medium text-primary tabular-nums" title="Proposed changes to review">
                    {proposal.changes.length}
                  </span>
                )}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="flex shrink-0 items-center gap-1">
          {latest > 0 && (
            <Select value={String(viewVersion)} onValueChange={(v) => setViewVersion(v === "latest" ? "latest" : Number(v))}>
              <SelectTrigger size="sm" className="h-8 max-w-44 gap-1 border-transparent bg-transparent px-2 text-xs shadow-none hover:bg-accent" aria-label="Version shown">
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="end" className="max-h-80 max-w-80">
                <SelectItem value="latest">
                  v{latest} <span className="text-muted-foreground">latest</span>
                </SelectItem>
                {doc.versions
                  .slice(0, -1)
                  .reverse()
                  .map((v) => (
                    <SelectItem key={v.version} value={String(v.version)}>
                      v{v.version} <span className="truncate text-muted-foreground">{v.note}</span>
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          )}
          {latest > 0 && (
            <ExportMenu
              sessionId={session.id}
              filename={session.filename}
              version={viewVersion === "latest" ? undefined : viewVersion}
              latest={latest}
              refreshKey={`${latest}-${session.status}`}
              notes={doc.client_notes ?? null}
              onNotesSaved={onReload}
            />
          )}
          <UsageChip sessionId={session.id} refreshKey={`${latest}-${session.status}-${session.running}`} />
          <IconButton label={wide ? "Show the chat again" : "Widen (hide the chat)"} onClick={onToggleWide}>
            {wide ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </IconButton>
          <IconButton label="Close the document panel" onClick={onClose}>
            <X size={16} />
          </IconButton>
        </div>
      </header>

      {group.views.length > 1 && (
        <div className="flex shrink-0 items-center border-b border-border bg-background/50 px-4 py-1.5">
          <Tabs value={tab} onValueChange={(v) => pickView(v as Tab)}>
            <TabsList className="h-8">
              {group.views.map((v) => (
                <TabsTrigger key={v.id} value={v.id} className="h-7 px-3 text-xs">
                  {v.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          {reading && !empty && (
            <span className="ml-auto hidden text-[11px] text-muted-foreground lg:inline">Select text to ask about it, explain it or rewrite it</span>
          )}
        </div>
      )}

      <div ref={scrollRef} className="scroll-thin relative flex-1 overflow-y-auto px-6 py-5">
        {empty ? (
          <div className="mx-auto mt-16 flex max-w-sm flex-col items-center gap-3 text-center">
            <FileText size={28} className="text-muted-foreground/60" />
            <p className="text-sm text-muted-foreground">The document appears here once it has been read.</p>
            <div className="w-full space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-4/6" />
            </div>
          </div>
        ) : (
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={tab} {...fade}>
              {checking && reading && (
                <div className="mb-4 flex items-center gap-2 rounded-lg border border-warn-fg/20 bg-warn/50 px-3 py-2 text-xs">
                  <FileSearch size={14} className="shrink-0 text-warn-fg" />
                  <span className="flex-1">This is the reading of the source (OCR). Nothing is translated until you continue.</span>
                  <button onClick={() => pickView("source")} className="shrink-0 font-medium text-primary hover:underline">
                    Compare with the page images
                  </button>
                </div>
              )}

              {tab === "translation" && (
                <div className="mx-auto max-w-3xl">
                  {withPageBreaks(
                    (s) => (
                      <SegmentShell key={s.id} seg={s} highlighted={highlight === s.id} actions={actions}>
                        {s.kind === "header" || s.kind === "footer" ? (
                          <div className="text-xs text-muted-foreground">
                            <span className="mr-1.5 text-[10px] tracking-wide uppercase">{s.kind}</span>
                            {s.target ?? s.source}
                          </div>
                        ) : s.kind === "figure" ? (
                          <FigureBlock sessionId={session.id} seg={s} legend={s.target ?? s.source} alt={altOf.get(s.id)} />
                        ) : s.kind === "alt" ? (
                          <div className="py-1 text-xs text-muted-foreground">
                            {s.where && <span className="mr-2">{s.where.replace(/ · alt text$/, "")}</span>}
                            <AltLine seg={s} />
                          </div>
                        ) : (
                          readingText(s)
                        )}
                      </SegmentShell>
                    ),
                    (s) => (
                      <SegmentShell key={s.id} seg={s} highlighted={highlight === s.id} actions={actions} compact>
                        {readingText(s)}
                      </SegmentShell>
                    ),
                  )}
                </div>
              )}

              {tab === "parallel" && (
                <>
                  <div className="mb-2 grid grid-cols-2 gap-6 text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
                    <span>{session.source_lang || "Source"}</span>
                    <span>English</span>
                  </div>
                  {withPageBreaks(
                    (s) => (
                      <SegmentShell key={s.id} seg={s} highlighted={highlight === s.id} actions={actions}>
                        {s.kind === "figure" ? (
                          <div className="py-1">
                            <FigureBlock sessionId={session.id} seg={s} legend={null} />
                            {(s.source || altOf.has(s.id)) && (
                              <div className="grid grid-cols-2 gap-6 text-xs whitespace-pre-line">
                                <div className="space-y-1 text-muted-foreground">
                                  {altOf.has(s.id) && <AltLine seg={altOf.get(s.id)!} side="source" />}
                                  {s.source && <div>{s.source}</div>}
                                </div>
                                <div className="space-y-1">
                                  {altOf.has(s.id) && (
                                    <div className="text-muted-foreground">
                                      <AltLine seg={altOf.get(s.id)!} />
                                    </div>
                                  )}
                                  {s.source && <div>{s.target ?? "…"}</div>}
                                </div>
                              </div>
                            )}
                          </div>
                        ) : s.kind === "alt" ? (
                          <div className="grid grid-cols-2 gap-6 py-1 text-xs text-muted-foreground">
                            <AltLine seg={s} side="source" />
                            <AltLine seg={s} />
                          </div>
                        ) : (
                          <div className="grid grid-cols-2 gap-6 py-1">
                            <Markdown text={s.source} className="text-muted-foreground" />
                            {s.target ? <Markdown text={s.target} /> : <div className="text-sm text-muted-foreground italic">…</div>}
                          </div>
                        )}
                      </SegmentShell>
                    ),
                    // in a table: the original above the English, in the same cell
                    (s) => (
                      <SegmentShell key={s.id} seg={s} highlighted={highlight === s.id} actions={actions} compact>
                        <Markdown text={s.source} className="text-xs text-muted-foreground" />
                        {s.target ? <Markdown text={s.target} /> : <div className="text-sm text-muted-foreground italic">…</div>}
                      </SegmentShell>
                    ),
                  )}
                </>
              )}

              {tab === "source" && (
                <SourceView
                  sessionId={session.id}
                  segments={segments}
                  doc={doc}
                  highlight={highlight}
                  actions={actions}
                  onFigureIsText={checking && canComment ? onReload : null}
                />
              )}

              {tab === "changes" && (
                <div>
                  {latest < 2 ? (
                    <p className="text-sm text-muted-foreground">
                      No changes yet. Versions are created after the draft translation, after review, and after each edit.
                    </p>
                  ) : (
                    <>
                      <div className="mb-4 flex items-center gap-2 text-xs">
                        <span className="text-muted-foreground">Compare</span>
                        <VersionSelect versions={doc.versions.map((v) => v.version)} value={compare.from} onChange={(from) => setCompare((c) => ({ ...c, from }))} />
                        <span className="text-muted-foreground">→</span>
                        <VersionSelect versions={doc.versions.map((v) => v.version)} value={compare.to} onChange={(to) => setCompare((c) => ({ ...c, to }))} />
                        <span className="ml-auto truncate text-muted-foreground">{doc.versions.find((v) => v.version === compare.to)?.note}</span>
                      </div>
                      <ChangesList segments={doc.segments} before={getSnap(compare.from)} after={getSnap(compare.to)} onReference={onReference} />
                    </>
                  )}
                </div>
              )}

              {tab === "checks" && <ChecksView doc={doc} onDraft={onDraft} />}

              {tab === "layout" && isOffice && (
                <div style={{ height: "calc(100vh - 190px)" }}>
                  <LayoutView
                    sessionId={session.id}
                    doc={doc}
                    segments={segments}
                    version={viewVersion === "latest" ? undefined : viewVersion}
                    latest={latest}
                    highlight={highlight}
                    onPick={openSegment}
                  />
                </div>
              )}

              {tab === "segments" && (
                <SegmentGrid
                  sessionId={session.id}
                  doc={doc}
                  hasProject={!!session.project_id}
                  editable={editable}
                  canComment={canComment}
                  role={role}
                  setRole={setRole}
                  qa={qa}
                  focus={focus}
                  onRunTask={onRunTask}
                  onSegment={onSegment}
                  onReload={onReload}
                  onReference={onReference}
                  proposal={proposal}
                  pick={pick}
                  onAcceptProposal={onAcceptProposal}
                  onRejectProposal={onRejectProposal}
                  onExplain={onExplain}
                  onFixIssue={onFixIssue}
                />
              )}

              {tab === "quality" &&
                (ready ? (
                  <QualityView
                    doc={doc}
                    qa={qa}
                    canRun={editable}
                    onRunLqa={onRunLqa}
                    onFixConsistency={() => onRunTask("consistency", [], "", 1)}
                    onOpenSegment={openSegment}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">Quality checks run once the pipeline has finished.</p>
                ))}
            </motion.div>
          </AnimatePresence>
        )}
      </div>
      <SelectionToolbar
        rootRef={scrollRef}
        enabled={reading && !empty}
        canAsk={canComment && session.status !== "awaiting_answers"}
        editable={editable}
        onSend={onSend}
        onRunTask={onRunTask}
        onDraft={onDraft}
      />
    </section>
  );
}

function VersionSelect({ versions, value, onChange }: { versions: number[]; value: number; onChange: (v: number) => void }) {
  return (
    <Select value={String(value)} onValueChange={(v) => onChange(Number(v))}>
      <SelectTrigger size="sm" className="h-7 w-20 text-xs" aria-label="Version">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {versions.map((v) => (
          <SelectItem key={v} value={String(v)}>
            v{v}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function ChangesList({
  segments,
  before,
  after,
  onReference,
}: {
  segments: Segment[];
  before?: Snapshot | null;
  after?: Snapshot | null;
  onReference: (id: string) => void;
}) {
  if (before === null || after === null) return <p className="text-sm text-muted-foreground">This version isn&apos;t available any more.</p>;
  if (!before || !after)
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-20 w-full rounded-lg" />
        ))}
      </div>
    );
  const changed = segments.filter((s) => (before[s.id] ?? "") !== (after[s.id] ?? ""));
  if (changed.length === 0) return <p className="text-sm text-muted-foreground">No differences between these versions.</p>;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {changed.length} segment{changed.length === 1 ? "" : "s"} changed
      </p>
      {changed.map((s) => (
        <div key={s.id} className="rounded-xl border border-border bg-card p-3 shadow-xs">
          <div className="mb-1.5 flex items-center justify-between">
            <button onClick={() => onReference(s.id)} className="font-mono text-[11px] text-muted-foreground hover:text-primary">
              {s.id}
            </button>
          </div>
          <div className="mb-2 line-clamp-3 text-xs text-muted-foreground">
            <Markdown text={s.source} inline />
          </div>
          <RichDiff before={before[s.id] ?? ""} after={after[s.id] ?? ""} />
        </div>
      ))}
    </div>
  );
}

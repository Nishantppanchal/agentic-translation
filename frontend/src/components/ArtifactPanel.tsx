"use client";

import { AlertTriangle, BookOpen, CheckCircle2, FileSearch, Maximize2, MessageSquareQuote, Minimize2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { DIRECT_FORMATS, UNIT_LABEL, type DocumentState, type Proposal, type QaIssue, type Segment, type SessionSummary, type TaskKind } from "@/lib/types";
import { SegmentGrid } from "./cat/SegmentGrid";
import { useQa } from "./cat/useQa";
import { ExportMenu } from "./ExportMenu";
import { LayoutView } from "./LayoutView";
import { UsageChip } from "./cat/UsageChip";
import { DiffText } from "./Diff";
import { Markdown } from "./Markdown";
import { OfficeLayoutView } from "./OfficeLayoutView";
import type { ProposalPick } from "./proposalPick";
import { QualityView } from "./QualityView";
import { StatusBadge } from "./StatusBadge";

export type Tab = "segments" | "quality" | "translation" | "parallel" | "layout" | "source" | "changes" | "checks";

/** Five top-level tabs; the document and source tabs have views you switch between inside them. */
const GROUPS: { id: string; label: string; views: { id: Tab; label: string }[] }[] = [
  { id: "segments", label: "Segments", views: [{ id: "segments", label: "Segments" }] },
  {
    id: "document",
    label: "Document",
    views: [
      { id: "translation", label: "Reading" },
      { id: "parallel", label: "Side by side" },
      { id: "layout", label: "Original layout" },
    ],
  },
  { id: "quality", label: "Quality", views: [{ id: "quality", label: "Quality" }] },
  { id: "history", label: "History", views: [{ id: "changes", label: "Changes" }] },
  {
    id: "source",
    label: "Source & notes",
    views: [
      { id: "source", label: "Source" },
      { id: "checks", label: "Brief, terms & checks" },
    ],
  },
];
/** Tab groups for a document's format: Excel and PowerPoint get sheet/slide views; files read directly
 * (Office, XLIFF) have no "Original layout" (that's the PDF re-typeset in place). */
function groupsFor(format: DocumentState["format"]) {
  const direct = !!format && DIRECT_FORMATS.includes(format);
  const first = format === "xlsx" ? "Sheets" : format === "pptx" ? "Slides" : "Reading";
  return GROUPS.map((g) =>
    g.id !== "document"
      ? g
      : { ...g, views: g.views.filter((v) => !(direct && v.id === "layout")).map((v) => (v.id === "translation" ? { ...v, label: first } : v)) },
  );
}

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

const FLAG_LABEL: Record<string, string> = { untranslated: "Not translated", merged: "Check: merged text?" };
const FLAG_HELP: Record<string, string> = {
  untranslated: "The translation is missing or still in the source language. Review couldn't fix it — edit it or ask in chat.",
  merged: "Text may have moved between this segment and a neighbour. Compare with the source.",
};

function SegmentShell({
  seg,
  highlighted,
  onReference,
  children,
}: {
  seg: Segment;
  highlighted: boolean;
  onReference: (id: string) => void;
  children: React.ReactNode;
}) {
  return (
    <div
      id={`seg-${seg.id}`}
      className={`group relative -mx-3 rounded-lg px-3 py-0.5 transition-colors ${
        highlighted ? "bg-accent-soft" : "hover:bg-sidebar/60"
      }`}
    >
      {children}
      {(!!seg.flags?.length || (seg.pages?.length ?? 0) > 1) && (
        <div className="mt-0.5 mb-1 flex flex-wrap items-center gap-1.5">
          {seg.flags?.map((f) => (
            <span
              key={f}
              className="rounded bg-warn px-1.5 py-0.5 text-[10px] font-medium text-warn-fg"
              title={FLAG_HELP[f] ?? f}
            >
              {FLAG_LABEL[f] ?? f}
            </span>
          ))}
          {(seg.pages?.length ?? 0) > 1 && (
            <span className="text-[10px] text-muted italic">↪ continues onto page {seg.pages!.slice(1).join(", ")}</span>
          )}
        </div>
      )}
      <button
        onClick={() => onReference(seg.id)}
        className="absolute top-1 -right-1 hidden items-center gap-1 rounded-md border border-border bg-panel px-1.5 py-0.5 text-[10px] text-muted shadow-sm group-hover:flex hover:text-fg"
        title="Reference this passage in chat"
      >
        <MessageSquareQuote size={12} /> {seg.id}
      </button>
    </div>
  );
}

/** A figure from the source document, with the text found inside it shown (and translated) as a legend. */
function FigureBlock({ sessionId, seg, legend, muted = false }: { sessionId: string; seg: Segment; legend: string | null; muted?: boolean }) {
  return (
    <figure className="my-2">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={api.figureUrl(sessionId, seg.image ?? "")}
        alt={`Figure ${seg.figure ?? ""}`}
        className="max-h-80 max-w-full rounded-md border border-border"
      />
      {legend && (
        <figcaption className={`mt-1.5 border-l-2 border-border pl-2 text-xs whitespace-pre-line ${muted ? "text-muted" : ""}`}>
          <span className="mr-1 text-[10px] tracking-wide text-muted uppercase">Text in figure</span>
          {legend}
        </figcaption>
      )}
    </figure>
  );
}

function PageBreak({ page, unit = "Page" }: { page: number; unit?: string }) {
  return (
    <div className="my-4 flex items-center gap-2 text-[10px] tracking-wider text-muted uppercase">
      <div className="h-px flex-1 bg-border" /> {unit} {page} <div className="h-px flex-1 bg-border" />
    </div>
  );
}

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
  editable,
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
  editable: boolean;
  wide: boolean;
  onToggleWide: () => void;
  onSegment: (seg: Segment, humanDirty: string[]) => void;
  onReload: () => void;
  onRunLqa: () => Promise<void>;
  onRunTask: (kind: TaskKind, segmentIds: string[], instruction: string, n: number) => Promise<void>;
  proposal: Proposal | null;
  pick: ProposalPick;
  onAcceptProposal: (changes: string[] | null, choices: Record<string, number> | null) => Promise<void>;
  onRejectProposal: () => Promise<void>;
  onExplain: (segmentId: string) => void;
  onFixIssue: (segmentId: string, issue: QaIssue) => void;
}) {
  // The view last picked in each tab group, so switching back returns to it.
  const [lastView, setLastView] = useState<Record<string, Tab>>({});
  const groups = groupsFor(doc.format);
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

  useEffect(() => {
    if (!highlight) return;
    document.getElementById(`seg-${highlight}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlight, tab]);

  const direct = !!doc.format && DIRECT_FORMATS.includes(doc.format); // read from the file: plain text + codes
  const unit = (doc.format && UNIT_LABEL[doc.format]) || "Page";
  const withPageBreaks = (render: (s: Segment) => React.ReactNode) => {
    const out: React.ReactNode[] = [];
    let page: number | null = null;
    for (const s of segments) {
      if (page !== null && s.page !== page) out.push(<PageBreak key={`pb-${s.page}`} page={s.page} unit={unit} />);
      page = s.page;
      out.push(render(s));
    }
    return out;
  };

  const empty = segments.length === 0;

  return (
    <section className="flex h-full min-w-0 flex-col border-l border-border bg-panel">
      <header className="flex items-center gap-2 border-b border-border px-4 py-2">
        <div
          className="flex min-w-0 flex-1 items-center gap-2"
          title={`${session.project_name ? `${session.project_name} · ` : ""}${session.source_lang} → English · ${session.pages} ${unit.toLowerCase()}${session.pages === 1 ? "" : "s"} · ${segments.length} segments`}
        >
          <span className="min-w-[5rem] truncate text-sm font-semibold">{session.filename}</span>
          <span className="shrink-0">
            <StatusBadge status={session.status} />
          </span>
          <span className="hidden min-w-0 shrink-[4] truncate text-xs text-muted 2xl:inline">
            {session.source_lang} → English · {segments.length} segments
          </span>
        </div>
        {latest > 0 && (
          <select
            value={viewVersion}
            onChange={(e) => setViewVersion(e.target.value === "latest" ? "latest" : Number(e.target.value))}
            className="rounded-md border border-border bg-panel px-2 py-1 text-xs"
          >
            <option value="latest">v{latest} (latest)</option>
            {doc.versions
              .slice(0, -1)
              .reverse()
              .map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version} — {v.note}
                </option>
              ))}
          </select>
        )}
        {latest > 0 && (
          <ExportMenu
            sessionId={session.id}
            version={viewVersion === "latest" ? undefined : viewVersion}
            refreshKey={`${latest}-${session.status}`}
            canImport={editable}
            onImported={onReload}
          />
        )}
        <UsageChip sessionId={session.id} refreshKey={`${latest}-${session.status}-${session.running}`} />
        <button
          onClick={onToggleWide}
          className="rounded-md p-1.5 text-muted hover:bg-sidebar hover:text-fg"
          title={wide ? "Show the chat again" : "Widen (hide the chat)"}
        >
          {wide ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
        </button>
        <button onClick={onClose} className="rounded-md p-1.5 text-muted hover:bg-sidebar hover:text-fg" title="Close">
          <X size={16} />
        </button>
      </header>

      <nav className="scroll-thin flex gap-1 overflow-x-auto border-b border-border px-3">
        {groups.map((g) => (
          <button
            key={g.id}
            onClick={() => group.id !== g.id && setTab(lastView[g.id] ?? g.views[0].id)}
            className={`-mb-px shrink-0 border-b-2 px-2.5 py-2 text-xs font-medium whitespace-nowrap ${
              group.id === g.id ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"
            }`}
          >
            {g.label}
            {g.id === "quality" && qa.report && qa.report.summary.errors > 0 && (
              <span className="ml-1 rounded-full bg-del px-1.5 text-[10px] text-del-fg">{qa.report.summary.errors}</span>
            )}
            {g.id === "segments" && proposal && proposal.changes.length > 0 && (
              <span className="ml-1 rounded-full bg-accent-soft px-1.5 text-[10px] text-accent" title="Proposed changes to review">
                {proposal.changes.length}
              </span>
            )}
          </button>
        ))}
      </nav>
      {group.views.length > 1 && (
        <div className="flex gap-1 border-b border-border bg-bg/60 px-4 py-1.5 text-xs">
          {group.views.map((v) => (
            <button
              key={v.id}
              onClick={() => pickView(v.id)}
              className={`rounded-full px-2.5 py-0.5 ${tab === v.id ? "bg-fg text-bg" : "text-muted hover:text-fg"}`}
            >
              {v.id === "source" && !direct ? "Page images & OCR" : v.label}
            </button>
          ))}
        </div>
      )}

      <div className="scroll-thin flex-1 overflow-y-auto px-6 py-5">
        {empty && <p className="text-sm text-muted">The document will appear here once OCR finishes.</p>}

        {checking && !empty && (tab === "translation" || tab === "parallel") && (
          <div className="mb-4 flex items-center gap-2 rounded-lg bg-warn/40 px-3 py-2 text-xs">
            <FileSearch size={13} className="shrink-0 text-warn-fg" />
            <span className="flex-1">This is the reading of the source (OCR). Nothing is translated until you continue.</span>
            <button onClick={() => pickView("source")} className="shrink-0 text-accent hover:underline">
              Compare with the page images
            </button>
          </div>
        )}

        {tab === "translation" && (doc.format === "xlsx" || doc.format === "pptx") && !empty && (
          <OfficeLayoutView key={session.id} sessionId={session.id} segments={segments} onOpen={openSegment} />
        )}

        {tab === "translation" && doc.format !== "xlsx" && doc.format !== "pptx" &&
          withPageBreaks((s) => (
            <SegmentShell key={s.id} seg={s} highlighted={highlight === s.id} onReference={onReference}>
              {s.kind === "header" || s.kind === "footer" ? (
                <div className="text-xs text-muted">
                  <span className="mr-1.5 text-[10px] tracking-wide uppercase">{s.kind}</span>
                  {direct ? <Markdown text={s.target ?? s.source} plain labels={s.codes} className="inline-block" /> : (s.target ?? s.source)}
                </div>
              ) : s.kind === "figure" ? (
                <FigureBlock sessionId={session.id} seg={s} legend={s.target ?? s.source} />
              ) : s.target ? (
                <Markdown text={s.target} plain={direct} labels={s.codes} heading={direct && s.kind === "heading"} />
              ) : checking ? (
                <Markdown text={s.source} plain={direct} labels={s.codes} heading={direct && s.kind === "heading"} />
              ) : session.status === "awaiting_answers" ? (
                <div className="flex items-baseline gap-1.5 text-muted">
                  <span className="shrink-0 text-[10px]">not translated yet</span>
                  <Markdown text={s.source} plain={direct} labels={s.codes} className="min-w-0 text-sm" />
                </div>
              ) : (
                <div className="animate-pulse text-sm text-muted italic">translating {s.id}…</div>
              )}
            </SegmentShell>
          ))}

        {tab === "parallel" &&
          withPageBreaks((s) => (
            <SegmentShell key={s.id} seg={s} highlighted={highlight === s.id} onReference={onReference}>
              {s.kind === "figure" ? (
                <div className="py-1">
                  <FigureBlock sessionId={session.id} seg={s} legend={null} />
                  {s.source && (
                    <div className="grid grid-cols-2 gap-5 text-xs whitespace-pre-line">
                      <div className="text-muted">{s.source}</div>
                      <div>{s.target ?? "…"}</div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-5 py-1">
                  <Markdown text={s.source} className="text-muted" plain={direct} labels={s.codes} />
                  {s.target ? <Markdown text={s.target} plain={direct} labels={s.codes} /> : <div className="text-sm text-muted italic">…</div>}
                </div>
              )}
            </SegmentShell>
          ))}

        {tab === "source" &&
          (direct ? (
            <DirectSourceView segments={segments} unit={unit} highlight={highlight} onReference={onReference} format={doc.format} />
          ) : (
            <SourceView sessionId={session.id} segments={segments} doc={doc} highlight={highlight} onReference={onReference} />
          ))}

        {tab === "changes" && (
          <div>
            {latest < 2 ? (
              <p className="text-sm text-muted">
                No changes yet. Versions are created after the draft translation, after review, and after each edit.
              </p>
            ) : (
              <>
                <div className="mb-4 flex items-center gap-2 text-xs">
                  <span className="text-muted">Compare</span>
                  <VersionSelect versions={doc.versions.map((v) => v.version)} value={compare.from} onChange={(from) => setCompare((c) => ({ ...c, from }))} />
                  <span className="text-muted">→</span>
                  <VersionSelect versions={doc.versions.map((v) => v.version)} value={compare.to} onChange={(to) => setCompare((c) => ({ ...c, to }))} />
                  <span className="ml-auto truncate text-muted">{doc.versions.find((v) => v.version === compare.to)?.note}</span>
                </div>
                <ChangesList
                  segments={doc.segments}
                  before={getSnap(compare.from)}
                  after={getSnap(compare.to)}
                  onReference={onReference}
                />
              </>
            )}
          </div>
        )}

        {tab === "checks" && <ChecksView doc={doc} onDraft={onDraft} />}

        {tab === "layout" &&
          (latest > 0 ? (
            <LayoutView
              sessionId={session.id}
              version={viewVersion === "latest" ? latest : viewVersion}
              segments={doc.segments}
              onReference={onReference}
            />
          ) : (
            <p className="text-sm text-muted">The layout preview appears once the first translation version exists.</p>
          ))}

        {tab === "segments" && (
          <SegmentGrid
            sessionId={session.id}
            doc={doc}
            hasProject={!!session.project_id}
            editable={editable}
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
            <p className="text-sm text-muted">Quality checks run once the pipeline has finished.</p>
          ))}
      </div>
    </section>
  );
}

function VersionSelect({ versions, value, onChange }: { versions: number[]; value: number; onChange: (v: number) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(Number(e.target.value))} className="rounded-md border border-border bg-panel px-2 py-1">
      {versions.map((v) => (
        <option key={v} value={v}>
          v{v}
        </option>
      ))}
    </select>
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
  if (before === null || after === null) return <p className="text-sm text-muted">This version isn&apos;t available any more.</p>;
  if (!before || !after) return <p className="text-sm text-muted">Loading versions…</p>;
  const changed = segments.filter((s) => (before[s.id] ?? "") !== (after[s.id] ?? ""));
  if (changed.length === 0) return <p className="text-sm text-muted">No differences between these versions.</p>;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        {changed.length} segment{changed.length === 1 ? "" : "s"} changed
      </p>
      {changed.map((s) => (
        <div key={s.id} className="rounded-lg border border-border p-3">
          <div className="mb-1.5 flex items-center justify-between">
            <button onClick={() => onReference(s.id)} className="font-mono text-[11px] text-muted hover:text-accent">
              {s.id}
            </button>
          </div>
          <div className="mb-2 line-clamp-3 text-xs text-muted">{s.source}</div>
          <DiffText before={before[s.id] ?? ""} after={after[s.id] ?? ""} />
        </div>
      ))}
    </div>
  );
}

/** Word, PowerPoint, Excel, XLIFF: no page images — the source text, with where each segment sits in the file. */
function DirectSourceView({
  segments,
  unit,
  format,
  highlight,
  onReference,
}: {
  segments: Segment[];
  unit: string;
  format: DocumentState["format"];
  highlight: string | null;
  onReference: (id: string) => void;
}) {
  const pages = [...new Set(segments.map((s) => s.page))];
  return (
    <div className="space-y-6">
      <p className="text-xs text-muted">
        Read directly from the {format === "xliff" ? "XLIFF" : format?.toUpperCase()} file (no OCR). Formatting, links, tabs and
        fields are kept as inline codes, so the translated file keeps them too.
      </p>
      {pages.map((p) => (
        <div key={p}>
          <div className="mb-2 text-xs font-medium">
            {unit} {p}
          </div>
          {segments
            .filter((s) => s.page === p)
            .map((s) => (
              <SegmentShell key={s.id} seg={s} highlighted={highlight === s.id} onReference={onReference}>
                <div className="flex gap-3">
                  <span className="w-36 shrink-0 truncate pt-1 text-[10px] text-muted" title={s.where}>
                    {s.where}
                  </span>
                  <Markdown text={s.source} plain labels={s.codes} heading={s.kind === "heading"} className="min-w-0 flex-1" />
                </div>
              </SegmentShell>
            ))}
        </div>
      ))}
    </div>
  );
}

function SourceView({
  sessionId,
  segments,
  doc,
  highlight,
  onReference,
}: {
  sessionId: string;
  segments: Segment[];
  doc: DocumentState;
  highlight: string | null;
  onReference: (id: string) => void;
}) {
  const pages = [...new Set(segments.map((s) => s.page))];
  const reports = new Map(doc.ocr_report.map((r) => [r.page, r]));
  return (
    <div className="space-y-8">
      {pages.map((p) => {
        const r = reports.get(p);
        return (
          <div key={p}>
            <div className="mb-2 flex items-center gap-2 text-xs">
              <span className="font-medium">Page {p}</span>
              {r &&
                (r.ok ? (
                  <span className="flex items-center gap-1 text-ins-fg">
                    <CheckCircle2 size={12} /> OCR verified
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-warn-fg">
                    <AlertTriangle size={12} /> OCR checker fixed {r.issues.length} issue{r.issues.length === 1 ? "" : "s"}
                  </span>
                ))}
              {r?.used_text_layer && <span className="text-muted">· cross-checked with PDF text layer</span>}
              {!!r?.suggestions?.length && (
                <span className="flex items-center gap-1 text-warn-fg">
                  · {r.suggestions.length} possible misreading{r.suggestions.length === 1 ? "" : "s"} to check
                </span>
              )}
              {!!r?.figures && (
                <span className="text-muted">
                  · {r.figures} figure{r.figures === 1 ? "" : "s"}
                  {r.figure_source ? ` (${r.figure_source.replace("layout", "page layout").replace("pdf", "PDF")})` : ""}
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-4">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={api.pageImageUrl(sessionId, p)}
                alt={`Page ${p}`}
                className="w-full rounded-md border border-border"
                onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
              />
              <div>
                {segments
                  .filter((s) => s.page === p)
                  .map((s) => (
                    <SegmentShell key={s.id} seg={s} highlighted={highlight === s.id} onReference={onReference}>
                      {s.kind === "figure" ? (
                        <FigureBlock sessionId={sessionId} seg={s} legend={s.source} muted />
                      ) : (
                        <Markdown text={s.source} />
                      )}
                    </SegmentShell>
                  ))}
              </div>
            </div>
            {r && !r.ok && r.issues.length > 0 && (
              <ul className="mt-2 list-disc pl-5 text-xs text-muted">
                {r.issues.map((i, k) => (
                  <li key={k}>Corrected: {i}</li>
                ))}
              </ul>
            )}
            {!!r?.suggestions?.length && (
              <div className="mt-2 rounded-md border border-warn-fg/30 bg-warn/40 px-3 py-2 text-xs">
                <div className="font-medium">Possible misreadings — not changed, please compare with the page image:</div>
                <ul className="mt-1 list-disc pl-5 text-fg/80">
                  {r.suggestions.map((i, k) => (
                    <li key={k}>{i}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ChecksView({ doc, onDraft }: { doc: DocumentState; onDraft: (text: string) => void }) {
  const glossary = Object.entries(doc.glossary);
  const termbase = Object.entries(doc.termbase ?? {});
  const issues = doc.review_report.flatMap((r) => r.issues.map((i) => ({ ...i, round: r.round })));
  const ocrFixed = doc.ocr_report.filter((r) => !r.ok);
  const flagged = doc.segments.filter((s) => s.flags?.length);
  return (
    <div className="space-y-6 text-sm">
      {flagged.length > 0 && (
        <section className="rounded-lg bg-warn/60 p-3">
          <h3 className="mb-1 font-semibold text-warn-fg">
            {flagged.length} segment{flagged.length === 1 ? "" : "s"} need{flagged.length === 1 ? "s" : ""} attention
          </h3>
          <p className="text-xs text-warn-fg">
            {flagged.map((s) => `${s.id} (${(s.flags ?? []).map((f) => FLAG_LABEL[f] ?? f).join(", ")})`).join(" · ")}
          </p>
        </section>
      )}
      {doc.tm_stats && (
        <section>
          <h3 className="mb-1 font-semibold">Translation memory</h3>
          <p className="text-sm">
            {doc.tm_stats.context + doc.tm_stats.exact} segment{doc.tm_stats.context + doc.tm_stats.exact === 1 ? "" : "s"} reused
            without a model call ({doc.tm_stats.context} in context · {doc.tm_stats.exact} exact · {doc.tm_stats.words} words) ·{" "}
            {doc.tm_stats.fuzzy} fuzzy match{doc.tm_stats.fuzzy === 1 ? "" : "es"} given to the translator to adapt
          </p>
        </section>
      )}
      {(doc.terms ?? []).length > 0 && (
        <section>
          <h3 className="mb-1 font-semibold">Project terms in this document</h3>
          <p className="mb-2 text-xs text-muted">From the project termbase — given to every agent; underlined in the Segments tab.</p>
          <table className="w-full text-left text-sm">
            <tbody>
              {doc.terms.map((t) => (
                <tr key={t.id} className="border-b border-border">
                  <td className="py-1.5 pr-3 font-medium">{t.source}</td>
                  <td className="py-1.5 pr-3">{t.target || <span className="text-muted">—</span>}</td>
                  <td className="py-1.5 text-xs text-muted">
                    {t.note}
                    {t.forbidden.length > 0 && <span className="text-del-fg"> · never: {t.forbidden.join(", ")}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <section>
        <h3 className="mb-1 font-semibold">Document brief</h3>
        <p className="mb-2 text-xs text-muted">
          Written after reading the whole document, before translating, and carried into every page (parties,
          abbreviations and defined terms, tone).
        </p>
        <p className="rounded-md bg-sidebar px-3 py-2 text-sm whitespace-pre-line">{doc.brief || "Not written yet."}</p>
      </section>
      {(doc.key_terms?.length ?? 0) > 0 && (
        <section>
          <h3 className="mb-1 font-semibold">Key terms</h3>
          <p className="mb-2 text-xs text-muted">
            Fixed once for the whole document before translating, with what each one means. Terms marked “asked” were
            decided by you (see the glossary below).
          </p>
          <table className="w-full text-left text-sm">
            <tbody>
              {doc.key_terms.map((k) => (
                <tr key={k.term} className="border-b border-border align-top">
                  <td className="py-1.5 pr-3 font-medium whitespace-nowrap">{k.term}</td>
                  <td className="py-1.5 pr-3 whitespace-nowrap">
                    {doc.glossary[k.term]?.target || k.target}
                    {k.asked && <span className="ml-1.5 rounded bg-accent-soft px-1 text-[10px] text-accent uppercase">asked</span>}
                  </td>
                  <td className="py-1.5 text-xs text-muted">
                    {k.meaning}
                    {k.dictionary?.map((d, i) => (
                      <span key={i} className="mt-0.5 flex items-start gap-1 text-fg/80">
                        <BookOpen size={11} className="mt-0.5 shrink-0" />
                        <span>
                          <span className="font-medium">{d.translation}</span>
                          {d.domain && ` · ${d.domain}`} ·{" "}
                          {d.url ? (
                            <a href={d.url} target="_blank" rel="noreferrer" className="underline">
                              {d.source || "Dictionary"}
                            </a>
                          ) : (
                            d.source || "Dictionary"
                          )}
                        </span>
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <section>
        <h3 className="mb-2 font-semibold">Glossary</h3>
        {glossary.length === 0 ? (
          <p className="text-muted">Empty. Terms are added when you answer questions or ask for terminology changes.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <tbody>
              {glossary.map(([term, e]) => (
                <tr key={term} className="border-b border-border">
                  <td className="py-1.5 pr-3 font-medium">{term}</td>
                  <td className="py-1.5 pr-3">{e.target}</td>
                  <td className="py-1.5 text-xs text-muted">{e.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section>
        <h3 className="mb-1 font-semibold">Terminology memory</h3>
        <p className="mb-2 text-xs text-muted">
          Term choices the translator made on earlier pages and reused on later ones. They are unverified — if one is
          wrong, change it and every page is updated.
        </p>
        {termbase.length === 0 ? (
          <p className="text-muted">None recorded.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <tbody>
              {termbase.map(([term, target]) => (
                <tr key={term} className="group border-b border-border">
                  <td className="py-1.5 pr-3 font-medium">{term}</td>
                  <td className="py-1.5">{target}</td>
                  <td className="py-1.5 text-right">
                    <button
                      onClick={() =>
                        onDraft(`"${term}" is currently translated as "${target}". Change it everywhere to: `)
                      }
                      className="rounded px-1.5 py-0.5 text-xs text-muted opacity-0 group-hover:opacity-100 hover:text-accent"
                    >
                      Change
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section>
        <h3 className="mb-2 font-semibold">OCR check</h3>
        <p className="text-muted">
          {doc.ocr_report.length} page{doc.ocr_report.length === 1 ? "" : "s"} checked ·{" "}
          {ocrFixed.length === 0 ? "no corrections needed" : `${ocrFixed.length} page(s) corrected`}
          {(() => {
            const n = doc.ocr_report.reduce((sum, r) => sum + (r.suggestions?.length ?? 0), 0);
            return n ? ` · ${n} possible misreading${n === 1 ? "" : "s"} to check (Source tab)` : "";
          })()}
        </p>
      </section>
      <section>
        <h3 className="mb-2 font-semibold">Translation review</h3>
        {issues.length === 0 ? (
          <p className="text-muted">No issues raised by the reviewer.</p>
        ) : (
          <ul className="space-y-1.5">
            {issues.map((i, k) => (
              <li key={k} className="flex gap-2">
                <span
                  className={`mt-0.5 h-fit shrink-0 rounded px-1.5 text-[10px] font-medium uppercase ${
                    i.severity === "minor" ? "bg-warn text-warn-fg" : "bg-del text-del-fg"
                  }`}
                >
                  {i.severity}
                </span>
                <span className="font-mono text-xs text-muted">{i.segment_id}</span>
                <span className="text-xs">{i.note}</span>
                <span className="ml-auto shrink-0 text-[10px] text-muted">round {i.round}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

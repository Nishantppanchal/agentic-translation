"use client";

import {
  ArrowDownWideNarrow,
  Bot,
  Check,
  CheckCheck,
  FilePenLine,
  Lightbulb,
  Lock,
  LockOpen,
  MessageSquare,
  Replace,
  Save,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { DocumentState, Proposal, ProposalChange, QaIssue, Role, Segment, SegmentStatus, StatusCounts, TaskKind, Term, TmMatch } from "@/lib/types";
import { DiffText } from "../document/Diff";
import { changeKey, type ProposalPick } from "../chat/proposalPick";
import { qeStyle } from "../document/QualityView";
import { FindReplace } from "./FindReplace";
import { TermCard, TermText, TmPanel } from "./TmPanel";
import { issuesBySegment, type QaState } from "./useQa";

type Filter = "all" | "todo" | "qa" | "comments" | "confirmed" | "proposed";
const FILTER_LABEL: Record<Filter, string> = {
  all: "All",
  todo: "To do",
  qa: "QA issues",
  comments: "Comments",
  confirmed: "Confirmed",
  proposed: "Proposed",
};
const openComments = (s: Segment) => (s.comments ?? []).filter((c) => !c.resolved).length;

/** One-click rewrite requests for selected segments (the result is a proposal to accept or reject). */
const QUICK_TASKS: { label: string; kind: TaskKind; instruction: string; n: number }[] = [
  { label: "More formal", kind: "retranslate", instruction: "More formal register.", n: 1 },
  { label: "Simpler", kind: "retranslate", instruction: "Simpler, plain language for non-experts.", n: 1 },
  { label: "Shorter", kind: "retranslate", instruction: "More concise: as short as possible without losing meaning.", n: 1 },
  { label: "3 alternatives", kind: "alternatives", instruction: "", n: 3 },
];

const STATUS_STYLE: Record<SegmentStatus, string> = {
  new: "bg-sidebar text-muted",
  draft: "bg-warn text-warn-fg",
  confirmed: "bg-ins text-ins-fg",
  reviewed: "bg-accent-soft text-accent",
};

/** Textarea that grows with its content (no clipped long segments). */
function AutoTextarea({ value, setRef, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { setRef: (el: HTMLTextAreaElement | null) => void }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight + 2}px`;
    };
    fit();
    // Re-fit when the column width changes (e.g. widening the panel), not only when the text does.
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (el.clientWidth !== width) {
        width = el.clientWidth;
        fit();
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [value]);
  return (
    <textarea
      {...props}
      value={value}
      rows={1}
      ref={(el) => {
        ref.current = el;
        setRef(el);
      }}
    />
  );
}
const ORIGIN_LABEL: Record<string, string> = {
  mt: "MT",
  agent: "AI edit",
  human: "Human",
  copy: "Copy",
  tm_exact: "TM 100%",
  tm_fuzzy: "TM fuzzy",
};

const originLabel = (seg: Segment) =>
  seg.origin?.startsWith("tm_") && seg.match ? `TM ${seg.match}%${seg.origin === "tm_fuzzy" ? " → MT" : ""}` : (ORIGIN_LABEL[seg.origin ?? ""] ?? seg.origin);

function counts(segments: Segment[]): StatusCounts {
  const c: StatusCounts = { new: 0, draft: 0, confirmed: 0, reviewed: 0, total: 0 };
  for (const s of segments) {
    if (!s.translatable) continue;
    c[s.status] += 1;
    c.total += 1;
  }
  return c;
}

/**
 * CAT-style segment editor: source | target (editable) | status.
 * Statuses are human work only: the translator confirms, a second (human) reviewer marks reviewed —
 * the AI reviewer's verdict is a separate "AI ✓" badge. The role switch decides what Ctrl+Enter does.
 * Keyboard: Ctrl/⌘+Enter confirm & next · Alt+↑/↓ move · Esc revert · Alt+S (or Ctrl+Shift+Insert) copy source ·
 * Alt+1–3 (or Ctrl+1–3) insert a translation-memory match. Project terms are underlined in the source.
 */
export function SegmentGrid({
  sessionId,
  doc,
  hasProject,
  editable,
  qa,
  focus,
  onSegment,
  onReload,
  onReference,
  onRunTask,
  proposal,
  pick,
  onAcceptProposal,
  onRejectProposal,
  onExplain,
  onFixIssue,
}: {
  sessionId: string;
  doc: DocumentState;
  hasProject: boolean; // translation memory lookups only exist inside a project
  editable: boolean; // false while agents run or the pipeline hasn't finished
  qa: QaState;
  focus: { id: string; n: number } | null; // jump here (e.g. from the Quality tab)
  onRunTask: (kind: TaskKind, segmentIds: string[], instruction: string, n: number) => Promise<void>;
  onSegment: (seg: Segment, humanDirty: string[]) => void;
  onReload: () => void;
  onReference: (id: string) => void;
  proposal: Proposal | null; // the agents' pending changes, reviewed here or in the chat card
  pick: ProposalPick;
  onAcceptProposal: (changes: string[] | null, choices: Record<string, number> | null) => Promise<void>;
  onRejectProposal: () => Promise<void>;
  onExplain: (segmentId: string) => void; // ask the agent what the source says (for non-speakers)
  onFixIssue: (segmentId: string, issue: QaIssue) => void; // ask the agent to fix one QA issue (as a proposal)
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const proposed = useMemo(
    () => new Map((proposal?.changes ?? []).filter((c) => c.field === "target").map((c) => [c.segment_id, c] as [string, ProposalChange])),
    [proposal],
  );
  const [deciding, setDeciding] = useState<"accept" | "reject" | null>(null);
  const decide = async (which: "accept" | "reject") => {
    setDeciding(which);
    try {
      if (which === "reject") await onRejectProposal();
      else await onAcceptProposal(...pick.acceptArgs(proposal?.changes ?? []));
    } finally {
      setDeciding(null);
    }
  };
  const [role, setRole] = useState<Role>("translator");
  const doneStatus: SegmentStatus = role === "translator" ? "confirmed" : "reviewed";
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"document" | "qe">("document");
  const [showReplace, setShowReplace] = useState(false);
  const qaBySeg = useMemo(() => issuesBySegment(qa.report), [qa.report]);
  const [drafts, _setDrafts] = useState<Record<string, string>>({});
  // Mirror drafts in a ref and track in-flight saves: Ctrl+Enter saves and moves focus, and the blur
  // that follows must not send a second (stale) save of the same segment.
  const draftsRef = useRef<Record<string, string>>({});
  const inflight = useRef(new Set<string>());
  const setDrafts = (update: (d: Record<string, string>) => Record<string, string>) => {
    draftsRef.current = update(draftsRef.current);
    _setDrafts(draftsRef.current);
  };
  const [active, setActive] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const lastClicked = useRef<string | null>(null);
  const [custom, setCustom] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refs = useRef(new Map<string, HTMLTextAreaElement>());
  const [tm, setTm] = useState<{ id: string; matches: TmMatch[]; loading: boolean } | null>(null);
  const tmCache = useRef(new Map<string, TmMatch[]>());
  const [hover, setHover] = useState<{ term: Term; rect: DOMRect } | null>(null);
  const terms = doc.terms ?? [];

  const loadTm = (seg: Segment) => {
    if (!hasProject || !seg.translatable) return setTm(null);
    const cached = tmCache.current.get(seg.id);
    setTm({ id: seg.id, matches: cached ?? [], loading: !cached });
    if (cached) return;
    api
      .segmentTm(sessionId, seg.id)
      .then(({ matches }) => {
        tmCache.current.set(seg.id, matches);
        setTm((t) => (t?.id === seg.id ? { id: seg.id, matches, loading: false } : t));
      })
      .catch(() => setTm((t) => (t?.id === seg.id ? { ...t, loading: false } : t)));
  };

  const insertMatch = (seg: Segment, target: string) => {
    setDrafts((d) => ({ ...d, [seg.id]: target }));
    refs.current.get(seg.id)?.focus();
  };

  const c = useMemo(() => counts(doc.segments), [doc.segments]);
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const shown = doc.segments.filter((s) => {
      if (s.id === focus?.id) return true; // a segment you jumped to is always visible
      if (filter === "todo" && (!s.translatable || (role === "translator" ? s.status !== "new" && s.status !== "draft" : s.status === "reviewed"))) return false;
      if (filter === "qa" && !s.flags?.length && !qaBySeg.has(s.id)) return false;
      if (filter === "confirmed" && s.status !== "confirmed") return false;
      if (filter === "comments" && !openComments(s)) return false;
      if (filter === "proposed" && !proposed.has(s.id)) return false;
      if (q && !s.source.toLowerCase().includes(q) && !(s.target ?? "").toLowerCase().includes(q)) return false;
      return true;
    });
    // Review queue order: lowest AI quality estimate first (unscored last).
    return sort === "qe" ? [...shown].sort((a, b) => (a.qe ?? 101) - (b.qe ?? 101)) : shown;
  }, [doc.segments, filter, query, role, qaBySeg, sort, focus, proposed]);

  const focusRow = useCallback((id: string | undefined) => {
    if (!id) return;
    const el = refs.current.get(id);
    el?.focus();
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);

  useEffect(() => {
    if (!focus) return;
    const frame = requestAnimationFrame(() => focusRow(focus.id));
    return () => cancelAnimationFrame(frame);
  }, [focus, focusRow]);

  /** Tick a row; shift-click ticks the range from the last ticked row. */
  const toggleSelect = (id: string, range: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      const ids = rows.map((r) => r.id);
      if (range && lastClicked.current && ids.includes(lastClicked.current)) {
        const [a, b] = [ids.indexOf(lastClicked.current), ids.indexOf(id)].sort((x, y) => x - y);
        for (const r of rows.slice(a, b + 1)) if (r.translatable && !r.locked) next.add(r.id);
      } else if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    lastClicked.current = id;
  };

  const runTask = async (kind: TaskKind, instruction: string, n: number) => {
    setError(null);
    try {
      await onRunTask(kind, [...selected], instruction, n);
      setSelected(new Set());
      setCustom("");
    } catch (e) {
      setError(String(e));
    }
  };

  const commentAction = async (fn: () => Promise<{ segment: Segment }>) => {
    setError(null);
    try {
      const res = await fn();
      onSegment(res.segment, doc.human_dirty);
    } catch (e) {
      setError(String(e));
    }
  };

  const neighbour = (id: string, dir: 1 | -1, predicate: (s: Segment) => boolean = () => true) => {
    const i = rows.findIndex((s) => s.id === id);
    for (let j = i + dir; j >= 0 && j < rows.length; j += dir) {
      if (!rows[j].locked && predicate(rows[j])) return rows[j].id;
    }
    return undefined;
  };

  const save = async (seg: Segment, confirm: boolean) => {
    if (inflight.current.has(seg.id)) return false;
    const draft = draftsRef.current[seg.id];
    const changed = draft !== undefined && draft !== (seg.target ?? "");
    if (!changed && !confirm) return true;
    inflight.current.add(seg.id);
    setBusy(seg.id);
    setError(null);
    try {
      const res = await api.editSegment(sessionId, seg.id, {
        target: changed ? draft : undefined,
        confirm,
        base_target: seg.target ?? "",
        role,
      });
      setDrafts((d) => {
        const next = { ...d };
        delete next[seg.id];
        return next;
      });
      if (confirm) tmCache.current.clear(); // confirmed segments go into the memory
      onSegment(res.segment, res.human_dirty);
      return true;
    } catch (e) {
      setError(String(e));
      return false;
    } finally {
      inflight.current.delete(seg.id);
      setBusy(null);
    }
  };

  const onKeyDown = async (e: React.KeyboardEvent<HTMLTextAreaElement>, seg: Segment) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key === "Enter") {
      e.preventDefault();
      if (await save(seg, true)) focusRow(neighbour(seg.id, 1, (s) => s.status !== doneStatus && s.status !== "reviewed" && s.translatable));
    } else if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      focusRow(neighbour(seg.id, e.key === "ArrowDown" ? 1 : -1));
    } else if (e.key === "Escape") {
      e.preventDefault();
      setDrafts((d) => {
        const next = { ...d };
        delete next[seg.id];
        return next;
      });
    } else if ((e.altKey && e.code === "KeyS") || (e.ctrlKey && e.shiftKey && e.key === "Insert")) {
      e.preventDefault();
      setDrafts((d) => ({ ...d, [seg.id]: seg.source }));
    } else if ((e.altKey || e.ctrlKey) && /^Digit[1-3]$/.test(e.code)) {
      const match = tm?.id === seg.id ? tm.matches[Number(e.code.slice(5)) - 1] : undefined;
      if (match) {
        e.preventDefault();
        insertMatch(seg, match.target);
      }
    }
  };

  const toggleLock = async (seg: Segment) => {
    try {
      const res = await api.lockSegment(sessionId, seg.id, !seg.locked);
      onSegment(res.segment, doc.human_dirty);
    } catch (e) {
      setError(String(e));
    }
  };

  const bulk = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      tmCache.current.clear();
      onReload();
    } catch (e) {
      setError(String(e));
    }
  };

  const done = c.confirmed + c.reviewed;
  const pct = c.total ? Math.round((100 * done) / c.total) : 0;
  const pending = doc.human_dirty?.length ?? 0;
  const aiPassedDrafts = doc.segments.filter((s) => s.translatable && !s.locked && s.status === "draft" && s.ai_check === "passed").length;

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="sticky top-0 z-10 -mx-6 -mt-5 mb-3 space-y-2 border-b border-border bg-panel px-6 pt-3 pb-2.5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
          <div className="min-w-[180px] flex-1">
            <div className="mb-1 flex justify-between text-muted">
              <span>
                <b className="text-fg">{done}</b>/{c.total} done · {c.reviewed} reviewed · {c.confirmed} confirmed ·{" "}
                {c.draft} draft{c.new ? ` · ${c.new} new` : ""}
              </span>
              <span>{pct}%</span>
            </div>
            <div className="flex h-1.5 overflow-hidden rounded-full bg-sidebar">
              <div className="bg-accent/70" style={{ width: `${c.total ? (100 * c.reviewed) / c.total : 0}%` }} />
              <div className="bg-ins-fg/70" style={{ width: `${c.total ? (100 * c.confirmed) / c.total : 0}%` }} />
            </div>
          </div>
          <div className="flex overflow-hidden rounded-md border border-border" title="What Ctrl+Enter does">
            {(["translator", "reviewer"] as Role[]).map((r) => (
              <button
                key={r}
                onClick={() => setRole(r)}
                className={`px-2 py-1 capitalize ${role === r ? "bg-fg text-bg" : "text-muted hover:text-fg"}`}
              >
                {r}
              </button>
            ))}
          </div>
          {role === "translator" ? (
            <button
              disabled={!editable || aiPassedDrafts === 0}
              onClick={() => bulk(() => api.confirmSegments(sessionId, null, "translator"))}
              className="flex items-center gap-1 rounded-md border border-border px-2 py-1 whitespace-nowrap hover:border-accent disabled:opacity-40"
              title="Confirm every draft the AI reviewer found no major problem in. Not added to the translation memory: confirm segments one by one (Ctrl+Enter) to store them as approved wording"
            >
              <CheckCheck size={13} /> Confirm AI-checked ({aiPassedDrafts})
            </button>
          ) : (
            <button
              disabled={!editable || c.confirmed === 0}
              onClick={() => bulk(() => api.confirmSegments(sessionId, null, "reviewer"))}
              className="flex items-center gap-1 rounded-md border border-border px-2 py-1 whitespace-nowrap hover:border-accent disabled:opacity-40"
              title="Second-linguist sign-off: mark every confirmed segment as reviewed"
            >
              <CheckCheck size={13} /> Mark confirmed as reviewed ({c.confirmed})
            </button>
          )}
          <button
            onClick={() => setShowReplace((v) => !v)}
            className={`flex items-center gap-1 rounded-md border px-2 py-1 ${showReplace ? "border-accent text-accent" : "border-border hover:border-accent"}`}
            title="Find & replace in the translations"
          >
            <Replace size={13} /> Replace
          </button>
          <button
            disabled={!editable || pending === 0}
            onClick={() => bulk(() => api.saveVersion(sessionId))}
            className="flex items-center gap-1 rounded-md bg-accent px-2 py-1 whitespace-nowrap text-white disabled:opacity-40"
            title="Save your edits as a new version (also happens automatically before agent runs and exports)"
          >
            <Save size={13} /> Save version{pending ? ` (${pending})` : ""}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          {(["all", "todo", "qa", "comments", "confirmed", ...(proposed.size ? ["proposed"] : [])] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-full px-2.5 py-0.5 whitespace-nowrap ${filter === f ? "bg-fg text-bg" : "bg-sidebar text-muted hover:text-fg"}`}
            >
              {FILTER_LABEL[f]}
              {f === "qa" && qaBySeg.size > 0 && <span className="ml-1 opacity-70">{qaBySeg.size}</span>}
              {f === "proposed" && <span className="ml-1 opacity-70">{proposed.size}</span>}
            </button>
          ))}
          <button
            onClick={() => setSort((v) => (v === "qe" ? "document" : "qe"))}
            className={`flex items-center gap-1 rounded-full px-2.5 py-0.5 whitespace-nowrap ${sort === "qe" ? "bg-fg text-bg" : "bg-sidebar text-muted hover:text-fg"}`}
            title="Review queue: lowest AI quality estimate first"
          >
            <ArrowDownWideNarrow size={12} /> Lowest score first
          </button>
          <label className="ml-auto flex items-center gap-1 rounded-md border border-border px-2 py-0.5">
            <Search size={12} className="text-muted" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter text…"
              className="w-36 bg-transparent outline-none"
            />
          </label>
        </div>
        <div className="text-[10px] text-muted">
          {editable
            ? `⌘/Ctrl+Enter ${role === "translator" ? "confirm" : "mark reviewed"} & next · Alt+↑/↓ move · Esc revert · Alt+S copy source${hasProject ? " · Alt+1–3 insert TM match" : ""} · edits save when you leave a segment · "AI ✓" = passed the AI review (not a human check)`
            : "Read-only while the agents are working — editing unlocks when the pipeline finishes."}
        </div>
        {error && <div className="rounded bg-del px-2 py-1 text-xs text-del-fg">{error}</div>}
        {proposed.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-accent/40 bg-accent-soft px-2 py-1.5 text-xs">
            <FilePenLine size={13} className="text-accent" />
            <b>
              The agent proposes {proposed.size} change{proposed.size === 1 ? "" : "s"}
            </b>
            <span className="text-muted">— shown under each segment; untick what you don&apos;t want.</span>
            <span className="ml-auto flex gap-1.5">
              <button
                onClick={() => decide("reject")}
                disabled={!!deciding}
                className="flex items-center gap-1 rounded-md px-2 py-0.5 text-muted hover:text-del-fg disabled:opacity-40"
              >
                <X size={12} /> Reject all
              </button>
              <button
                onClick={() => decide("accept")}
                disabled={!!deciding || [...proposed.keys()].every((id) => pick.excluded.has(`${id}|target`))}
                className="flex items-center gap-1 rounded-md bg-accent px-2 py-0.5 font-medium text-white disabled:opacity-40"
              >
                <Check size={12} />
                {pick.excluded.size
                  ? `Apply ${[...proposed.keys()].filter((id) => !pick.excluded.has(`${id}|target`)).length} selected`
                  : "Apply all"}
              </button>
            </span>
          </div>
        )}
        {selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 rounded-md bg-accent-soft px-2 py-1.5 text-xs">
            <Sparkles size={13} className="text-accent" />
            <b>{selected.size} selected</b> — ask the agent to rewrite:
            {QUICK_TASKS.map((t) => (
              <button
                key={t.label}
                disabled={!editable}
                onClick={() => runTask(t.kind, t.instruction, t.n)}
                className="rounded-md border border-accent/40 bg-panel px-2 py-0.5 hover:border-accent disabled:opacity-40"
              >
                {t.label}
              </button>
            ))}
            <input
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && custom.trim() && editable && runTask("retranslate", custom.trim(), 1)}
              placeholder="or your own instruction, Enter"
              className="w-56 rounded-md border border-border bg-panel px-2 py-0.5 outline-none focus:border-accent"
            />
            <span className="text-muted">Results come back as a proposal to accept or reject.</span>
            <button onClick={() => setSelected(new Set())} className="ml-auto p-0.5 text-muted hover:text-fg" title="Clear selection">
              <X size={13} />
            </button>
          </div>
        )}
      </div>
      {showReplace && (
        <FindReplace
          sessionId={sessionId}
          editable={editable}
          onApplied={() => {
            tmCache.current.clear();
            onReload();
            qa.refresh();
          }}
          onClose={() => setShowReplace(false)}
        />
      )}

      {/* Rows */}
      <div className="divide-y divide-border">
        {rows.map((seg) => {
          const draft = drafts[seg.id];
          const value = draft ?? seg.target ?? "";
          const dirty = draft !== undefined && draft !== (seg.target ?? "");
          const canEdit = editable && !seg.locked && seg.translatable;
          const issues = qaBySeg.get(seg.id) ?? [];
          const errors = issues.filter((i) => i.severity === "error").length;
          return (
            <div
              key={seg.id}
              className={`grid grid-cols-[64px_1fr_1fr_96px] gap-3 py-2 [content-visibility:auto] ${
                active === seg.id ? "bg-accent-soft/40" : selected.has(seg.id) ? "bg-accent-soft/20" : ""
              }`}
            >
              <div className="self-start pt-1">
              {seg.translatable && !seg.locked && (
                <input
                  type="checkbox"
                  checked={selected.has(seg.id)}
                  onChange={() => undefined}
                  onClick={(e) => toggleSelect(seg.id, e.shiftKey)}
                  className="mr-1 align-middle accent-[var(--accent)]"
                  title="Select (shift-click for a range) to rewrite with the agent"
                  aria-label={`Select ${seg.id}`}
                />
              )}
              <button
                onClick={() => onReference(seg.id)}
                className="text-left align-middle font-mono text-[10px] text-muted hover:text-accent"
                title="Reference in chat"
              >
                {seg.id}
                {(seg.kind === "header" || seg.kind === "footer") && (
                  <span className="block text-[9px] tracking-wide text-muted uppercase">{seg.kind}</span>
                )}
              </button>
              </div>
              <div className="text-sm whitespace-pre-wrap text-muted">
                {seg.kind === "figure" && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={api.figureUrl(sessionId, seg.image ?? "")} alt="" className="mb-1 max-h-24 rounded border border-border" />
                )}
                <TermText
                  text={seg.source}
                  terms={terms}
                  onHover={(term, el) => setHover(term && el ? { term, rect: el.getBoundingClientRect() } : null)}
                />
              </div>
              <AutoTextarea
                setRef={(el) => {
                  if (el) refs.current.set(seg.id, el);
                  else refs.current.delete(seg.id);
                }}
                value={value}
                readOnly={!canEdit}
                onChange={(e) => setDrafts((d) => ({ ...d, [seg.id]: e.target.value }))}
                onFocus={() => {
                  setActive(seg.id);
                  if (tm?.id !== seg.id) loadTm(seg);
                }}
                onBlur={() => canEdit && save(seg, false)}
                onKeyDown={(e) => canEdit && onKeyDown(e, seg)}
                className={`w-full self-start resize-none overflow-hidden rounded-md border bg-bg px-2 py-1 text-sm outline-none ${
                  dirty ? "border-warn-fg" : "border-transparent"
                } ${canEdit ? "focus:border-accent" : "cursor-default opacity-80"}`}
              />
              <div className="flex flex-col items-start gap-1 pt-1 text-[10px]">
                <span className={`rounded px-1.5 py-0.5 font-medium capitalize ${STATUS_STYLE[seg.status]}`}>
                  {busy === seg.id ? "saving…" : seg.status}
                </span>
                {seg.origin && <span className="text-muted">{originLabel(seg)}</span>}
                {seg.qe != null && (
                  <span className={`font-medium ${qeStyle(seg.qe)}`} title="AI quality estimate (0-100) from the last review or LQA">
                    QE {seg.qe}
                  </span>
                )}
                {issues.length > 0 && (
                  <span
                    className={`rounded px-1 ${errors ? "bg-del text-del-fg" : "bg-warn text-warn-fg"}`}
                    title={issues.map((i) => `${i.label}: ${i.message}`).join("\n")}
                  >
                    QA {issues.length}
                  </span>
                )}
                {seg.ai_check && (
                  <span
                    className={`flex items-center gap-0.5 ${seg.ai_check === "passed" ? "text-ins-fg" : "text-warn-fg"}`}
                    title={seg.ai_check === "passed" ? "The AI reviewer found no major problem (not a human review)" : "The AI reviewer raised a major issue"}
                  >
                    <Bot size={11} /> {seg.ai_check === "passed" ? "AI ✓" : "AI: issues"}
                  </span>
                )}
                {seg.flags?.map((f) => (
                  <span key={f} className="rounded bg-warn px-1 text-warn-fg">
                    {f}
                  </span>
                ))}
                {(seg.comments?.length ?? 0) > 0 && (
                  <button
                    onClick={() => refs.current.get(seg.id)?.focus()}
                    className={`flex items-center gap-0.5 ${openComments(seg) ? "text-accent" : "text-muted"}`}
                    title={`${openComments(seg)} open comment${openComments(seg) === 1 ? "" : "s"}`}
                  >
                    <MessageSquare size={11} /> {openComments(seg) || "✓"}
                  </button>
                )}
                {seg.translatable && (
                  <button
                    onClick={() => onExplain(seg.id)}
                    className="flex items-center gap-0.5 text-muted hover:text-accent"
                    title="Ask the agent what the source says and whether the translation carries it (answer only, no edits)"
                  >
                    <Lightbulb size={11} /> explain
                  </button>
                )}
                {seg.translatable && (
                  <button
                    disabled={!editable}
                    onClick={() => toggleLock(seg)}
                    className="flex items-center gap-0.5 text-muted hover:text-fg disabled:opacity-40"
                    title={seg.locked ? "Unlock (agents and edits allowed)" : "Lock (no one may change it)"}
                  >
                    {seg.locked ? <Lock size={11} /> : <LockOpen size={11} />}
                    {seg.locked ? "locked" : "lock"}
                  </button>
                )}
              </div>
              {proposed.has(seg.id) && (
                <ProposedChange change={proposed.get(seg.id)!} pick={pick} disabled={!!deciding} />
              )}
              {issues.length > 0 && (
                // Always visible: what's wrong with this segment, not just a count.
                <ul
                  className={`col-span-4 -mt-1 mb-1 ml-[76px] space-y-0.5 rounded-md border-l-2 bg-bg px-3 py-1.5 text-xs ${
                    errors ? "border-del-fg" : "border-warn-fg"
                  }`}
                >
                  {issues.map((i) => (
                    <li key={i.id} className="group/issue flex items-start gap-2">
                      <span className={`mt-0.5 shrink-0 rounded px-1 text-[10px] font-medium uppercase ${i.severity === "error" ? "bg-del text-del-fg" : "bg-warn text-warn-fg"}`}>
                        {i.severity}
                      </span>
                      <span className="shrink-0 text-muted">{i.label}</span>
                      <span className="flex-1">{i.message}</span>
                      {editable && (
                        <button
                          onMouseDown={(e) => e.preventDefault()} // keep focus in the target box
                          onClick={() => onFixIssue(seg.id, i)}
                          className="shrink-0 text-accent hover:underline"
                          title="Ask the agent to fix this — the change comes back as a proposal"
                        >
                          Fix
                        </button>
                      )}
                      <button
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => qa.ignore([i.id])}
                        className="shrink-0 text-muted hover:text-fg"
                        title="Ignore (comes back if the text changes)"
                      >
                        Ignore
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {active === seg.id && (
                <div className="col-span-4 -mt-1 mb-1 ml-[76px] rounded-md border border-border bg-bg px-3 py-2 text-xs">
                  <div className="mb-1 flex items-center gap-1.5 font-medium text-muted">
                    <MessageSquare size={12} /> Comments
                  </div>
                  {(seg.comments ?? []).map((c) => (
                    <div key={c.id} className={`group mb-1 flex items-start gap-2 ${c.resolved ? "opacity-50" : ""}`}>
                      <span className="shrink-0 rounded bg-sidebar px-1 text-[10px] text-muted capitalize">{c.role}</span>
                      <span className={`flex-1 ${c.resolved ? "line-through" : ""}`}>{c.text}</span>
                      <button
                        disabled={!editable}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => commentAction(() => api.resolveComment(sessionId, seg.id, c.id, !c.resolved))}
                        className="shrink-0 text-muted hover:text-fg disabled:opacity-40"
                      >
                        {c.resolved ? "Reopen" : "Resolve"}
                      </button>
                      <button
                        disabled={!editable}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => commentAction(() => api.deleteComment(sessionId, seg.id, c.id))}
                        className="shrink-0 text-muted opacity-0 group-hover:opacity-100 hover:text-del-fg disabled:opacity-40"
                        title="Delete"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                  <input
                    value={comment}
                    disabled={!editable}
                    onChange={(e) => setComment(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && comment.trim()) {
                        e.preventDefault();
                        commentAction(() => api.addComment(sessionId, seg.id, comment.trim(), role)).then(() => setComment(""));
                      }
                    }}
                    placeholder={`Add a comment as ${role} — Enter to post`}
                    className="w-full rounded border border-border bg-panel px-2 py-1 outline-none focus:border-accent disabled:opacity-50"
                  />
                </div>
              )}
              {hasProject && active === seg.id && tm?.id === seg.id && (
                <TmPanel
                  source={seg.source}
                  matches={tm.matches}
                  loading={tm.loading}
                  editable={canEdit}
                  onInsert={(target) => insertMatch(seg, target)}
                />
              )}
            </div>
          );
        })}
        {rows.length === 0 && <p className="py-6 text-center text-sm text-muted">No segments match.</p>}
      </div>
      {hover && <TermCard term={hover.term} anchor={hover.rect} />}
    </div>
  );
}

/** A pending agent change shown in place, under the segment: include it or not, or pick an alternative. */
function ProposedChange({ change, pick, disabled }: { change: ProposalChange; pick: ProposalPick; disabled: boolean }) {
  const k = changeKey(change);
  const included = !pick.excluded.has(k);
  const alternatives = change.alternatives ?? [];
  return (
    <div className="col-span-4 -mt-1 mb-1 ml-[76px] rounded-md border border-accent/40 bg-accent-soft/30 px-3 py-2 text-xs">
      <label className="mb-1 flex cursor-pointer items-center gap-1.5 font-medium text-accent">
        <input
          type="checkbox"
          checked={included}
          disabled={disabled}
          onChange={(e) => pick.include(k, e.target.checked)}
          className="accent-[var(--accent)]"
        />
        Proposed change{alternatives.length ? ` — pick one of ${alternatives.length}` : ""}
      </label>
      <div className={included ? "" : "opacity-40"}>
        {alternatives.length ? (
          <div className="space-y-1">
            {alternatives.map((alt, i) => (
              <label key={i} className="flex cursor-pointer items-start gap-2">
                <input
                  type="radio"
                  name={`grid-alt-${k}`}
                  className="mt-0.5 accent-[var(--accent)]"
                  checked={(pick.choices[k] ?? 0) === i}
                  disabled={disabled || !included}
                  onChange={() => pick.choose(k, i)}
                />
                <span className="min-w-0 flex-1 text-sm">
                  <DiffText before={change.before} after={alt.text} />
                  {alt.note && <span className="block text-[11px] text-muted">{alt.note}</span>}
                </span>
              </label>
            ))}
          </div>
        ) : (
          <div className="text-sm">
            <DiffText before={change.before} after={change.after} />
          </div>
        )}
      </div>
    </div>
  );
}

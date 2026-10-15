"use client";

import {
  ArrowDownWideNarrow,
  Bot,
  Check,
  CheckCheck,
  Database,
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
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { rise } from "@/lib/motion";
import { REWRITES } from "@/lib/rewrites";
import type { DocumentState, Proposal, ProposalChange, QaIssue, Role, Segment, SegmentStatus, StatusCounts, TaskKind, Term, TmMatch } from "@/lib/types";
import { RewriteMenu } from "../document/RewriteMenu";
import { RichDiff } from "../document/RichDiff";
import { CommentThread } from "./CommentThread";
import { changeKey, type ProposalPick } from "../chat/proposalPick";
import { qeStyle, SeverityBadge } from "../document/QualityView";
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

const STATUS_STYLE: Record<SegmentStatus, string> = {
  new: "bg-muted text-muted-foreground",
  draft: "bg-warn text-warn-fg",
  confirmed: "bg-ins text-ins-fg",
  reviewed: "bg-primary-soft text-primary",
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
  tm: "TM",
};

/** How the current text was made: "TM 101%" (reused), "MT · TM 87%" (the translator adapted a fuzzy match). */
const originLabel = (seg: Segment) =>
  seg.origin === "tm" && seg.match
    ? `TM ${seg.match}%`
    : seg.origin === "mt" && seg.match
      ? `MT · TM ${seg.match}%`
      : (ORIGIN_LABEL[seg.origin ?? ""] ?? seg.origin);

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
  canComment,
  role,
  setRole,
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
  canComment: boolean; // comments: any status, as long as nothing is running
  role: Role; // translator or reviewer: what confirming means, and who comments
  setRole: (r: Role) => void;
  qa: QaState;
  focus: { id: string; n: number } | null; // jump here (e.g. from the Quality tab)
  onRunTask: (kind: TaskKind, segmentIds: string[], instruction: string, n: number) => Promise<void>;
  onSegment: (seg: Segment, humanDirty: string[]) => void;
  onReload: () => void;
  onReference: (id: string) => void;
  proposal: Proposal | null; // the agents' pending changes, reviewed here or in the chat card
  pick: ProposalPick;
  onAcceptProposal: (changes: string[] | null, choices: Record<string, number> | null, confirm?: boolean) => Promise<void>;
  onRejectProposal: () => Promise<void>;
  onExplain: (segmentId: string) => void; // ask the agent what the source says (for non-speakers)
  onFixIssue: (segmentId: string, issue: QaIssue) => void; // ask the agent to fix one QA issue (as a proposal)
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const proposed = useMemo(
    () => new Map((proposal?.changes ?? []).filter((c) => c.field === "target").map((c) => [c.segment_id, c] as [string, ProposalChange])),
    [proposal],
  );
  const [deciding, setDeciding] = useState<"accept" | "confirm" | "reject" | null>(null);
  const decide = async (which: "accept" | "confirm" | "reject") => {
    setDeciding(which);
    try {
      if (which === "reject") await onRejectProposal();
      else await onAcceptProposal(...pick.acceptArgs(proposal?.changes ?? []), which === "confirm");
    } finally {
      setDeciding(null);
    }
  };
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
  const [thread, setThread] = useState<string | null>(null); // the row whose comments are open
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

  const onCommented = (seg: Segment | null) => (seg ? onSegment(seg, doc.human_dirty) : onReload());

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
      <div className="sticky -top-5 z-10 -mx-6 -mt-5 mb-3 space-y-2.5 border-b border-border bg-card/95 px-6 pt-3 pb-3 backdrop-blur">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
          <div className="min-w-[180px] flex-1">
            <div className="mb-1.5 flex justify-between text-muted-foreground">
              <span>
                <b className="text-foreground tabular-nums">{done}</b>/{c.total} done · {c.reviewed} reviewed · {c.confirmed} confirmed ·{" "}
                {c.draft} draft{c.new ? ` · ${c.new} new` : ""}
              </span>
              <span className="tabular-nums">{pct}%</span>
            </div>
            <div className="flex h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="bg-primary transition-[width] duration-500" style={{ width: `${c.total ? (100 * c.reviewed) / c.total : 0}%` }} />
              <div className="bg-ins-fg/70 transition-[width] duration-500" style={{ width: `${c.total ? (100 * c.confirmed) / c.total : 0}%` }} />
            </div>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <ToggleGroup
                  type="single"
                  variant="outline"
                  size="sm"
                  value={role}
                  onValueChange={(v) => v && setRole(v as Role)}
                  aria-label="Your role: what Ctrl+Enter does"
                >
                  {(["translator", "reviewer"] as Role[]).map((r) => (
                    <ToggleGroupItem key={r} value={r} className="h-7 px-2.5 text-xs capitalize data-[state=on]:bg-foreground data-[state=on]:text-background">
                      {r}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </span>
            </TooltipTrigger>
            <TooltipContent>Your role: what Ctrl+Enter does, and who your comments are from</TooltipContent>
          </Tooltip>
          {role === "translator" ? (
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              disabled={!editable || aiPassedDrafts === 0}
              onClick={() => bulk(() => api.confirmSegments(sessionId, null, "translator"))}
              title="Confirm every draft the AI reviewer found no major problem in. They go into the translation memory marked as confirmed in bulk (never auto-confirmed later)."
            >
              <CheckCheck /> Confirm AI-checked ({aiPassedDrafts})
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              disabled={!editable || c.confirmed === 0}
              onClick={() => bulk(() => api.confirmSegments(sessionId, null, "reviewer"))}
              title="Second-linguist sign-off: mark every confirmed segment as reviewed"
            >
              <CheckCheck /> Mark confirmed as reviewed ({c.confirmed})
            </Button>
          )}
          <Toggle
            size="sm"
            variant="outline"
            pressed={showReplace}
            onPressedChange={setShowReplace}
            className="h-7 text-xs data-[state=on]:border-primary/50 data-[state=on]:bg-primary-soft data-[state=on]:text-primary"
            aria-label="Find and replace in the translations"
          >
            <Replace /> Replace
          </Toggle>
          <Button
            size="sm"
            className="h-7 text-xs"
            disabled={!editable || pending === 0}
            onClick={() => bulk(() => api.saveVersion(sessionId))}
            title="Save your edits as a new version (also happens automatically before agent runs and exports)"
          >
            <Save /> Save version{pending ? ` (${pending})` : ""}
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <ToggleGroup type="single" value={filter} onValueChange={(v) => v && setFilter(v as Filter)} className="flex-wrap justify-start gap-1" aria-label="Show">
            {(["all", "todo", "qa", "comments", "confirmed", ...(proposed.size ? ["proposed"] : [])] as Filter[]).map((f) => (
              <ToggleGroupItem
                key={f}
                value={f}
                className="h-6 min-w-0 rounded-full bg-muted px-2.5 text-xs whitespace-nowrap text-muted-foreground data-[state=on]:bg-foreground data-[state=on]:text-background"
              >
                {FILTER_LABEL[f]}
                {f === "qa" && qaBySeg.size > 0 && <span className="tabular-nums opacity-70">{qaBySeg.size}</span>}
                {f === "proposed" && <span className="tabular-nums opacity-70">{proposed.size}</span>}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <Toggle
            pressed={sort === "qe"}
            onPressedChange={(on) => setSort(on ? "qe" : "document")}
            className="h-6 min-w-0 rounded-full bg-muted px-2.5 text-xs whitespace-nowrap text-muted-foreground data-[state=on]:bg-foreground data-[state=on]:text-background"
            title="Review queue: lowest AI quality estimate first"
          >
            <ArrowDownWideNarrow className="size-3" /> Lowest score first
          </Toggle>
          <div className="relative ml-auto">
            <Search size={13} className="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-muted-foreground" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter text…" className="h-7 w-44 pl-7 text-xs" aria-label="Filter segments by text" />
          </div>
        </div>
        <div className="text-[10px] text-muted-foreground">
          {editable
            ? `⌘/Ctrl+Enter ${role === "translator" ? "confirm" : "mark reviewed"} & next · Alt+↑/↓ move · Esc revert · Alt+S copy source${hasProject ? " · Alt+1–3 insert TM match" : ""} · edits save when you leave a segment · "AI ✓" = passed the AI review (not a human check)`
            : "Read-only while the agents are working — editing unlocks when the pipeline finishes."}
        </div>
        {error && <div className="rounded-md bg-del px-2 py-1 text-xs text-del-fg">{error}</div>}
        <AnimatePresence initial={false}>
          {proposed.size > 0 && (
            <motion.div key="proposal" {...rise} className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-primary-soft px-3 py-2 text-xs">
              <FilePenLine size={14} className="text-primary" />
              <b>
                The agent proposes {proposed.size} change{proposed.size === 1 ? "" : "s"}
              </b>
              <span className="text-muted-foreground">— shown under each segment; untick what you don&apos;t want.</span>
              <span className="ml-auto flex gap-1.5">
                <Button variant="ghost" size="xs" onClick={() => decide("reject")} disabled={!!deciding} className="text-muted-foreground hover:text-del-fg">
                  <X /> Reject all
                </Button>
                <Button
                  variant="outline"
                  size="xs"
                  onClick={() => decide("confirm")}
                  disabled={!!deciding || [...proposed.keys()].every((id) => pick.excluded.has(`${id}|target`))}
                  title="Apply, and confirm the new translations (they go into the project's translation memory)"
                >
                  <CheckCheck /> Apply &amp; confirm
                </Button>
                <Button size="xs" onClick={() => decide("accept")} disabled={!!deciding || [...proposed.keys()].every((id) => pick.excluded.has(`${id}|target`))}>
                  <Check />
                  {pick.excluded.size
                    ? `Apply ${[...proposed.keys()].filter((id) => !pick.excluded.has(`${id}|target`)).length} selected`
                    : "Apply all"}
                </Button>
              </span>
            </motion.div>
          )}
          {selected.size > 0 && (
            <motion.div key="selection" {...rise} className="flex flex-wrap items-center gap-1.5 rounded-lg bg-primary-soft px-3 py-2 text-xs">
              <Sparkles size={14} className="text-primary" />
              <b>{selected.size} selected</b> — ask the agent to rewrite:
              {REWRITES.map((t) => (
                <Button key={t.label} variant="outline" size="xs" disabled={!editable} onClick={() => runTask(t.kind, t.instruction, t.n)} title={t.hint} className="bg-card">
                  {t.label}
                </Button>
              ))}
              <Input
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && custom.trim() && editable && runTask("retranslate", custom.trim(), 1)}
                placeholder="or your own instruction, Enter"
                className="h-6 w-56 bg-card text-xs"
                aria-label="Your own rewrite instruction"
              />
              <span className="text-muted-foreground">Results come back as a proposal to accept or reject.</span>
              <Button variant="ghost" size="icon-xs" onClick={() => setSelected(new Set())} className="ml-auto" aria-label="Clear selection">
                <X />
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
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
              className={`group/row grid grid-cols-[72px_1fr_1fr_104px] gap-3 py-2.5 transition-colors [content-visibility:auto] ${
                active === seg.id ? "bg-primary-soft/50" : selected.has(seg.id) ? "bg-primary-soft/25" : "hover:bg-muted/30"
              }`}
            >
              <div className="flex items-start gap-1.5 self-start pt-1">
              {seg.translatable && !seg.locked && (
                <Checkbox
                  checked={selected.has(seg.id)}
                  onClick={(e) => toggleSelect(seg.id, e.shiftKey)}
                  className="mt-px size-3.5"
                  title="Select (shift-click for a range) to rewrite with the agent"
                  aria-label={`Select ${seg.id}`}
                />
              )}
              <button
                onClick={() => onReference(seg.id)}
                className="min-w-0 text-left font-mono text-[10px] text-muted-foreground hover:text-primary"
                title="Reference in chat"
              >
                {seg.id}
                {(seg.kind === "header" || seg.kind === "footer" || seg.kind === "alt" || (seg.kind === "figure" && !!seg.loc)) && (
                  <span className="block text-[9px] tracking-wide text-muted-foreground uppercase">
                    {seg.kind === "alt" ? "Alt text" : seg.kind === "figure" ? "Picture" : seg.kind}
                  </span>
                )}
                {seg.where && seg.where !== "Body" && (
                  <span className="mt-0.5 block text-[9px] leading-tight break-words text-muted-foreground" title={seg.where}>
                    {seg.where.length > 28 ? `${seg.where.slice(0, 27)}…` : seg.where}
                  </span>
                )}
              </button>
              </div>
              <div className="text-sm whitespace-pre-wrap text-muted-foreground">
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
                className={`w-full self-start resize-none overflow-hidden rounded-md border bg-background px-2 py-1 text-sm transition-[border-color,box-shadow] outline-none ${
                  dirty ? "border-warn-fg" : "border-transparent"
                } ${canEdit ? "hover:border-border focus:border-ring focus:ring-[3px] focus:ring-ring/30" : "cursor-default opacity-80"}`}
              />
              <div className="flex flex-col items-start gap-1 pt-1 text-[10px]">
                <div className="flex flex-wrap items-center gap-1">
                  <span className={`rounded-full px-2 py-0.5 font-medium capitalize ${STATUS_STYLE[seg.status]}`}>
                    {busy === seg.id ? "saving…" : seg.status}
                  </span>
                  {issues.length > 0 && (
                    <span
                      className={`rounded-full px-1.5 py-0.5 font-medium ${errors ? "bg-del text-del-fg" : "bg-warn text-warn-fg"}`}
                      title={issues.map((i) => `${i.label}: ${i.message}`).join("\n")}
                    >
                      QA {issues.length}
                    </span>
                  )}
                  {seg.flags?.map((f) => (
                    <span key={f} className="rounded-full bg-warn px-1.5 py-0.5 text-warn-fg">
                      {f}
                    </span>
                  ))}
                </div>
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-muted-foreground">
                  {seg.origin && (
                    <span title={seg.origin === "mt" && seg.match ? `Machine translation, adapted from a ${seg.match}% translation-memory match` : undefined}>
                      {originLabel(seg)}
                    </span>
                  )}
                  {seg.qe != null && (
                    <span className={`font-medium tabular-nums ${qeStyle(seg.qe)}`} title="AI quality estimate (0-100) from the last review or LQA">
                      QE {seg.qe}
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
                  {hasProject && seg.tm_saved && (
                    <span className="flex items-center gap-0.5 text-ins-fg" title="This translation is in the project's translation memory">
                      <Database size={11} /> in TM
                    </span>
                  )}
                </div>
                <div
                  className={`flex items-center gap-0.5 transition-opacity ${
                    seg.comments?.length || thread === seg.id || seg.locked
                      ? ""
                      : "opacity-0 group-hover/row:opacity-100 focus-within:opacity-100 has-[[data-state=open]]:opacity-100 pointer-coarse:opacity-100"
                  }`}
                >
                  <RowAction
                    label={
                      seg.comments?.length
                        ? `${openComments(seg)} open comment${openComments(seg) === 1 ? "" : "s"} of ${seg.comments.length}`
                        : "Add a comment"
                    }
                    onClick={() => setThread((t) => (t === seg.id ? null : seg.id))}
                    active={!!openComments(seg)}
                    expanded={thread === seg.id}
                  >
                    <MessageSquare size={12} />
                    {!!seg.comments?.length && <span className="tabular-nums">{openComments(seg) || "✓"}</span>}
                  </RowAction>
                  {seg.translatable && (
                    <RowAction label="Explain: what the source says, and whether the translation carries it (an answer, no edits)" onClick={() => onExplain(seg.id)}>
                      <Lightbulb size={12} />
                    </RowAction>
                  )}
                  {seg.translatable && (
                    <RowAction
                      label={seg.locked ? "Locked — click to unlock (agents and edits allowed)" : "Lock (no one may change it)"}
                      onClick={() => toggleLock(seg)}
                      disabled={!editable}
                      active={seg.locked}
                    >
                      {seg.locked ? <Lock size={12} /> : <LockOpen size={12} />}
                    </RowAction>
                  )}
                  {seg.translatable && !!seg.target && !seg.locked && (
                    <RewriteMenu ids={[seg.id]} editable={editable} onRunTask={onRunTask} compact />
                  )}
                </div>
              </div>
              {proposed.has(seg.id) && (
                <ProposedChange change={proposed.get(seg.id)!} pick={pick} disabled={!!deciding} />
              )}
              {issues.length > 0 && (
                // Always visible: what's wrong with this segment, not just a count.
                <ul
                  className={`col-span-4 -mt-1 mb-1 ml-[84px] space-y-1 rounded-lg border-l-2 bg-background px-3 py-2 text-xs ${
                    errors ? "border-del-fg" : "border-warn-fg"
                  }`}
                >
                  {issues.map((i) => (
                    <li key={i.id} className="group/issue flex items-start gap-2">
                      <SeverityBadge severity={i.severity} />
                      <span className="shrink-0 text-muted-foreground">{i.label}</span>
                      <span className="flex-1">{i.message}</span>
                      {editable && (
                        <button
                          onMouseDown={(e) => e.preventDefault()} // keep focus in the target box
                          onClick={() => onFixIssue(seg.id, i)}
                          className="shrink-0 text-primary hover:underline"
                          title="Ask the agent to fix this — the change comes back as a proposal"
                        >
                          Fix
                        </button>
                      )}
                      <button
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => qa.ignore([i.id])}
                        className="shrink-0 text-muted-foreground hover:text-foreground"
                        title="Ignore (comes back if the text changes)"
                      >
                        Ignore
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {(thread === seg.id || (active === seg.id && !!seg.comments?.length)) && (
                <CommentThread
                  key={`thread-${seg.id}`}
                  sessionId={sessionId}
                  segId={seg.id}
                  comments={seg.comments ?? []}
                  canComment={canComment}
                  role={role}
                  onChanged={onCommented}
                  onClose={thread === seg.id ? () => setThread(null) : undefined}
                  autoFocus={thread === seg.id && !seg.comments?.length}
                  className="col-span-4 -mt-1 mb-1 ml-[84px]"
                />
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
        {rows.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">No segments match.</p>}
        {filter === "comments" && !!doc.orphan_comments?.length && (
          <div className="py-3">
            <div className="mb-1 text-xs font-medium text-muted-foreground">On text that has changed since</div>
            {doc.orphan_comments.map((c) => (
              <div key={c.id} className={`mb-1 flex items-start gap-2 text-xs ${c.resolved ? "opacity-50" : ""}`}>
                <span className="shrink-0 rounded-full bg-muted px-1.5 text-[10px] text-muted-foreground capitalize">{c.role}</span>
                <span className="min-w-0 flex-1">
                  {c.text}
                  <span className="block truncate text-muted-foreground" title={c.anchor}>
                    was on: {c.anchor}
                  </span>
                </span>
                {canComment && (
                  <button
                    onClick={() =>
                      api
                        .deleteComment(sessionId, c.seg_id, c.id)
                        .then(onReload)
                        .catch((e) => setError(String(e)))
                    }
                    className="shrink-0 text-muted-foreground hover:text-del-fg"
                    title="Delete"
                    aria-label="Delete comment"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      {hover && <TermCard term={hover.term} anchor={hover.rect} />}
    </div>
  );
}

/** An icon action on a grid row (comment, explain, lock), with its label as a tooltip. */
function RowAction({
  label,
  onClick,
  disabled,
  active = false,
  expanded,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
  expanded?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          disabled={disabled}
          aria-label={label}
          aria-expanded={expanded}
          className={`flex h-6 min-w-6 items-center justify-center gap-0.5 rounded-md px-1 transition-colors hover:bg-accent disabled:opacity-40 ${
            active ? "text-primary" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{label}</TooltipContent>
    </Tooltip>
  );
}

/** A pending agent change shown in place, under the segment: include it or not, or pick an alternative. The change
 * reads as the document does (RichDiff; its markdown toggle shows the raw diff). */
function ProposedChange({ change, pick, disabled }: { change: ProposalChange; pick: ProposalPick; disabled: boolean }) {
  const k = changeKey(change);
  const included = !pick.excluded.has(k);
  const alternatives = change.alternatives ?? [];
  return (
    <motion.div {...rise} className="col-span-4 -mt-1 mb-1 ml-[84px] rounded-lg border border-primary/40 bg-primary-soft/40 px-3 py-2 text-xs">
      <label className="mb-1.5 flex cursor-pointer items-center gap-1.5 font-medium text-primary">
        <Checkbox checked={included} disabled={disabled} onCheckedChange={(v) => pick.include(k, v === true)} className="size-3.5" />
        Proposed change{alternatives.length ? ` — pick one of ${alternatives.length}` : ""}
      </label>
      <div className={`transition-opacity ${included ? "" : "opacity-40"}`}>
        {alternatives.length ? (
          <div className="space-y-1.5">
            {alternatives.map((alt, i) => (
              <label
                key={i}
                className={`flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 transition-colors ${(pick.choices[k] ?? 0) === i ? "bg-card shadow-xs" : "hover:bg-card/60"}`}
              >
                <input
                  type="radio"
                  name={`grid-alt-${k}`}
                  className="mt-1 accent-[var(--color-primary)]"
                  checked={(pick.choices[k] ?? 0) === i}
                  disabled={disabled || !included}
                  onChange={() => pick.choose(k, i)}
                />
                <span className="min-w-0 flex-1">
                  <RichDiff before={change.before} after={alt.text} />
                  {alt.note && <span className="block text-[11px] text-muted-foreground">{alt.note}</span>}
                </span>
              </label>
            ))}
          </div>
        ) : (
          <RichDiff before={change.before} after={change.after} />
        )}
      </div>
    </motion.div>
  );
}

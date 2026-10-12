"use client";

import {
  AlertTriangle,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  GitCompare,
  Loader2,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Answer, DocFormat, DocStatus, LqaResult, Progress, Proposal, Question, Segment, SourceFix, TimelineItem } from "@/lib/types";
import { ClarifyForm } from "./ClarifyForm";
import { VersionDiff } from "../document/Diff";
import { ProposalCard } from "./ProposalCard";
import type { ProposalPick } from "./proposalPick";
import { Markdown } from "../document/Markdown";
import { QuestionCard } from "./QuestionCard";
import { NextSteps, RunSteps } from "./RunSteps";
import { SourceCheck } from "./SourceCheck";

const FIX_QA = "Please run the QA checks and fix the errors they find.";
/** One-click requests (sent to the chat editor, or run as a task); results come back as proposals. */
const QUICK_ACTIONS: { label: string; title: string; message?: string; task?: "consistency" }[] = [
  { label: "Fix QA errors", title: "The agent runs the QA checks and proposes fixes", message: FIX_QA },
  { label: "Apply termbase", title: "Consistency task: termbase rules and repeated sentences, as a proposal", task: "consistency" },
  {
    label: "Summarise",
    title: "What the document says, for someone who doesn't read the source language (answer only)",
    message: "Summarise what this document says in plain English: its purpose, the key facts, dates and obligations. Don't change anything.",
  },
  { label: "More formal", title: "Propose a more formal register throughout", message: "Make the whole translation more formal in register." },
];

type Group =
  | { type: "single"; item: TimelineItem }
  | { type: "activity"; id: string; items: TimelineItem[] };

/** Collapse runs of activity/tool items into one expandable group. */
function groupTimeline(items: TimelineItem[]): Group[] {
  const groups: Group[] = [];
  for (const item of items) {
    if (item.kind === "activity" || item.kind === "tool") {
      const last = groups[groups.length - 1];
      if (last?.type === "activity") last.items.push(item);
      else groups.push({ type: "activity", id: item.id, items: [item] });
    } else {
      groups.push({ type: "single", item });
    }
  }
  return groups;
}

function toolLabel(item: Extract<TimelineItem, { kind: "tool" }>): string {
  const a = item.args as Record<string, string | string[] | undefined>;
  switch (item.name) {
    case "update_segment":
      return `Edited ${a.segment_id}`;
    case "replace_in_translation":
      return `Replaced “${a.find}” → “${a.replace}”`;
    case "set_glossary_term":
      return `Glossary: ${a.source_term} → ${a.translation}`;
    case "get_segments":
      return `Read ${(a.segment_ids as string[] | undefined)?.join(", ") ?? "segments"}`;
    case "search_segments":
      return `Searched “${a.query}”`;
    case "resolve_question":
      return `Resolved question ${a.question_id}`;
    case "ask_user_about_term":
      return `Asked about “${a.term}”`;
    case "fix_source_segment":
      return `Fixed OCR in ${a.segment_id}`;
    default:
      return item.name;
  }
}

function VersionCard({
  sessionId,
  item,
  segments,
  onShowDiff,
  onJump,
}: {
  sessionId: string;
  item: Extract<TimelineItem, { kind: "version" }>;
  segments: Segment[];
  onShowDiff: (version: number) => void;
  onJump: (segmentId: string) => void;
}) {
  const hasDiff = item.version > 1;
  // Small edits show their diff inline right away; big passes (draft, review) stay collapsed.
  const [open, setOpen] = useState(hasDiff && item.changed.length > 0 && item.changed.length <= 5);
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-panel text-sm">
      <div className="flex items-center gap-3 px-3 py-2.5">
        <GitCompare size={18} className="shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <div className="font-medium">Translation v{item.version}</div>
          <div className="truncate text-xs text-muted">
            {item.note}
            {item.changed.length > 0 && ` · ${item.changed.length} segment${item.changed.length === 1 ? "" : "s"} changed`}
          </div>
        </div>
        {hasDiff && (
          <>
            <button onClick={() => setOpen(!open)} className="flex items-center gap-0.5 text-xs text-muted hover:text-fg">
              {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Changes
            </button>
            <button onClick={() => onShowDiff(item.version)} className="text-xs text-accent hover:underline">
              Open
            </button>
          </>
        )}
      </div>
      {open && (
        <div className="scroll-thin max-h-[40vh] overflow-y-auto border-t border-border px-3">
          <VersionDiff sessionId={sessionId} version={item.version} segments={segments} onJump={onJump} />
        </div>
      )}
    </div>
  );
}

function ActivityGroup({ items, live }: { items: TimelineItem[]; live: boolean }) {
  const [open, setOpen] = useState(false);
  const last = items[items.length - 1];
  const label = (it: TimelineItem) =>
    it.kind === "tool" ? toolLabel(it) : it.kind === "activity" ? it.text : "";
  return (
    <div className="text-sm text-muted">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 hover:text-fg">
        {live ? <Loader2 size={14} className="animate-spin text-accent" /> : <Wrench size={14} />}
        <span className="truncate">{label(last)}</span>
        {items.length > 1 && (
          <>
            <span className="shrink-0 text-xs whitespace-nowrap">· {items.length} steps</span>
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </>
        )}
      </button>
      {open && (
        <ul className="mt-1.5 ml-[7px] space-y-0.5 border-l border-border pl-4 text-xs">
          {items.map((it) => (
            <li key={it.id}>{label(it)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Chat({
  sessionId,
  proposal,
  pick,
  onAcceptProposal,
  onRejectProposal,
  timeline,
  running,
  serverRunning,
  status,
  progress,
  questions,
  segments,
  onSend,
  onAnswer,
  onClarify,
  onRetry,
  onShowDiff,
  onJump,
  draft,
  setDraft,
  lqa,
  format,
  versionCount,
  onOpenSegments,
  onRunLqa,
  onRunTask,
  sourceFixes,
  onDecideSourceFix,
  onContinueSourceCheck,
}: {
  sessionId: string;
  proposal: Proposal | null;
  pick: ProposalPick;
  onAcceptProposal: (changes: string[] | null, choices: Record<string, number> | null) => Promise<void>;
  onRejectProposal: () => Promise<void>;
  timeline: TimelineItem[];
  running: boolean;
  serverRunning: boolean;
  status: DocStatus | undefined;
  progress: Progress | null;
  questions: Question[];
  segments: Segment[];
  onSend: (text: string) => void;
  onAnswer: (questionId: string, answer: Answer | null) => void;
  onClarify: (answers: Record<string, Answer | null>) => Promise<void>;
  onRetry: () => void;
  onShowDiff: (version: number) => void;
  onJump: (segmentId: string) => void;
  draft: string;
  setDraft: (s: string) => void;
  lqa: LqaResult | null;
  format: DocFormat | null;
  versionCount: number;
  onOpenSegments: () => void;
  onRunLqa: () => void;
  onRunTask: (kind: "consistency") => void;
  sourceFixes: SourceFix[];
  onDecideSourceFix: (page: number, accept: boolean) => Promise<void>;
  onContinueSourceCheck: () => Promise<void>;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const groups = useMemo(() => groupTimeline(timeline), [timeline]);
  const segMap = useMemo(() => new Map(segments.map((s) => [s.id, s])), [segments]);
  const openQs = questions.filter((q) => q.status === "open");
  const paused = status === "awaiting_answers" && !running;
  const checking = status === "awaiting_source_check" && !running; // the chat stays open: it fixes the source
  // A pipeline status with no live run means the run died (error or server restart).
  const stalled = !running && !serverRunning && !!status && !["ready", "awaiting_answers", "awaiting_source_check"].includes(status);
  const locked = running || paused || stalled;
  const pipeline = !!status && !["ready", "error"].includes(status); // the ingest run (not a task or chat turn)
  const idle = !running && status === "ready";

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [timeline.length, running, openQs.length, proposal?.changes.length]);

  const send = () => {
    const t = draft.trim();
    if (!t || locked) return;
    onSend(t);
    setDraft("");
  };

  const placeholder = running
    ? "Agents are working…"
    : paused
      ? "Answer the questions above to continue…"
      : checking
        ? "What's wrong with the reading? e.g. “page 1 has two columns: read the left one first”"
        : stalled
          ? "Retry processing to continue…"
          : "Ask for a change, or e.g. “explain p1.4”";

  return (
    <div className="flex h-full min-w-0 flex-col">
      <div className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-4 px-5 py-6">
          {groups.map((g, i) => {
            if (g.type === "activity")
              return <ActivityGroup key={g.id} items={g.items} live={running && i === groups.length - 1} />;
            const it = g.item;
            switch (it.kind) {
              case "user":
                return (
                  <div key={it.id} className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl bg-sidebar px-4 py-2 text-sm whitespace-pre-wrap">
                      {it.text}
                    </div>
                  </div>
                );
              case "assistant":
                return (
                  <div key={it.id} className="flex gap-2.5">
                    <Sparkles size={16} className="mt-1 shrink-0 text-accent" />
                    <Markdown text={it.text} className="min-w-0 text-sm" />
                  </div>
                );
              case "version":
                return (
                  <VersionCard
                    key={it.id}
                    sessionId={sessionId}
                    item={it}
                    segments={segments}
                    onShowDiff={onShowDiff}
                    onJump={onJump}
                  />
                );
              case "error":
                return (
                  <div key={it.id} className="flex items-start gap-2 rounded-lg bg-del px-3 py-2 text-sm text-del-fg">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                    <span className="break-words">{it.text}</span>
                  </div>
                );
              default:
                return null;
            }
          })}

          {(pipeline || paused) && !stalled && (
            <RunSteps progress={progress} status={status} running={running} segments={segments} check={format === "pdf" || format === "image"} />
          )}

          {running && progress && !pipeline && (
            <div className="rounded-xl border border-border bg-panel p-3 text-sm">
              <div className="flex items-center justify-between text-xs text-muted">
                <span className="flex items-center gap-1.5">
                  <Loader2 size={12} className="animate-spin text-accent" /> {progress.message}
                </span>
                {progress.total > 0 && (
                  <span>
                    {progress.current}/{progress.total}
                  </span>
                )}
              </div>
              {progress.total > 0 && (
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sidebar">
                  <div
                    className="h-full rounded-full bg-accent transition-all"
                    style={{ width: `${Math.round((100 * progress.current) / progress.total)}%` }}
                  />
                </div>
              )}
            </div>
          )}

          {proposal && (
            <ProposalCard
              key={proposal.id}
              proposal={proposal}
              pick={pick}
              segments={segments}
              disabled={running}
              onAccept={onAcceptProposal}
              onReject={onRejectProposal}
              onJump={onJump}
            />
          )}

          {idle && !proposal && (
            <NextSteps
              sessionId={sessionId}
              segments={segments}
              lqa={lqa}
              versionCount={versionCount}
              onOpenSegments={onOpenSegments}
              onFixQa={() => onSend(FIX_QA)}
              onRunLqa={onRunLqa}
            />
          )}

          {stalled && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-del-fg/30 bg-del px-3 py-2.5 text-sm text-del-fg">
              <span className="flex items-center gap-2">
                <AlertTriangle size={16} />
                {status === "error" ? "Processing failed." : "Processing was interrupted."}
              </span>
              <button onClick={onRetry} className="rounded-md bg-panel px-2.5 py-1 text-xs font-medium text-fg hover:opacity-80">
                Retry
              </button>
            </div>
          )}

          {checking && <SourceCheck fixes={sourceFixes} onDecide={onDecideSourceFix} onContinue={onContinueSourceCheck} />}

          {paused && openQs.length > 0 && (
            <ClarifyForm questions={openQs} segments={segMap} onSubmit={onClarify} onJump={onJump} />
          )}

          {!paused && openQs.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-medium tracking-wide text-muted uppercase">
                The translator has {openQs.length} question{openQs.length === 1 ? "" : "s"}
              </div>
              {openQs.map((q) => (
                <QuestionCard
                  key={q.id}
                  question={q}
                  segments={segMap}
                  disabled={running}
                  onAnswer={(a) => onAnswer(q.id, a)}
                  onJump={onJump}
                />
              ))}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="px-5 pb-5">
        {idle && (
          <div className="mx-auto mb-2 flex max-w-2xl flex-wrap gap-1.5">
            {QUICK_ACTIONS.map((a) => (
              <button
                key={a.label}
                title={a.title}
                onClick={() => (a.task ? onRunTask(a.task) : a.message && onSend(a.message))}
                className="rounded-full border border-border bg-panel px-2.5 py-1 text-xs text-muted hover:border-accent hover:text-fg"
              >
                {a.label}
              </button>
            ))}
          </div>
        )}
        <div className="mx-auto flex max-w-2xl items-end gap-2 rounded-2xl border border-border bg-panel px-3 py-2 shadow-sm focus-within:border-accent">
          {/* Grows with its text (or the placeholder) up to 10 lines: the hidden copy sets the height. */}
          <div className="grid min-w-0 flex-1">
            <div
              aria-hidden
              className="invisible col-start-1 row-start-1 max-h-60 overflow-hidden py-1.5 text-sm whitespace-pre-wrap [overflow-wrap:anywhere]"
            >
              {(draft || placeholder) + " "}
            </div>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={1}
              placeholder={placeholder}
              disabled={paused || stalled}
              className="col-start-1 row-start-1 resize-none overflow-y-auto bg-transparent py-1.5 text-sm whitespace-pre-wrap outline-none [overflow-wrap:anywhere]"
            />
          </div>
          <button
            onClick={send}
            disabled={locked || !draft.trim()}
            className="mb-0.5 rounded-lg bg-accent p-1.5 text-white disabled:opacity-30"
          >
            {running ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}

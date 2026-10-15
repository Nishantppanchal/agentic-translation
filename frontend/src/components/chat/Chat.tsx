"use client";

import { AlertTriangle, ArrowUp, ChevronRight, GitCompare, Loader2, RotateCcw, Sparkles, Wrench } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { cn } from "cn";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Kbd } from "@/components/ui/kbd";
import { Progress as Bar } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { pop, rise } from "@/lib/motion";
import type {
  Answer,
  DocFormat,
  DocSettings,
  DocStatus,
  LqaResult,
  Progress,
  Proposal,
  Question,
  Segment,
  SourceFix,
  TimelineItem,
} from "@/lib/types";
import { VersionDiff } from "../document/Diff";
import { Markdown } from "../document/Markdown";
import { useModelCatalog } from "../settings/ModelChoices";
import { ChatModelPicker } from "./ChatModelPicker";
import { ClarifyForm } from "./ClarifyForm";
import { LookupRow, lookupLabel } from "./Lookup";
import { ProposalCard } from "./ProposalCard";
import type { ProposalPick } from "./proposalPick";
import { QuestionCard } from "./QuestionCard";
import { NextSteps, RunSteps } from "./RunSteps";
import { SourceCheck } from "./SourceCheck";
import { useCompletion, useSuggestions } from "./useAssist";

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

// The source check for someone who doesn't read the language: the chat looks at every page next to its reading.
const CHECK_PAGES_REQUEST =
  "Please check the reading for me: look at each page next to its OCR text — start with the pages listed under " +
  "“where to look first” — and tell me in plain English what looks wrong (reading order, missing or extra text, " +
  "stamps or seals, headings, tables). Propose fixes where the structure is wrong, and have a page read again " +
  "where text is misread. Don't change anything that looks right.";

type Group = { type: "single"; item: TimelineItem } | { type: "activity"; id: string; items: TimelineItem[] };

/** Collapse runs of activity/tool/lookup items into one expandable group. */
function groupTimeline(items: TimelineItem[]): Group[] {
  const groups: Group[] = [];
  for (const item of items) {
    if (item.kind === "activity" || item.kind === "tool" || item.kind === "lookup") {
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
    case "look_at_page":
      return `Looked at page ${a.page_number}`;
    case "get_page_source":
      return `Read the OCR of page ${a.page_number}`;
    case "propose_page_source":
      return `Proposed a fix for page ${a.page_number}`;
    case "reread_page":
      return `Read page ${a.page_number} again`;
    case "inspect_page_layout":
      return `Checked the layout of page ${a.page_number}`;
    case "add_comment":
      return `Commented on ${a.segment_id}`;
    case "run_qa_checks":
      return "Ran the QA checks";
    case "propose_alternatives":
      return `Proposed alternatives for ${a.segment_id}`;
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
    <Collapsible open={open} onOpenChange={setOpen} className="overflow-hidden rounded-xl border border-border bg-card text-sm shadow-xs">
      <div className="flex items-center gap-3 px-3 py-2.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
          <GitCompare size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-medium">Translation v{item.version}</div>
          <div className="truncate text-xs text-muted-foreground">
            {item.note}
            {item.changed.length > 0 && ` · ${item.changed.length} segment${item.changed.length === 1 ? "" : "s"} changed`}
          </div>
        </div>
        {hasDiff && (
          <>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="xs" className="text-muted-foreground">
                <ChevronRight className={cn("transition-transform", open && "rotate-90")} /> Changes
              </Button>
            </CollapsibleTrigger>
            <Button variant="link" size="xs" onClick={() => onShowDiff(item.version)} className="px-1">
              Open
            </Button>
          </>
        )}
      </div>
      <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
        <div className="scroll-thin max-h-[40vh] overflow-y-auto border-t border-border px-3">
          <VersionDiff sessionId={sessionId} version={item.version} segments={segments} onJump={onJump} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function ActivityGroup({ items, live }: { items: TimelineItem[]; live: boolean }) {
  const last = items[items.length - 1];
  const label = (it: TimelineItem) =>
    it.kind === "tool" ? toolLabel(it) : it.kind === "activity" ? it.text : it.kind === "lookup" ? lookupLabel(it) : "";
  if (items.length === 1 && last.kind === "lookup") {
    return (
      <div className="pl-9 text-sm text-muted-foreground">
        <LookupRow item={last} />
      </div>
    );
  }
  const head = (
    <>
      {live ? <Loader2 size={14} className="shrink-0 animate-spin text-primary" /> : <Wrench size={14} className="shrink-0" />}
      <span className={cn("truncate", live && "text-foreground/80")}>{label(last)}</span>
    </>
  );
  if (items.length === 1) return <div className="flex items-center gap-1.5 pl-9 text-sm text-muted-foreground">{head}</div>;
  return (
    <Collapsible className="pl-9 text-sm text-muted-foreground">
      <CollapsibleTrigger className="group/act flex max-w-full items-center gap-1.5 rounded-sm text-left transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50">
        {head}
        <span className="shrink-0 text-xs whitespace-nowrap">· {items.length} steps</span>
        <ChevronRight size={14} className="shrink-0 transition-transform group-data-[state=open]/act:rotate-90" />
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
        <ul className="mt-1.5 ml-[7px] space-y-0.5 border-l border-border pl-4 text-xs">
          {items.map((it) => (
            <li key={it.id}>{it.kind === "lookup" ? <LookupRow item={it} /> : label(it)}</li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** The assistant's avatar: a soft disc with the sparkle. */
function Avatar() {
  return (
    <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary ring-1 ring-primary/15">
      <Sparkles size={14} />
    </span>
  );
}

const IME = (e: React.KeyboardEvent) => e.nativeEvent.isComposing || e.keyCode === 229;

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
  settings,
  onSettingsChanged,
}: {
  sessionId: string;
  proposal: Proposal | null;
  pick: ProposalPick;
  onAcceptProposal: (changes: string[] | null, choices: Record<string, number> | null, confirm?: boolean) => Promise<void>;
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
  settings?: DocSettings | null; // this document's models (the chat model picker)
  onSettingsChanged?: () => void; // after the chat model changed: reload the document
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

  // AI assist: suggested next prompts once a run is over, and Tab completions while typing.
  const catalog = useModelCatalog();
  const assistOn = catalog.settings?.assist !== false;
  const suggestions = useSuggestions(sessionId, idle ? timeline.length : -1, assistOn);
  const [focused, setFocused] = useState(false);
  const [atEnd, setAtEnd] = useState(true);
  const [composing, setComposing] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const long = draft.length > 600 || draft.split("\n").length > 8; // past where the ghost lines up with the text
  const completion = useCompletion(sessionId, draft, assistOn && !locked && focused && atEnd && !composing && !long);
  const starter = !draft && !locked && suggestions.length > 0 ? suggestions[0].prompt : "";
  const ghost = dismissed === draft ? "" : draft ? completion : starter;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [timeline.length, running, openQs.length, proposal?.changes.length]);

  const send = () => {
    const t = draft.trim();
    if (!t || locked) return;
    onSend(t);
    setDraft("");
  };
  const trackCaret = (el: HTMLTextAreaElement) => setAtEnd(el.selectionStart === el.value.length && el.selectionEnd === el.value.length);

  const placeholder = running
    ? "Agents are working…"
    : paused
      ? "Answer the questions above to continue…"
      : checking
        ? "What's wrong with the reading? e.g. “page 1 has two columns: read the left one first”"
        : stalled
          ? "Retry processing to continue…"
          : "Ask for a change, or e.g. “explain p1.4”";

  const render = (g: Group, i: number) => {
    if (g.type === "activity") return <ActivityGroup items={g.items} live={running && i === groups.length - 1} />;
    const it = g.item;
    switch (it.kind) {
      case "user":
        return (
          <div className="flex justify-end">
            <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary-soft px-4 py-2 text-sm whitespace-pre-wrap text-foreground">
              {it.text}
            </div>
          </div>
        );
      case "assistant":
        return (
          <div className="flex gap-2.5">
            <Avatar />
            <Markdown text={it.text} className="min-w-0 flex-1 pt-0.5 text-sm" />
          </div>
        );
      case "version":
        return <VersionCard sessionId={sessionId} item={it} segments={segments} onShowDiff={onShowDiff} onJump={onJump} />;
      case "error":
        return (
          <div className="flex items-start gap-2 rounded-lg border border-del-fg/20 bg-del px-3 py-2 text-sm text-del-fg">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span className="break-words">{it.text}</span>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="flex h-full min-w-0 flex-col">
      <div className="scroll-thin flex-1 overflow-y-auto">
        <div key={sessionId} className="mx-auto max-w-2xl space-y-4 px-5 py-6">
          <AnimatePresence initial={false}>
            {groups.map((g, i) => (
              // Keyed by position: a streaming draft and the message that replaces it are the same element (no flash).
              <motion.div key={`g${i}`} {...rise}>
                {render(g, i)}
              </motion.div>
            ))}
          </AnimatePresence>

          {(pipeline || paused) && !stalled && (
            <RunSteps progress={progress} status={status} running={running} segments={segments} check={format === "pdf" || format === "image"} />
          )}

          {running && progress && !pipeline && (
            <motion.div {...rise} className="rounded-xl border border-border bg-card p-3 text-sm shadow-xs">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <Loader2 size={12} className="animate-spin text-primary" /> {progress.message}
                </span>
                {progress.total > 0 && (
                  <span className="tabular-nums">
                    {progress.current}/{progress.total}
                  </span>
                )}
              </div>
              {progress.total > 0 && <Bar value={Math.round((100 * progress.current) / progress.total)} className="mt-2 h-1.5 bg-muted" />}
            </motion.div>
          )}

          <AnimatePresence initial={false}>
            {proposal && (
              <motion.div key={proposal.id} {...rise}>
                <ProposalCard
                  proposal={proposal}
                  pick={pick}
                  segments={segments}
                  disabled={running}
                  onAccept={onAcceptProposal}
                  onReject={onRejectProposal}
                  onJump={onJump}
                />
              </motion.div>
            )}
          </AnimatePresence>

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
            <div className="flex items-center justify-between gap-3 rounded-xl border border-del-fg/25 bg-del px-3 py-2.5 text-sm text-del-fg">
              <span className="flex items-center gap-2">
                <AlertTriangle size={16} />
                {status === "error" ? "Processing failed." : "Processing was interrupted."}
              </span>
              <Button variant="outline" size="sm" onClick={onRetry} className="bg-card text-foreground">
                <RotateCcw /> Retry
              </Button>
            </div>
          )}

          {checking && (
            <SourceCheck
              fixes={sourceFixes}
              onDecide={onDecideSourceFix}
              onContinue={onContinueSourceCheck}
              onAskToCheck={() => onSend(CHECK_PAGES_REQUEST)}
              chatBusy={running}
            />
          )}

          {paused && openQs.length > 0 && <ClarifyForm questions={openQs} segments={segMap} onSubmit={onClarify} onJump={onJump} />}

          {!paused && openQs.length > 0 && (
            <div className="space-y-2">
              <div className="text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
                The translator has {openQs.length} question{openQs.length === 1 ? "" : "s"}
              </div>
              <AnimatePresence initial={false}>
                {openQs.map((q) => (
                  <motion.div key={q.id} {...rise}>
                    <QuestionCard question={q} segments={segMap} disabled={running} onAnswer={(a) => onAnswer(q.id, a)} onJump={onJump} />
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="px-5 pb-5">
        {idle && (
          <div className="mx-auto mb-2 flex max-w-2xl flex-wrap gap-1.5">
            <AnimatePresence initial={false}>
              {suggestions.map((s) => (
                <motion.div key={s.prompt} {...pop} layout>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="xs"
                        onClick={() => onSend(s.prompt)}
                        className="rounded-full border-primary/30 bg-primary-soft text-primary hover:bg-primary-soft hover:text-primary hover:brightness-95"
                      >
                        <Sparkles /> {s.label}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs">{s.prompt}</TooltipContent>
                  </Tooltip>
                </motion.div>
              ))}
            </AnimatePresence>
            {QUICK_ACTIONS.map((a) => (
              <Tooltip key={a.label}>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="xs"
                    onClick={() => (a.task ? onRunTask(a.task) : a.message && onSend(a.message))}
                    className="rounded-full bg-card text-muted-foreground hover:text-foreground"
                  >
                    {a.label}
                  </Button>
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">{a.title}</TooltipContent>
              </Tooltip>
            ))}
          </div>
        )}
        <div className="mx-auto max-w-2xl rounded-2xl border border-input bg-card shadow-sm transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/20">
          {/* Grows with its text (or the placeholder) up to 10 lines: the copy underneath sets the height, and shows the
              ghost text (a completion, or a suggested prompt in an empty box) after the invisible copy of the draft. */}
          <div className="grid min-w-0 px-3.5 pt-2.5">
            <div
              aria-hidden
              className="col-start-1 row-start-1 max-h-60 overflow-hidden py-1 text-sm whitespace-pre-wrap [overflow-wrap:anywhere]"
            >
              <span className="text-transparent">{draft || (ghost ? "" : placeholder)}</span>
              {ghost && <span className="text-muted-foreground/60">{ghost}</span>}{" "}
            </div>
            <textarea
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                trackCaret(e.target);
              }}
              onSelect={(e) => trackCaret(e.currentTarget)}
              onFocus={(e) => {
                setFocused(true);
                trackCaret(e.currentTarget);
              }}
              onBlur={() => setFocused(false)}
              onCompositionStart={() => setComposing(true)}
              onCompositionEnd={() => setComposing(false)}
              onKeyDown={(e) => {
                if (IME(e)) return;
                if (e.key === "Tab" && !e.shiftKey && ghost) {
                  e.preventDefault();
                  setDraft(draft + ghost);
                  return;
                }
                if (e.key === "Escape" && ghost) {
                  e.preventDefault();
                  setDismissed(draft);
                  return;
                }
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={1}
              placeholder={ghost ? "" : placeholder}
              disabled={paused || stalled}
              aria-label="Message the chat"
              className="col-start-1 row-start-1 resize-none overflow-y-auto bg-transparent py-1 text-sm whitespace-pre-wrap outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed [overflow-wrap:anywhere]"
            />
          </div>
          <div className="flex items-center gap-2 px-2 pt-1 pb-2">
            {settings && catalog.models && catalog.settings && (
              <ChatModelPicker
                sessionId={sessionId}
                settings={settings}
                models={catalog.models}
                catalog={catalog.settings}
                busy={running}
                onSaved={() => onSettingsChanged?.()}
              />
            )}
            <span className="flex-1" />
            <AnimatePresence>
              {ghost && (
                <motion.span {...pop} className="flex items-center gap-1 text-[11px] text-muted-foreground">
                  <Kbd>Tab</Kbd> {draft ? "to complete" : "for this suggestion"}
                </motion.span>
              )}
            </AnimatePresence>
            <Button size="icon-sm" onClick={send} disabled={locked || !draft.trim()} className="rounded-lg" aria-label="Send">
              {running ? <Loader2 className="animate-spin" /> : <ArrowUp />}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

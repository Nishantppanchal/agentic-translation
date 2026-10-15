"use client";

import { Eye, EyeOff, Gauge, ListOrdered, Loader2, Play, ShieldCheck, Wand2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { rise } from "@/lib/motion";
import type { DocumentState, LqaResult, QaIssue, Severity } from "@/lib/types";
import type { QaState } from "../cat/useQa";
import { Markdown } from "./Markdown";

const CATEGORY_LABEL: Record<string, string> = {
  accuracy: "Accuracy",
  fluency: "Fluency",
  terminology: "Terminology",
  style: "Style",
  locale: "Locale conventions",
  markup: "Design & markup",
  other: "Uncategorised",
};
const SEVERITIES: Severity[] = ["minor", "major", "critical"];
const PENALTY: Record<Severity, number> = { minor: 1, major: 5, critical: 25 };
export const SEV_STYLE: Record<string, string> = {
  error: "bg-del text-del-fg",
  warning: "bg-warn text-warn-fg",
  critical: "bg-del-fg text-del",
  major: "bg-del text-del-fg",
  minor: "bg-warn text-warn-fg",
};

export const qeStyle = (qe: number) => (qe >= 90 ? "text-ins-fg" : qe >= 70 ? "text-warn-fg" : "text-del-fg");

/** A severity chip: error, warning, minor, major, critical. */
export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`mt-px shrink-0 rounded-full px-1.5 py-px text-[10px] font-medium tracking-wide uppercase ${SEV_STYLE[severity] ?? "bg-muted text-muted-foreground"}`}>
      {severity}
    </span>
  );
}

function SegLink({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button onClick={() => onOpen(id)} className="shrink-0 font-mono text-[11px] text-muted-foreground hover:text-primary">
          {id}
        </button>
      </TooltipTrigger>
      <TooltipContent>Open in the segment editor</TooltipContent>
    </Tooltip>
  );
}

function Section({ icon, title, meta, action, children }: { icon: React.ReactNode; title: string; meta?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-muted-foreground">{icon}</span>
        <h3 className="text-sm font-semibold">{title}</h3>
        {meta && <span className="text-xs text-muted-foreground">{meta}</span>}
        {action && <span className="ml-auto">{action}</span>}
      </div>
      {children}
    </section>
  );
}

function QaSection({ qa, onOpen }: { qa: QaState; onOpen: (id: string) => void }) {
  const [check, setCheck] = useState<string>("");
  const [showIgnored, setShowIgnored] = useState(false);
  const report = qa.report;
  if (!report)
    return (
      <Section icon={<ShieldCheck size={16} />} title="Automatic QA" meta="Running checks…">
        <div className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
        </div>
      </Section>
    );
  const { summary } = report;
  const shown = report.issues.filter((i) => (showIgnored || !i.ignored) && (!check || i.check === check));
  const checks = report.checks.filter((c) => summary.by_check[c.id] > 0);

  return (
    <Section
      icon={<ShieldCheck size={16} />}
      title="Automatic QA"
      meta={
        <>
          {summary.errors} error{summary.errors === 1 ? "" : "s"} · {summary.warnings} warning{summary.warnings === 1 ? "" : "s"}
          {summary.ignored ? ` · ${summary.ignored} ignored` : ""}
        </>
      }
      action={
        summary.ignored > 0 && (
          <Button variant="ghost" size="xs" onClick={() => setShowIgnored((v) => !v)}>
            {showIgnored ? <EyeOff /> : <Eye />} {showIgnored ? "Hide" : "Show"} ignored
          </Button>
        )
      }
    >
      <p className="mb-3 text-xs text-muted-foreground">
        Numbers and dates, termbase and forbidden terms, markup, punctuation, consistency and length — checked on every change.
        Errors are sent to the AI reviewer as must-fix issues; warnings may be false alarms, so ignore the ones that are fine.
      </p>
      {checks.length > 0 && (
        <ToggleGroup type="single" value={check} onValueChange={setCheck} className="mb-2 flex-wrap justify-start gap-1" aria-label="Filter by check">
          <ToggleGroupItem value="" className="h-6 rounded-full px-2.5 text-xs data-[state=on]:bg-foreground data-[state=on]:text-background">
            All
          </ToggleGroupItem>
          {checks.map((c) => (
            <ToggleGroupItem
              key={c.id}
              value={c.id}
              className="h-6 rounded-full bg-muted px-2.5 text-xs data-[state=on]:bg-foreground data-[state=on]:text-background"
            >
              {c.label} <span className="tabular-nums opacity-70">{summary.by_check[c.id]}</span>
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      )}
      {shown.length === 0 ? (
        <p className="rounded-lg bg-ins px-3 py-2 text-sm text-ins-fg">No open QA issues.</p>
      ) : (
        <ul className="divide-y divide-border">
          <AnimatePresence initial={false}>
            {shown.map((i: QaIssue) => (
              <motion.li key={i.id} {...rise} layout="position" className={`group flex items-start gap-2 py-2 text-xs ${i.ignored ? "opacity-50" : ""}`}>
                <SeverityBadge severity={i.severity} />
                <SegLink id={i.segment_id} onOpen={onOpen} />
                <span className="shrink-0 text-muted-foreground">{i.label}</span>
                <span className="flex-1">{i.message}</span>
                <button
                  onClick={() => qa.ignore([i.id], !i.ignored)}
                  className="shrink-0 rounded px-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground focus-visible:opacity-100"
                  title={i.ignored ? "Show this issue again" : "Ignore (it comes back if the text changes)"}
                >
                  {i.ignored ? "Restore" : "Ignore"}
                </button>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </Section>
  );
}

function Scorecard({ lqa, latest, onOpen }: { lqa: LqaResult; latest: number; onOpen: (id: string) => void }) {
  const rows = Object.entries(lqa.matrix);
  return (
    <div>
      <div className="flex flex-wrap items-end gap-5">
        <div>
          <div className={`text-4xl font-semibold tracking-tight tabular-nums ${lqa.passed ? "text-ins-fg" : "text-del-fg"}`}>{lqa.score.toFixed(1)}</div>
          <div className="text-xs text-muted-foreground">MQM quality score</div>
        </div>
        <div className="mb-1 min-w-48 flex-1">
          <div className="mb-1 flex items-center justify-between text-xs">
            <span className={`rounded-full px-2 py-0.5 font-semibold ${lqa.passed ? "bg-ins text-ins-fg" : "bg-del text-del-fg"}`}>
              {lqa.passed ? "PASS" : "FAIL"}
            </span>
            <span className="text-muted-foreground">threshold {lqa.threshold}</span>
          </div>
          <div className="relative">
            <Progress value={Math.max(0, Math.min(100, lqa.score))} className={`h-2 ${lqa.passed ? "[&>div]:bg-ins-fg" : "[&>div]:bg-del-fg"} bg-muted`} />
            <span className="absolute -top-0.5 h-3 w-px bg-foreground/60" style={{ left: `${lqa.threshold}%` }} aria-hidden />
          </div>
        </div>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        {lqa.penalty} penalty point{lqa.penalty === 1 ? "" : "s"} in {lqa.words} source words · v{lqa.version ?? "?"} · {lqa.model} ·{" "}
        {new Date(lqa.at * 1000).toLocaleString()}
        {lqa.version !== null && lqa.version < latest && <span className="text-warn-fg"> · the translation has changed since (v{latest})</span>}
      </div>
      <table className="mt-3 w-full text-left text-xs">
        <thead className="text-muted-foreground">
          <tr className="border-b border-border">
            <th className="py-1.5 font-medium">Category</th>
            {SEVERITIES.map((s) => (
              <th key={s} className="py-1.5 text-right font-medium capitalize">
                {s} <span className="font-normal">×{PENALTY[s]}</span>
              </th>
            ))}
            <th className="py-1.5 text-right font-medium">Points</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([cat, counts]) => {
            const points = SEVERITIES.reduce((n, s) => n + counts[s] * PENALTY[s], 0);
            return (
              <tr key={cat} className="border-b border-border last:border-0">
                <td className="py-1.5">{CATEGORY_LABEL[cat] ?? cat}</td>
                {SEVERITIES.map((s) => (
                  <td key={s} className={`py-1.5 text-right tabular-nums ${counts[s] ? "font-semibold" : "text-muted-foreground"}`}>
                    {counts[s]}
                  </td>
                ))}
                <td className={`py-1.5 text-right tabular-nums ${points ? "font-semibold" : "text-muted-foreground"}`}>{points}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-1.5 text-[11px] text-muted-foreground">Score = 100 − penalty points per 1000 source words (MQM weights: minor 1, major 5, critical 25).</p>
      {lqa.errors.length > 0 && (
        <ul className="mt-3 divide-y divide-border">
          {lqa.errors.map((e, k) => (
            <li key={k} className="flex items-start gap-2 py-1.5 text-xs">
              <SeverityBadge severity={e.severity} />
              <SegLink id={e.segment_id} onOpen={onOpen} />
              <span className="shrink-0 text-muted-foreground">{CATEGORY_LABEL[e.category ?? "other"]}</span>
              <span>
                {e.span && <q className="rounded bg-del px-0.5 text-del-fg">{e.span}</q>} {e.note}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function QualityView({
  doc,
  qa,
  canRun,
  onRunLqa,
  onFixConsistency,
  onOpenSegment,
}: {
  doc: DocumentState;
  qa: QaState;
  canRun: boolean;
  onRunLqa: () => Promise<void>;
  onFixConsistency: () => Promise<void>;
  onOpenSegment: (id: string) => void;
}) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latest = doc.versions.at(-1)?.version ?? 0;
  const issueCount = useMemo(() => {
    const n = new Map<string, number>();
    for (const i of qa.report?.issues ?? []) if (!i.ignored) n.set(i.segment_id, (n.get(i.segment_id) ?? 0) + 1);
    return n;
  }, [qa.report]);
  const queue = useMemo(
    () =>
      doc.segments
        .filter((s) => s.translatable && s.qe != null && s.status !== "reviewed")
        .sort((a, b) => (a.qe ?? 100) - (b.qe ?? 100) || a.page - b.page)
        .slice(0, 12),
    [doc.segments],
  );

  const run = async () => {
    setStarting(true);
    setError(null);
    try {
      await onRunLqa();
    } catch (e) {
      setError(String(e));
    } finally {
      setStarting(false);
    }
  };

  const fixable = (qa.report?.summary.by_check.consistency ?? 0) + (qa.report?.summary.by_check.terminology ?? 0);
  const fix = async () => {
    setError(null);
    try {
      await onFixConsistency();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="space-y-4 text-sm">
      <QaSection qa={qa} onOpen={onOpenSegment} />
      {fixable > 0 && (
        <div className="flex items-center gap-3 rounded-xl border border-primary/30 bg-primary-soft px-4 py-3 text-xs">
          <Wand2 size={16} className="shrink-0 text-primary" />
          <span className="flex-1">
            {fixable} consistency or terminology issue{fixable === 1 ? "" : "s"}. The agent can unify repeated sentences (your confirmed
            translations win) and apply the termbase — as a proposal you review.
          </span>
          <Button size="sm" onClick={fix} disabled={!canRun}>
            Fix consistency
          </Button>
        </div>
      )}

      <Section
        icon={<Gauge size={16} />}
        title="Quality score (LQA)"
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={run}
            disabled={!canRun || starting}
            title="An independent AI assessor annotates errors with MQM categories and severities. Nothing is changed."
          >
            {starting ? <Loader2 className="animate-spin" /> : <Play />} {doc.lqa ? "Run again" : "Run LQA"}
          </Button>
        }
      >
        {error && <div className="mb-2 rounded-md bg-del px-2 py-1 text-xs text-del-fg">{error}</div>}
        {doc.lqa ? (
          <Scorecard lqa={doc.lqa} latest={latest} onOpen={onOpenSegment} />
        ) : (
          <p className="text-xs text-muted-foreground">
            Not assessed yet. LQA scores the current version the way an LSP reviewer would: every error gets an MQM category and
            severity, and the document passes or fails against the project&apos;s threshold.
          </p>
        )}
      </Section>

      <Section icon={<ListOrdered size={16} />} title="Review queue">
        <p className="mb-2 text-xs text-muted-foreground">
          Segments with the lowest AI quality estimate first (from the last review or LQA), so a human reviewer starts where it
          matters. Reviewed segments drop off.
        </p>
        {queue.length === 0 ? (
          <p className="text-xs text-muted-foreground">No scored segments waiting.</p>
        ) : (
          <ul className="divide-y divide-border">
            {queue.map((s) => (
              <li key={s.id} className="flex items-center gap-3 py-1.5 text-xs">
                <span className={`w-8 shrink-0 text-right font-semibold tabular-nums ${qeStyle(s.qe ?? 0)}`}>{s.qe}</span>
                <SegLink id={s.id} onOpen={onOpenSegment} />
                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                  <Markdown text={s.target ?? s.source} inline />
                </span>
                {issueCount.get(s.id) ? <span className="shrink-0 text-warn-fg">{issueCount.get(s.id)} QA</span> : null}
                <span className="shrink-0 text-muted-foreground capitalize">{s.status}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

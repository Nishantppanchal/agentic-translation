"use client";

import { Eye, EyeOff, Gauge, Loader2, Play, ShieldCheck, Wand2 } from "lucide-react";
import { useMemo, useState } from "react";
import type { DocumentState, LqaResult, QaIssue, Severity } from "@/lib/types";
import type { QaState } from "../cat/useQa";

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
const SEV_STYLE: Record<string, string> = {
  error: "bg-del text-del-fg",
  warning: "bg-warn text-warn-fg",
  critical: "bg-del-fg text-white",
  major: "bg-del text-del-fg",
  minor: "bg-warn text-warn-fg",
};

export const qeStyle = (qe: number) => (qe >= 90 ? "text-ins-fg" : qe >= 70 ? "text-warn-fg" : "text-del-fg");

function SegLink({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return (
    <button onClick={() => onOpen(id)} className="shrink-0 font-mono text-[11px] text-muted hover:text-accent" title="Open in the segment editor">
      {id}
    </button>
  );
}

function QaSection({ qa, onOpen }: { qa: QaState; onOpen: (id: string) => void }) {
  const [check, setCheck] = useState<string | null>(null);
  const [showIgnored, setShowIgnored] = useState(false);
  const report = qa.report;
  if (!report) return <p className="text-sm text-muted">Running checks…</p>;
  const { summary } = report;
  const shown = report.issues.filter((i) => (showIgnored || !i.ignored) && (!check || i.check === check));
  const checks = report.checks.filter((c) => summary.by_check[c.id] > 0);

  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <ShieldCheck size={16} className="text-muted" />
        <h3 className="font-semibold">Automatic QA</h3>
        <span className="text-xs text-muted">
          {summary.errors} error{summary.errors === 1 ? "" : "s"} · {summary.warnings} warning{summary.warnings === 1 ? "" : "s"}
          {summary.ignored ? ` · ${summary.ignored} ignored` : ""}
        </span>
        {summary.ignored > 0 && (
          <button onClick={() => setShowIgnored((v) => !v)} className="ml-auto flex items-center gap-1 text-xs text-muted hover:text-fg">
            {showIgnored ? <EyeOff size={12} /> : <Eye size={12} />} {showIgnored ? "Hide" : "Show"} ignored
          </button>
        )}
      </div>
      <p className="mb-2 text-xs text-muted">
        Numbers and dates, termbase and forbidden terms, markup, punctuation, consistency and length — checked on every change.
        Errors are sent to the AI reviewer as must-fix issues; warnings may be false alarms, so ignore the ones that are fine.
      </p>
      {checks.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5 text-xs">
          <button onClick={() => setCheck(null)} className={`rounded-full px-2.5 py-0.5 ${!check ? "bg-fg text-bg" : "bg-sidebar text-muted hover:text-fg"}`}>
            All
          </button>
          {checks.map((c) => (
            <button
              key={c.id}
              onClick={() => setCheck(c.id === check ? null : c.id)}
              className={`rounded-full px-2.5 py-0.5 ${check === c.id ? "bg-fg text-bg" : "bg-sidebar text-muted hover:text-fg"}`}
            >
              {c.label} {summary.by_check[c.id]}
            </button>
          ))}
        </div>
      )}
      {shown.length === 0 ? (
        <p className="rounded-md bg-ins px-3 py-2 text-sm text-ins-fg">No open QA issues.</p>
      ) : (
        <ul className="divide-y divide-border">
          {shown.map((i: QaIssue) => (
            <li key={i.id} className={`group flex items-start gap-2 py-1.5 text-xs ${i.ignored ? "opacity-50" : ""}`}>
              <span className={`mt-0.5 shrink-0 rounded px-1.5 text-[10px] font-medium uppercase ${SEV_STYLE[i.severity]}`}>{i.severity}</span>
              <SegLink id={i.segment_id} onOpen={onOpen} />
              <span className="shrink-0 text-muted">{i.label}</span>
              <span className="flex-1">{i.message}</span>
              <button
                onClick={() => qa.ignore([i.id], !i.ignored)}
                className="shrink-0 text-muted opacity-0 group-hover:opacity-100 hover:text-fg"
                title={i.ignored ? "Show this issue again" : "Ignore (it comes back if the text changes)"}
              >
                {i.ignored ? "Restore" : "Ignore"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Scorecard({ lqa, latest, onOpen }: { lqa: LqaResult; latest: number; onOpen: (id: string) => void }) {
  const rows = Object.entries(lqa.matrix);
  return (
    <div>
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <div className={`text-4xl font-semibold tabular-nums ${lqa.passed ? "text-ins-fg" : "text-del-fg"}`}>{lqa.score.toFixed(1)}</div>
          <div className="text-xs text-muted">MQM quality score</div>
        </div>
        <span className={`mb-1 rounded px-2 py-0.5 text-xs font-semibold ${lqa.passed ? "bg-ins text-ins-fg" : "bg-del text-del-fg"}`}>
          {lqa.passed ? "PASS" : "FAIL"} · threshold {lqa.threshold}
        </span>
        <div className="mb-1 text-xs text-muted">
          {lqa.penalty} penalty point{lqa.penalty === 1 ? "" : "s"} in {lqa.words} source words
          <br />
          v{lqa.version ?? "?"} · {lqa.model} · {new Date(lqa.at * 1000).toLocaleString()}
          {lqa.version !== null && lqa.version < latest && <span className="text-warn-fg"> · translation changed since (v{latest})</span>}
        </div>
      </div>
      <table className="mt-3 w-full text-left text-xs">
        <thead className="text-muted">
          <tr className="border-b border-border">
            <th className="py-1 font-medium">Category</th>
            {SEVERITIES.map((s) => (
              <th key={s} className="py-1 text-right font-medium capitalize">
                {s} <span className="font-normal">×{PENALTY[s]}</span>
              </th>
            ))}
            <th className="py-1 text-right font-medium">Points</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([cat, counts]) => {
            const points = SEVERITIES.reduce((n, s) => n + counts[s] * PENALTY[s], 0);
            return (
              <tr key={cat} className="border-b border-border">
                <td className="py-1">{CATEGORY_LABEL[cat] ?? cat}</td>
                {SEVERITIES.map((s) => (
                  <td key={s} className={`py-1 text-right tabular-nums ${counts[s] ? "font-semibold" : "text-muted"}`}>
                    {counts[s]}
                  </td>
                ))}
                <td className={`py-1 text-right tabular-nums ${points ? "font-semibold" : "text-muted"}`}>{points}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-1 text-[11px] text-muted">Score = 100 − penalty points per 1000 source words (MQM weights: minor 1, major 5, critical 25).</p>
      {lqa.errors.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {lqa.errors.map((e, k) => (
            <li key={k} className="flex items-start gap-2 text-xs">
              <span className={`mt-0.5 shrink-0 rounded px-1.5 text-[10px] font-medium uppercase ${SEV_STYLE[e.severity]}`}>{e.severity}</span>
              <SegLink id={e.segment_id} onOpen={onOpen} />
              <span className="shrink-0 text-muted">{CATEGORY_LABEL[e.category ?? "other"]}</span>
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
    <div className="space-y-8 text-sm">
      <QaSection qa={qa} onOpen={onOpenSegment} />
      {fixable > 0 && (
        <div className="-mt-5 flex items-center gap-2 rounded-md bg-accent-soft px-3 py-2 text-xs">
          <Wand2 size={14} className="text-accent" />
          <span className="flex-1">
            {fixable} consistency or terminology issue{fixable === 1 ? "" : "s"}. The agent can unify repeated sentences (your confirmed
            translations win) and apply the termbase — as a proposal you review.
          </span>
          <button
            onClick={fix}
            disabled={!canRun}
            className="rounded-md bg-accent px-2.5 py-1 font-medium text-white disabled:opacity-40"
          >
            Fix consistency
          </button>
        </div>
      )}

      <section>
        <div className="mb-2 flex items-center gap-2">
          <Gauge size={16} className="text-muted" />
          <h3 className="font-semibold">Quality score (LQA)</h3>
          <button
            onClick={run}
            disabled={!canRun || starting}
            className="ml-auto flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:border-accent disabled:opacity-40"
            title="An independent AI assessor annotates errors with MQM categories and severities. Nothing is changed."
          >
            {starting ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} {doc.lqa ? "Run again" : "Run LQA"}
          </button>
        </div>
        {error && <div className="mb-2 rounded bg-del px-2 py-1 text-xs text-del-fg">{error}</div>}
        {doc.lqa ? (
          <Scorecard lqa={doc.lqa} latest={latest} onOpen={onOpenSegment} />
        ) : (
          <p className="text-xs text-muted">
            Not assessed yet. LQA scores the current version the way an LSP reviewer would: every error gets an MQM category
            and severity, and the document passes or fails against the project&apos;s threshold. Set <code>LQA_MODEL</code> for a
            second opinion from a different model.
          </p>
        )}
      </section>

      <section>
        <h3 className="mb-1 font-semibold">Review queue</h3>
        <p className="mb-2 text-xs text-muted">
          Segments with the lowest AI quality estimate first (from the last review or LQA), so a human reviewer starts where it
          matters. Reviewed segments drop off.
        </p>
        {queue.length === 0 ? (
          <p className="text-xs text-muted">No scored segments waiting.</p>
        ) : (
          <ul className="divide-y divide-border">
            {queue.map((s) => (
              <li key={s.id} className="flex items-center gap-3 py-1.5 text-xs">
                <span className={`w-8 shrink-0 text-right font-semibold tabular-nums ${qeStyle(s.qe ?? 0)}`}>{s.qe}</span>
                <SegLink id={s.id} onOpen={onOpenSegment} />
                <span className="min-w-0 flex-1 truncate text-muted">{s.target ?? s.source}</span>
                {issueCount.get(s.id) ? <span className="shrink-0 text-warn-fg">{issueCount.get(s.id)} QA</span> : null}
                <span className="shrink-0 capitalize text-muted">{s.status}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

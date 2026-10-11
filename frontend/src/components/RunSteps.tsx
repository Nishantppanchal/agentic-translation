"use client";

import { Check, CircleHelp, Download, FileCheck2, Gauge, ListChecks, Loader2, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DocFormat, DocStatus, LqaResult, Progress, Segment } from "@/lib/types";

const STEPS = ["Read", "Analyse", "Translate", "Review", "Ready"] as const;

/** Where a pipeline run is: progress stages and statuses mapped onto the five steps people see. */
function stepOf(progress: Progress | null, status: DocStatus | undefined, translated: boolean): number {
  if (status === "ready") return 4;
  switch (progress?.stage) {
    case "queued":
    case "ocr":
    case "extract":
      return 0;
    case "analyse":
      return 1;
    case "clarify": // the questions before translating belong to the analysis; later ones to the translation
      return translated ? 2 : 1;
    case "translate":
      return 2;
    case "review":
    case "refine":
      return 3;
    case "done":
      return 4;
  }
  // No live progress (e.g. a paused run after a reload): go by the document's status.
  if (status === "awaiting_answers") return translated ? 2 : 1;
  return status === "translating" ? 2 : status === "reviewing" ? 3 : 0;
}

function Elapsed() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const t = setInterval(() => setSeconds(Math.round((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <span className="tabular-nums">
      {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
    </span>
  );
}

/** The pipeline as steps — Read → Analyse → Translate → Review → Ready — with the live progress of the current one. */
export function RunSteps({
  progress,
  status,
  running,
  segments,
}: {
  progress: Progress | null;
  status: DocStatus | undefined;
  running: boolean;
  segments: Segment[];
}) {
  const waiting = status === "awaiting_answers" && !running;
  const current = stepOf(progress, status, segments.some((s) => s.translatable && s.target));
  return (
    <div className="rounded-xl border border-border bg-panel p-3 text-sm">
      <ol className="flex items-center">
        {STEPS.map((label, i) => {
          const done = i < current;
          const now = i === current;
          return (
            <li key={label} className="flex flex-1 items-center last:flex-none">
              <div className="flex flex-col items-center gap-1">
                <span
                  className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-medium ${
                    done
                      ? "bg-accent text-white"
                      : now
                        ? waiting
                          ? "bg-warn text-warn-fg ring-2 ring-warn-fg/40"
                          : "bg-accent-soft text-accent ring-2 ring-accent/40"
                        : "bg-sidebar text-muted"
                  }`}
                >
                  {done ? <Check size={13} /> : now && waiting ? <CircleHelp size={13} /> : now && running ? <Loader2 size={12} className="animate-spin" /> : i + 1}
                </span>
                <span className={`text-[11px] ${now ? "font-medium text-fg" : "text-muted"}`}>{label}</span>
              </div>
              {i < STEPS.length - 1 && <div className={`mx-1 mb-4 h-0.5 flex-1 rounded ${done ? "bg-accent" : "bg-border"}`} />}
            </li>
          );
        })}
      </ol>
      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted">
        <span className="truncate">
          {waiting ? "Waiting for your answers below — the agents continue as soon as you decide." : (progress?.message ?? "Working…")}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {!waiting && progress && progress.total > 0 && (
            <span>
              {progress.current}/{progress.total}
            </span>
          )}
          {running && <Elapsed />}
        </span>
      </div>
      {!waiting && progress && progress.total > 0 && (
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-sidebar">
          <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.round((100 * progress.current) / progress.total)}%` }} />
        </div>
      )}
    </div>
  );
}

/** After a run: the obvious next actions as buttons instead of a paragraph of instructions. */
export function NextSteps({
  sessionId,
  segments,
  format,
  lqa,
  versionCount,
  onOpenSegments,
  onFixQa,
  onRunLqa,
}: {
  sessionId: string;
  segments: Segment[];
  format: DocFormat | null;
  lqa: LqaResult | null;
  versionCount: number;
  onOpenSegments: () => void;
  onFixQa: () => void;
  onRunLqa: () => void;
}) {
  const [qaErrors, setQaErrors] = useState<number | null>(null);
  const [download, setDownload] = useState<{ id: string; label: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .qa(sessionId)
      .then((r) => !cancelled && setQaErrors(r.summary.errors))
      .catch(() => {});
    api
      .exportFormats(sessionId)
      .then((formats) => {
        const best = formats.find((f) => f.available && (f.id === "original" || f.id === "pdf")) ?? formats.find((f) => f.id === "docx");
        if (!cancelled && best) setDownload({ id: best.id, label: best.id === "original" ? `Download the ${format?.toUpperCase()} file` : best.id === "pdf" ? "Download the PDF" : "Download Word" });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sessionId, versionCount, format]);

  const drafts = segments.filter((s) => s.translatable && (s.status === "draft" || s.status === "new")).length;
  const btn = "flex items-center gap-1.5 rounded-lg border border-border bg-panel px-2.5 py-1.5 text-xs hover:border-accent";
  return (
    <div className="rounded-xl border border-border bg-bg p-3">
      <div className="mb-2 text-xs font-medium tracking-wide text-muted uppercase">Next steps</div>
      <div className="flex flex-wrap gap-2">
        {drafts > 0 && (
          <button onClick={onOpenSegments} className={btn}>
            <ListChecks size={14} className="text-accent" /> Review {drafts} draft{drafts === 1 ? "" : "s"}
          </button>
        )}
        {!!qaErrors && (
          <button onClick={onFixQa} className={btn} title="The agent runs the QA checks and proposes fixes">
            <Wrench size={14} className="text-del-fg" /> Fix {qaErrors} QA error{qaErrors === 1 ? "" : "s"}
          </button>
        )}
        <button onClick={onRunLqa} className={btn} title="An independent model scores the translation (MQM)">
          <Gauge size={14} className="text-accent" /> {lqa ? "Re-check quality score" : "Check quality score"}
        </button>
        {download && (
          <a href={api.exportUrl(sessionId, undefined, "target", download.id)} className={btn}>
            <Download size={14} className="text-accent" /> {download.label}
          </a>
        )}
        {drafts === 0 && !qaErrors && (
          <span className="flex items-center gap-1.5 px-1 text-xs text-ins-fg">
            <FileCheck2 size={14} /> Every segment is confirmed
          </span>
        )}
      </div>
    </div>
  );
}

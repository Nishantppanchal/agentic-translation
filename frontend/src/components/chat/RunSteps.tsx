"use client";

import { Check, CircleHelp, Download, FileCheck2, Gauge, ListChecks, Loader2, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Progress as Bar } from "@/components/ui/progress";
import { api } from "@/lib/api";
import type { DocStatus, ExportFormat, LqaResult, Progress, Segment } from "@/lib/types";

const STEPS = ["Read", "Analyse", "Translate", "Review", "Ready"] as const;
const WITH_CHECK = ["Read", "Check", "Analyse", "Translate", "Review", "Ready"] as const; // PDFs and images

/** Where a pipeline run is: progress stages and statuses mapped onto the steps people see (with the source check
 * after reading for PDFs and images). */
function stepOf(progress: Progress | null, status: DocStatus | undefined, translated: boolean, check: boolean): number {
  if (progress?.stage === "check" || status === "awaiting_source_check") return 1;
  const base = baseStep(progress, status, translated);
  return check && base >= 1 ? base + 1 : base;
}

function baseStep(progress: Progress | null, status: DocStatus | undefined, translated: boolean): number {
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
  check = false,
}: {
  progress: Progress | null;
  status: DocStatus | undefined;
  running: boolean;
  segments: Segment[];
  check?: boolean; // the document is read with OCR, so it stops for the source check
}) {
  const checking = status === "awaiting_source_check" && !running;
  const waiting = (status === "awaiting_answers" || checking) && !running;
  const steps = check ? WITH_CHECK : STEPS;
  const current = stepOf(progress, status, segments.some((s) => s.translatable && s.target), check);
  return (
    <div className="rounded-xl border border-border bg-card p-3.5 text-sm shadow-xs">
      <ol className="flex items-center">
        {steps.map((label, i) => {
          const done = i < current;
          const now = i === current;
          return (
            <li key={label} className="flex flex-1 items-center last:flex-none">
              <div className="flex flex-col items-center gap-1">
                <span
                  className={cn(
                    "flex size-6 items-center justify-center rounded-full text-[11px] font-medium transition-colors duration-300",
                    done
                      ? "bg-primary text-primary-foreground"
                      : now
                        ? waiting
                          ? "bg-warn text-warn-fg ring-2 ring-warn-fg/40"
                          : "bg-primary-soft text-primary ring-2 ring-primary/40"
                        : "bg-muted text-muted-foreground",
                  )}
                >
                  {done ? <Check size={13} /> : now && waiting ? <CircleHelp size={13} /> : now && running ? <Loader2 size={12} className="animate-spin" /> : i + 1}
                </span>
                <span className={`text-[11px] ${now ? "font-medium text-foreground" : "text-muted-foreground"}`}>{label}</span>
              </div>
              {i < steps.length - 1 && (
                <div className="relative mx-1 mb-4 h-0.5 flex-1 overflow-hidden rounded bg-border">
                  <div className={cn("absolute inset-0 origin-left bg-primary transition-transform duration-500", done ? "scale-x-100" : "scale-x-0")} />
                </div>
              )}
            </li>
          );
        })}
      </ol>
      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="truncate">
          {checking
            ? "Check the source text — ask me to fix anything, then press Continue to translation."
            : waiting
              ? "Waiting for your answers below — the agents continue as soon as you decide."
              : (progress?.message ?? "Working…")}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {!waiting && progress && progress.total > 0 && (
            <span className="tabular-nums">
              {progress.current}/{progress.total}
            </span>
          )}
          {running && <Elapsed />}
        </span>
      </div>
      {!waiting && progress && progress.total > 0 && (
        <Bar value={Math.round((100 * progress.current) / progress.total)} className="mt-1.5 h-1 bg-muted" aria-label="Progress" />
      )}
    </div>
  );
}

/** After a run: the obvious next actions as buttons instead of a paragraph of instructions. */
export function NextSteps({
  sessionId,
  segments,
  lqa,
  versionCount,
  onOpenSegments,
  onFixQa,
  onRunLqa,
}: {
  sessionId: string;
  segments: Segment[];
  lqa: LqaResult | null;
  versionCount: number;
  onOpenSegments: () => void;
  onFixQa: () => void;
  onRunLqa: () => void;
}) {
  const [qaErrors, setQaErrors] = useState<number | null>(null);
  const [canDownload, setCanDownload] = useState<ExportFormat["id"] | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .qa(sessionId)
      .then((r) => !cancelled && setQaErrors(r.summary.errors))
      .catch(() => {});
    api
      .exportFormats(sessionId)
      // The translated Word / PowerPoint / Excel file for Office uploads, else the Word export.
      .then((formats) => !cancelled && setCanDownload(formats.find((f) => f.available && (f.id === "office" || f.id === "docx"))?.id ?? null))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sessionId, versionCount]);

  const drafts = segments.filter((s) => s.translatable && (s.status === "draft" || s.status === "new")).length;
  return (
    <div className="rounded-xl border border-border bg-card/60 p-3">
      <div className="mb-2 text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">Next steps</div>
      <div className="flex flex-wrap gap-2">
        {drafts > 0 && (
          <Button variant="outline" size="sm" onClick={onOpenSegments} className="bg-card">
            <ListChecks className="text-primary" /> Review {drafts} draft{drafts === 1 ? "" : "s"}
          </Button>
        )}
        {!!qaErrors && (
          <Button variant="outline" size="sm" onClick={onFixQa} className="bg-card" title="The agent runs the QA checks and proposes fixes">
            <Wrench className="text-del-fg" /> Fix {qaErrors} QA error{qaErrors === 1 ? "" : "s"}
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={onRunLqa} className="bg-card" title="An independent model scores the translation (MQM)">
          <Gauge className="text-primary" /> {lqa ? "Re-check quality score" : "Check quality score"}
        </Button>
        {canDownload && (
          <Button variant="outline" size="sm" asChild className="bg-card">
            <a href={api.exportUrl(sessionId, undefined, "target", canDownload)}>
              <Download className="text-primary" /> {canDownload === "office" ? "Download the translated file" : "Download Word"}
            </a>
          </Button>
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

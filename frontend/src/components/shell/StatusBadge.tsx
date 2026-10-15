import { cn } from "cn";
import type { DocStatus } from "@/lib/types";

const LABELS: Record<DocStatus, string> = {
  uploaded: "Queued",
  reading: "Reading",
  ocr: "OCR",
  ocr_check: "Checking OCR",
  translating: "Translating",
  awaiting_answers: "Needs input",
  awaiting_source_check: "Check source",
  reviewing: "Reviewing",
  ready: "Ready",
  error: "Error",
};

const WORKING: DocStatus[] = ["uploaded", "reading", "ocr", "ocr_check", "translating", "reviewing"];

/** A document's status as a pill: green when ready, amber when it waits for you, red on an error, blue (with a
 * pulsing dot) while the agents work. */
export function StatusBadge({ status, compact = false, className }: { status: DocStatus; compact?: boolean; className?: string }) {
  const tone =
    status === "ready"
      ? "bg-ins text-ins-fg"
      : status === "error"
        ? "bg-del text-del-fg"
        : status === "awaiting_answers" || status === "awaiting_source_check"
          ? "bg-warn text-warn-fg"
          : "bg-primary-soft text-primary";
  const working = WORKING.includes(status);
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full font-medium whitespace-nowrap",
        compact ? "h-4 px-1.5 text-[10px]" : "h-5 px-2 text-xs",
        tone,
        className,
      )}
    >
      {working && <span className="size-1.5 rounded-full bg-current motion-safe:animate-pulse" aria-hidden />}
      {LABELS[status] ?? status}
    </span>
  );
}

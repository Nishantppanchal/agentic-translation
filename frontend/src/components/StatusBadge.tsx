import type { DocStatus } from "@/lib/types";

const LABELS: Record<DocStatus, string> = {
  uploaded: "Queued",
  ocr: "OCR",
  ocr_check: "Checking OCR",
  translating: "Translating",
  awaiting_answers: "Needs input",
  reviewing: "Reviewing",
  ready: "Ready",
  error: "Error",
};

export function StatusBadge({ status, compact = false }: { status: DocStatus; compact?: boolean }) {
  const tone =
    status === "ready"
      ? "bg-ins text-ins-fg"
      : status === "error"
        ? "bg-del text-del-fg"
        : status === "awaiting_answers"
          ? "bg-warn text-warn-fg"
        : "bg-accent-soft text-accent";
  return (
    <span className={`shrink-0 rounded-full ${compact ? "px-1.5 text-[10px]" : "px-2 py-0.5 text-xs"} font-medium ${tone}`}>
      {LABELS[status] ?? status}
    </span>
  );
}

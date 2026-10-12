"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { LayoutBox, LayoutReport, LayoutStatus, Segment } from "@/lib/types";

const BOX_STYLE: Record<LayoutStatus, string> = {
  fit: "border-accent/30 hover:border-accent hover:bg-accent/5",
  shrunk: "border-warn-fg/70 bg-warn/20",
  overflow: "border-del-fg bg-del/30",
  unaligned: "border-del-fg",
};
const LABEL: Record<LayoutStatus, string> = {
  fit: "fit",
  shrunk: "shrunk to fit",
  overflow: "didn't fit — original kept",
  unaligned: "not found in the PDF",
};

function Boxes({ boxes, selected, onSelect }: { boxes: (LayoutBox & { id: string })[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <>
      {boxes.map((b, i) => {
        const [x0, y0, x1, y1] = b.rect;
        return (
          <button
            key={`${b.id}-${i}`}
            onClick={() => onSelect(b.id)}
            title={`${b.id}: ${LABEL[b.status]}`}
            className={`absolute rounded-sm border ${BOX_STYLE[b.status]} ${selected === b.id ? "!border-2 !border-accent !bg-accent/10" : ""}`}
            style={{
              left: `${(100 * x0) / b.width}%`,
              top: `${(100 * y0) / b.height}%`,
              width: `${(100 * (x1 - x0)) / b.width}%`,
              height: `${(100 * (y1 - y0)) / b.height}%`,
            }}
          />
        );
      })}
    </>
  );
}

/** Original page next to the layout-preserving translated page, with per-segment fit results. */
export function LayoutView({
  sessionId,
  version,
  segments,
  onReference,
}: {
  sessionId: string;
  version?: number;
  segments: Segment[];
  onReference: (id: string) => void;
}) {
  // Results are keyed by session+version, so switching versions shows "loading" without resetting state.
  const key = `${sessionId}:${version ?? "latest"}`;
  const [result, setResult] = useState<{ key: string; report?: LayoutReport; error?: string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .previewReport(sessionId, version)
      .then((report) => !cancelled && setResult({ key, report }))
      .catch((e) => !cancelled && setResult({ key, error: String(e).replace(/^Error: \d+: /, "") }));
    return () => {
      cancelled = true;
    };
  }, [sessionId, version, key]);

  const report = result?.key === key ? (result.report ?? null) : null;
  const error = result?.key === key ? result.error : null;

  if (error) return <p className="text-sm text-muted">{error}</p>;
  if (!report)
    return (
      <p className="flex items-center gap-2 text-sm text-muted">
        <Loader2 size={14} className="animate-spin" /> Typesetting the translation into the original layout…
      </p>
    );

  const boxes = Object.entries(report.segments).flatMap(([id, s]) => s.boxes.map((b) => ({ ...b, id })));
  const problems = Object.entries(report.segments).filter(([, s]) => s.status === "overflow" || s.status === "unaligned");
  const source = new Map(segments.map((s) => [s.id, s.source]));
  const pick = (id: string) => {
    setSelected(id);
    onReference(id);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted">Layout of v{report.version}:</span>
        <span className="rounded bg-sidebar px-1.5 py-0.5">{report.summary.fit} fit</span>
        <span className="rounded bg-warn px-1.5 py-0.5 text-warn-fg">{report.summary.shrunk} shrunk</span>
        <span className="rounded bg-del px-1.5 py-0.5 text-del-fg">
          {report.summary.overflow + report.summary.unaligned} need attention
        </span>
        <a href={api.exportUrl(sessionId, report.version, "target", "pdf")} className="ml-auto text-accent hover:underline">
          Download PDF
        </a>
      </div>

      {!!report.summary.by_position && (
        <div className="rounded-lg bg-accent-soft/60 p-2.5 text-xs">
          {report.summary.by_position} segment{report.summary.by_position === 1 ? " was" : "s were"} placed by position between
          their neighbours because the reading differs from the PDF&apos;s text there —{" "}
          {Object.entries(report.segments)
            .filter(([, s]) => s.matched === "position")
            .map(([id]) => (
              <button key={id} onClick={() => pick(id)} className="mr-1.5 font-mono underline-offset-2 hover:underline">
                {id}
              </button>
            ))}
          — worth a look.
        </div>
      )}

      {problems.length > 0 && (
        <div className="rounded-lg bg-del/40 p-2.5 text-xs text-del-fg">
          <div className="mb-1 flex items-center gap-1 font-medium">
            <AlertTriangle size={13} /> Kept in the original language (shorten the translation or edit in a reflowed export):
          </div>
          {problems.map(([id, s]) => (
            <button key={id} onClick={() => pick(id)} className="mr-3 underline-offset-2 hover:underline">
              {id} · {LABEL[s.status]}
              <span className="text-muted"> — {(source.get(id) ?? "").slice(0, 40)}…</span>
            </button>
          ))}
        </div>
      )}

      {Array.from({ length: report.pages }, (_, i) => i + 1).map((p) => {
        const pageBoxes = boxes.filter((b) => b.page === p);
        return (
          <div key={p}>
            <div className="mb-1 grid grid-cols-2 gap-3 text-[10px] tracking-wide text-muted uppercase">
              <span>Original · page {p}</span>
              <span>Translated · page {p}</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[api.pageImageUrl(sessionId, p), api.previewPageUrl(sessionId, p, report.version)].map((src, side) => (
                <div key={side} className="relative h-fit overflow-hidden rounded-md border border-border bg-white">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={src} alt={`${side ? "Translated" : "Original"} page ${p}`} className="block w-full" />
                  <Boxes boxes={pageBoxes} selected={selected} onSelect={pick} />
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

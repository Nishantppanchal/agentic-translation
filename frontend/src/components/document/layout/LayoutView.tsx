"use client";

import { AlertTriangle, Link2, Link2Off, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Toggle } from "@/components/ui/toggle";
import { api } from "@/lib/api";
import type { DocumentState, OfficeWriteReport, Segment, SheetGrid } from "@/lib/types";
import { DocxPane, type PaneHandle } from "./DocxPane";
import { PptxPane, type SlidesHandle } from "./PptxPane";
import { cellText, SheetPane } from "./SheetPane";

/** A Word, PowerPoint or Excel upload as it looks: the original next to the translated file (as of the version
 * picked in the header). The translated side is the real file the download gives. */
export function LayoutView({
  sessionId,
  doc,
  segments,
  version,
  latest,
  highlight,
  onPick,
}: {
  sessionId: string;
  doc: DocumentState;
  segments: Segment[]; // with the targets of the version shown
  version: number | undefined; // undefined: the current state
  latest: number;
  highlight: string | null;
  onPick: (segId: string) => void; // open a segment (from a click in the translated file)
}) {
  const fmt = doc.office?.format;
  const [sync, setSync] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [report, setReport] = useState<OfficeWriteReport | null>(null);
  const [showReport, setShowReport] = useState(false);
  // The translated file is written again when a version is saved or a segment is edited by hand.
  const targetKey = `${version ?? `${latest}:${doc.human_dirty.join(",")}`}:${refresh}`;
  const bySeg = useMemo(() => new Map(segments.map((s) => [s.id, s])), [segments]);

  useEffect(() => {
    let cancelled = false;
    api
      .officeReport(sessionId, version)
      .then((r) => !cancelled && setReport(r.write))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sessionId, version, targetKey]);

  const skipped = Object.entries(doc.office?.not_translated ?? {}).filter(([k]) => k !== "sheet names");
  const problems = (report?.mismatch.length ?? 0) + (report?.anchors_moved.length ?? 0) + (report?.formatting_simplified.length ?? 0);

  return (
    <div className="flex h-full min-h-[480px] flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <Toggle
          size="sm"
          variant="outline"
          pressed={sync}
          onPressedChange={setSync}
          className="h-7 text-xs data-[state=on]:border-primary/50 data-[state=on]:bg-primary-soft data-[state=on]:text-primary"
          aria-label="Scroll both sides together"
        >
          {sync ? <Link2 /> : <Link2Off />} Sync scroll
        </Toggle>
        <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setRefresh((n) => n + 1)}>
          <RefreshCw /> Refresh
        </Button>
        {(skipped.length > 0 || problems > 0 || !!doc.office?.tracked_changes) && (
          <Popover open={showReport} onOpenChange={setShowReport}>
            <PopoverTrigger asChild>
              <button className="flex h-7 items-center gap-1 rounded-md bg-warn px-2.5 font-medium text-warn-fg">
                <AlertTriangle size={12} />
                {problems ? `${problems} to check` : "Not translated"}
              </button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-80 text-xs">
              {!!doc.office?.tracked_changes && <p className="mb-1.5">{doc.office.tracked_changes} tracked change(s) were accepted before translating.</p>}
              {skipped.length > 0 && (
                <p className="mb-1.5">
                  <span className="font-medium">Left as they are:</span> {skipped.map(([k, v]) => `${v} ${k}`).join(", ")}.
                </p>
              )}
              {report && (
                <ReportList
                  report={report}
                  onPick={(id) => {
                    setShowReport(false);
                    onPick(id);
                  }}
                />
              )}
            </PopoverContent>
          </Popover>
        )}
        {latest === 0 && <span className="text-muted-foreground">The translation appears here as each version is saved.</span>}
      </div>
      {fmt === "docx" && (
        <DocxSides sessionId={sessionId} version={version} targetKey={targetKey} sync={sync} highlight={highlight} onPick={onPick} />
      )}
      {fmt === "pptx" && (
        <PptxSides sessionId={sessionId} version={version} targetKey={targetKey} sync={sync} segments={segments} highlight={highlight} bySeg={bySeg} />
      )}
      {fmt === "xlsx" && <SheetSides sessionId={sessionId} bySeg={bySeg} highlight={highlight} sync={sync} onPick={onPick} />}
    </div>
  );
}

function ReportList({ report, onPick }: { report: OfficeWriteReport; onPick: (id: string) => void }) {
  const rows: [string, string[]][] = [
    ["Changed in the file since it was read (left as it was)", report.mismatch],
    ["A footnote mark or picture the translation lost (kept, near the end)", report.anchors_moved],
    ["Formatting simplified (e.g. a colour or underline only)", report.formatting_simplified],
  ];
  return (
    <div className="space-y-1.5">
      {rows
        .filter(([, ids]) => ids.length)
        .map(([label, ids]) => (
          <div key={label}>
            <div className="text-muted-foreground">{label}:</div>
            <div className="flex flex-wrap gap-1">
              {ids.map((id) => (
                <button key={id} onClick={() => onPick(id)} className="rounded bg-muted px-1 font-mono text-[10px] hover:text-primary">
                  {id}
                </button>
              ))}
            </div>
          </div>
        ))}
      {report.autofit.length > 0 && (
        <div className="text-muted-foreground">
          Shrunk to fit: {report.autofit.map((a) => `${a.where} (${Math.round(a.scale * 100)}%)`).join(", ")}
        </div>
      )}
      {report.formulas_updated > 0 && <div className="text-muted-foreground">{report.formulas_updated} formula text(s) translated.</div>}
    </div>
  );
}

function Side({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="mb-1.5 text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">{label}</div>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}

function DocxSides({
  sessionId,
  version,
  targetKey,
  sync,
  highlight,
  onPick,
}: {
  sessionId: string;
  version: number | undefined;
  targetKey: string;
  sync: boolean;
  highlight: string | null;
  onPick: (id: string) => void;
}) {
  const left = useRef<PaneHandle>(null);
  const right = useRef<PaneHandle>(null);
  const echo = useRef(false);
  const follow = (fromLeft: boolean) => {
    const [from, to] = fromLeft ? [left.current, right.current] : [right.current, left.current];
    if (!sync || echo.current) {
      echo.current = false;
      return;
    }
    const seg = from?.topSegment();
    if (seg) {
      echo.current = true;
      to?.scrollToSegment(seg);
    }
  };
  useEffect(() => {
    if (!highlight) return;
    left.current?.locate(highlight);
    right.current?.locate(highlight);
  }, [highlight]);
  return (
    <div className="flex min-h-0 flex-1 gap-3">
      <Side label="Original">
        <DocxPane ref={left} url={api.officeFileUrl(sessionId, "source", undefined, true)} refreshKey="source" onScroll={() => follow(true)} />
      </Side>
      <Side label={`Translation${version ? ` v${version}` : ""}`}>
        <DocxPane
          ref={right}
          url={api.officeFileUrl(sessionId, "target", version, true)}
          refreshKey={targetKey}
          onScroll={() => follow(false)}
          onPick={onPick}
        />
      </Side>
    </div>
  );
}

function PptxSides({
  sessionId,
  version,
  targetKey,
  sync,
  segments,
  highlight,
  bySeg,
}: {
  sessionId: string;
  version: number | undefined;
  targetKey: string;
  sync: boolean;
  segments: Segment[];
  highlight: string | null;
  bySeg: Map<string, Segment>;
}) {
  const left = useRef<SlidesHandle>(null);
  const right = useRef<SlidesHandle>(null);
  const [slide, setSlide] = useState(0);
  const notes = segments.filter((s) => s.kind === "note" && s.page === slide + 1);
  useEffect(() => {
    const seg = highlight ? bySeg.get(highlight) : undefined;
    if (!seg) return;
    left.current?.find(seg.page - 1, cellText(seg.source));
    if (seg.target) right.current?.find(seg.page - 1, cellText(seg.target));
  }, [highlight, bySeg]);
  const moved = (fromLeft: boolean, i: number) => {
    setSlide(i);
    if (sync) (fromLeft ? right.current : left.current)?.goTo(i);
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex min-h-0 flex-1 gap-3">
        <Side label="Original">
          <PptxPane ref={left} url={api.officeFileUrl(sessionId, "source")} refreshKey="source" onSlide={(i) => moved(true, i)} />
        </Side>
        <Side label={`Translation${version ? ` v${version}` : ""}`}>
          <PptxPane ref={right} url={api.officeFileUrl(sessionId, "target", version)} refreshKey={targetKey} onSlide={(i) => moved(false, i)} />
        </Side>
      </div>
      {notes.length > 0 && (
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-background p-3 text-xs">
          <div>
            <div className="mb-0.5 text-[10px] tracking-wide text-muted-foreground uppercase">Notes · slide {slide + 1}</div>
            {notes.map((n) => (
              <p key={n.id}>{cellText(n.source)}</p>
            ))}
          </div>
          <div>
            <div className="mb-0.5 text-[10px] tracking-wide text-muted-foreground uppercase">Notes · translation</div>
            {notes.map((n) => (
              <p key={n.id} className={n.target ? "" : "text-muted-foreground italic"}>
                {cellText(n.target ?? n.source)}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function SheetSides({
  sessionId,
  bySeg,
  highlight,
  sync,
  onPick,
}: {
  sessionId: string;
  bySeg: Map<string, Segment>;
  highlight: string | null;
  sync: boolean;
  onPick: (id: string) => void;
}) {
  const [grid, setGrid] = useState<SheetGrid | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setSheet] = useState(0);
  const left = useRef<HTMLDivElement>(null);
  const right = useRef<HTMLDivElement>(null);
  const echo = useRef(false);
  useEffect(() => {
    let cancelled = false;
    api
      .officeSheets(sessionId)
      .then((g) => !cancelled && setGrid(g))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);
  // A highlighted segment opens the sheet it is on.
  const sheetOfHighlight = highlight && grid ? grid.sheets.findIndex((s) => s.rows.some((r) => r.some((c) => c.seg === highlight))) : -1;
  const sheet = sheetOfHighlight >= 0 ? sheetOfHighlight : picked;
  useEffect(() => {
    if (!highlight) return;
    requestAnimationFrame(() =>
      [left, right].forEach((r) => r.current?.querySelector(`[data-seg="${CSS.escape(highlight)}"]`)?.scrollIntoView({ block: "center", inline: "center" })),
    );
  }, [highlight, sheet]);
  if (error) return <p className="text-xs text-del-fg">Couldn&apos;t load the sheets: {error}</p>;
  if (!grid) return <p className="text-xs text-muted-foreground">Loading the sheets…</p>;
  const follow = (fromLeft: boolean) => {
    const [from, to] = fromLeft ? [left.current, right.current] : [right.current, left.current];
    if (!sync || echo.current) {
      echo.current = false;
      return;
    }
    if (from && to) {
      echo.current = true;
      to.scrollTop = from.scrollTop;
      to.scrollLeft = from.scrollLeft;
    }
  };
  const current = grid.sheets[sheet];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex items-center gap-1 text-xs">
        {grid.sheets.map((s, i) => (
          <button
            key={s.name}
            onClick={() => setSheet(i)}
            className={`rounded-full px-3 py-1 transition-colors ${i === sheet ? "bg-foreground font-medium text-background" : "bg-muted text-muted-foreground hover:text-foreground"}`}
          >
            {s.name}
          </button>
        ))}
        {grid.charts > 0 && <span className="ml-auto self-center text-muted-foreground">{grid.charts} chart(s) in the file (not shown here)</span>}
      </div>
      {current && (
        <div className="flex min-h-0 flex-1 gap-3">
          <Side label="Original">
            <SheetPane sheet={current} segments={bySeg} side="source" highlight={highlight} scrollRef={left} onScroll={() => follow(true)} />
          </Side>
          <Side label="Translation">
            <SheetPane sheet={current} segments={bySeg} side="target" highlight={highlight} scrollRef={right} onScroll={() => follow(false)} onPick={onPick} />
          </Side>
        </div>
      )}
    </div>
  );
}

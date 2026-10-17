"use client";

import type { Segment, SheetGrid } from "@/lib/types";

/** Text as a cell shows it: the segment's markdown markers taken out. */
export const cellText = (md: string) =>
  md
    .replace(/\[\^\d+\]/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/(\*\*\*|\*\*|\*)(?=\S)(.+?)(?<=\S)\1/g, "$2")
    .replace(/\\([\\*_[\]])/g, "$1");

/** The rows, top to bottom (wrapped text can make a row taller on one side). */
export const rowAnchors = (pane: HTMLElement) =>
  Array.from(pane.querySelectorAll<HTMLElement>("tr[data-row]"), (r) => [r.dataset.row ?? "", r] as const);

const col = (letters: string) => [...letters].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0);
function parseRange(range: string): [number, number, number, number] | null {
  const m = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(range);
  return m ? [Number(m[2]), col(m[1]), Number(m[4]), col(m[3])] : null;
}

/** One sheet as a grid: the original's values, with text cells shown from the segments (source or translation). */
export function SheetPane({
  sheet,
  segments,
  side,
  highlight,
  onPick,
  scrollRef,
}: {
  sheet: SheetGrid["sheets"][number];
  segments: Map<string, Segment>;
  side: "source" | "target";
  highlight: string | null;
  onPick?: (segId: string) => void;
  scrollRef?: React.Ref<HTMLDivElement>;
}) {
  const spans = new Map<string, [number, number]>();
  const covered = new Set<string>();
  for (const range of sheet.merges) {
    const r = parseRange(range);
    if (!r) continue;
    const [r1, c1, r2, c2] = r;
    spans.set(`${r1}:${c1}`, [r2 - r1 + 1, c2 - c1 + 1]);
    for (let i = r1; i <= r2; i++) for (let j = c1; j <= c2; j++) if (i !== r1 || j !== c1) covered.add(`${i}:${j}`);
  }
  return (
    <div ref={scrollRef} className="scroll-thin h-full overflow-auto rounded-lg border border-border bg-white text-[12px] text-[#1f1d1a]">
      {/* the file's column widths on both sides (a fixed layout needs the table's width, or content sizes the columns) */}
      <table className="border-collapse" style={{ tableLayout: "fixed", width: 34 + sheet.widths.reduce((a, w) => a + w, 0) }}>
        <colgroup>
          <col style={{ width: 34 }} />
          {sheet.widths.map((w, i) => (
            <col key={i} style={{ width: w }} />
          ))}
        </colgroup>
        <tbody>
          {sheet.rows.map((row, r) => (
            <tr key={r} data-row={r + 1} style={sheet.heights[String(r + 1)] ? { height: sheet.heights[String(r + 1)] } : undefined}>
              <td className="sticky left-0 border border-[#d9d9d9] bg-[#f3f3f3] px-1 text-right text-[10px] text-[#777]">{r + 1}</td>
              {row.map((cell, c) => {
                if (covered.has(`${r + 1}:${c + 1}`)) return null;
                const span = spans.get(`${r + 1}:${c + 1}`);
                const seg = cell.seg ? segments.get(cell.seg) : undefined;
                const text = seg ? cellText(side === "source" ? seg.source : (seg.target ?? seg.source)) : cell.v;
                const pending = !!seg && side === "target" && !seg.target;
                return (
                  <td
                    key={c}
                    rowSpan={span?.[0]}
                    colSpan={span?.[1]}
                    data-seg={cell.seg}
                    onClick={() => cell.seg && onPick?.(cell.seg)}
                    className={`border border-[#d9d9d9] px-1 py-0.5 align-top ${cell.wrap ? "whitespace-pre-wrap" : "truncate whitespace-nowrap"} ${
                      cell.seg ? "cursor-pointer hover:outline hover:outline-1 hover:outline-[#4f46e5]" : ""
                    } ${highlight && cell.seg === highlight ? "office-located" : ""} ${pending ? "italic opacity-50" : ""}`}
                    style={{
                      fontWeight: cell.b ? 600 : undefined,
                      fontStyle: cell.i ? "italic" : undefined,
                      color: cell.color,
                      background: cell.fill,
                      textAlign: cell.align,
                    }}
                    title={seg ? `${seg.id} · ${text}` : undefined}
                  >
                    {text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {sheet.truncated && <p className="p-2 text-[11px] text-[#777]">Only the first 300 rows and 40 columns are shown; the file has them all.</p>}
    </div>
  );
}

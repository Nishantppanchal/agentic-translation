"use client";

import type { Segment } from "@/lib/types";

type Place = NonNullable<Segment["cell"]>;
type Cell = Place & { segs: Segment[] };

/** Where each segment goes: cells by their top-left position (merged cells span), and the positions they cover. */
function layout(cells: Segment[]) {
  const origin = new Map<string, Cell>();
  const covered = new Map<string, string>(); // a position inside a merged cell → that cell's position
  let rows = 0;
  let cols = 0;
  for (const s of cells) {
    const c = s.cell!;
    const at = `${c.row}:${c.col}`;
    const home = covered.get(at) ?? at; // text in a merged cell's continuation belongs to the merged cell
    let cell = origin.get(home);
    if (!cell) {
      cell = { ...c, rows: c.rows || 1, cols: c.cols || 1, segs: [] };
      origin.set(home, cell);
      for (let r = c.row; r < c.row + cell.rows; r++)
        for (let k = c.col; k < c.col + cell.cols; k++) if (r !== c.row || k !== c.col) covered.set(`${r}:${k}`, home);
      rows = Math.max(rows, c.row + cell.rows - 1);
      cols = Math.max(cols, c.col + cell.cols - 1);
    }
    cell.segs.push(s);
  }
  return { origin, covered, rows, cols };
}

/** A Word or PowerPoint table in the reading views. The file's tables are read one paragraph per segment (so each
 * translation goes back into its own cell); here they are put back into their rows and columns, each paragraph
 * still a segment of its own (`render`). */
export function CellTable({ cells, render }: { cells: Segment[]; render: (s: Segment) => React.ReactNode }) {
  const { origin, covered, rows, cols } = layout(cells);
  return (
    <div className="scroll-thin my-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <tbody>
          {Array.from({ length: rows }, (_, r) => (
            <tr key={r}>
              {Array.from({ length: cols }, (_, k) => {
                const at = `${r + 1}:${k + 1}`;
                if (covered.has(at)) return null;
                const cell = origin.get(at);
                return (
                  <td key={k} rowSpan={cell?.rows} colSpan={cell?.cols} className="border border-border p-0.5 align-top">
                    {cell?.segs.map(render)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { stripCodes } from "@/lib/codes";
import type { OfficeLayout, Segment, SheetData, SlideParagraph, SlideShape } from "@/lib/types";

type Mode = "translation" | "original";
type Texts = (segId: string | null | undefined, fallback: string, mode: Mode) => string;
type Formulas = (formula: string, mode: Mode) => string;

const LITERAL = /"((?:[^"]|"")*)"/g;

/** A formula as the translated workbook has it: text it compares against follows that text's translation
 * (the export does the same, so COUNTIF(F:F,"未整改") still counts the right cells). */
function translateFormula(formula: string, translations: Map<string, string>): string {
  return formula.replace(LITERAL, (whole, lit: string) => {
    const m = lit.replace(/""/g, '"').match(/^(<>|>=|<=|=|<|>)?([\s\S]*)$/);
    const next = m && translations.get(m[2].trim().toLowerCase());
    return next === undefined || next === null ? whole : `"${((m?.[1] ?? "") + next).replace(/"/g, '""')}"`;
  });
}

const columnName = (n: number) => {
  let s = "";
  for (; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
};

function Toggle<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="flex overflow-hidden rounded-md border border-border text-xs">
      {options.map(([v, label]) => (
        <button key={v} onClick={() => onChange(v)} className={`px-2 py-1 ${value === v ? "bg-fg text-bg" : "text-muted hover:text-fg"}`}>
          {label}
        </button>
      ))}
    </div>
  );
}

/** Excel: each sheet as a grid — translated text in every cell that uses it; numbers, dates and formula results as in the file. */
function SheetView({ sheets, text, formula, onOpen }: { sheets: SheetData[]; text: Texts; formula: Formulas; onOpen: (id: string) => void }) {
  const [index, setIndex] = useState(0);
  const [mode, setMode] = useState<Mode>("translation");
  const sheet = sheets[Math.min(index, sheets.length - 1)];
  const { grid, covered, spans } = useMemo(() => {
    const grid = new Map(sheet.cells.map((c) => [`${c.r}:${c.c}`, c]));
    const covered = new Set<string>();
    const spans = new Map<string, { rows: number; cols: number }>();
    for (const [r1, c1, r2, c2] of sheet.merged) {
      spans.set(`${r1}:${c1}`, { rows: r2 - r1 + 1, cols: c2 - c1 + 1 });
      for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) if (r !== r1 || c !== c1) covered.add(`${r}:${c}`);
    }
    return { grid, covered, spans };
  }, [sheet]);
  const cols = Array.from({ length: sheet.cols }, (_, i) => i + 1);
  const rows = Array.from({ length: sheet.rows }, (_, i) => i + 1);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {sheets.map((s, i) => (
            <button
              key={s.name}
              onClick={() => setIndex(i)}
              className={`rounded-md border px-2.5 py-1 text-xs ${i === index ? "border-accent bg-accent-soft text-accent" : "border-border text-muted hover:text-fg"}`}
            >
              {s.name}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[11px] text-muted">Click a text cell to open its segment</span>
        <Toggle value={mode} options={[["translation", "Translation"], ["original", "Original"]]} onChange={setMode} />
      </div>
      <div className="scroll-thin overflow-auto rounded-md border border-border">
        <table className="border-collapse text-[12px]" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: 40 }} />
            {cols.map((c) => (
              <col key={c} style={{ width: sheet.widths[String(c)] ?? 90 }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th className="sticky top-0 left-0 z-20 border border-border bg-sidebar" />
              {cols.map((c) => (
                <th key={c} className="sticky top-0 z-10 border border-border bg-sidebar px-1 py-0.5 text-center font-normal text-muted">
                  {columnName(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r}>
                <th className="sticky left-0 z-10 border border-border bg-sidebar px-1 text-center font-normal text-muted">{r}</th>
                {cols.map((c) => {
                  const key = `${r}:${c}`;
                  if (covered.has(key)) return null;
                  const cell = grid.get(key);
                  const span = spans.get(key);
                  const shown = cell ? (cell.kind === "text" ? text(cell.seg, cell.value, mode) : cell.value) : "";
                  const other = cell?.kind === "text" && cell.seg ? text(cell.seg, cell.value, mode === "translation" ? "original" : "translation") : "";
                  const align = cell?.align ?? (cell && cell.kind !== "text" ? "right" : "left");
                  return (
                    <td
                      key={c}
                      colSpan={span?.cols}
                      rowSpan={span?.rows}
                      onClick={() => cell?.seg && onOpen(cell.seg)}
                      title={[other, cell?.formula && formula(cell.formula, mode)].filter(Boolean).join("\n") || undefined}
                      className={`border border-border/70 px-1.5 py-0.5 align-top ${cell?.wrap ? "break-words whitespace-normal" : "overflow-hidden text-ellipsis whitespace-nowrap"} ${
                        cell?.seg ? "cursor-pointer hover:bg-accent-soft/60" : ""
                      }`}
                      style={{ background: cell?.fill, fontWeight: cell?.bold ? 600 : undefined, textAlign: align }}
                    >
                      {cell?.formula && <span className="mr-1 font-mono text-[9px] text-accent italic">fx</span>}
                      {shown}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sheet.truncated && <p className="mt-1.5 text-xs text-muted">Only the first {sheet.rows} rows and {sheet.cols} columns are shown; the file has them all.</p>}
    </div>
  );
}

/** A text box that shrinks its text to fit, like PowerPoint's shrink-on-overflow. */
function TextBox({ shape, paragraphs, slideWidthPt, text, mode, onOpen }: {
  shape: SlideShape;
  paragraphs: SlideParagraph[];
  slideWidthPt: number;
  text: Texts;
  mode: Mode;
  onOpen: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState(1);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && el.scrollHeight > el.clientHeight + 1 && fit > 0.45) setFit((f) => Math.max(0.45, f * 0.9));
  }, [fit]);
  const title = shape.placeholder === "title" || shape.placeholder === "center_title";
  return (
    <div ref={ref} className={`absolute flex flex-col overflow-hidden px-[1.2%] ${title ? "justify-center" : ""}`}
      style={{ left: `${shape.x * 100}%`, top: `${shape.y * 100}%`, width: `${shape.w * 100}%`, height: `${shape.h * 100}%`, background: shape.fill ?? undefined }}>
      {paragraphs.map((p, i) => {
        const t = text(p.seg, p.text, mode);
        if (!t.trim()) return null;
        return (
          <p
            key={i}
            onClick={() => p.seg && onOpen(p.seg)}
            className={p.seg ? "cursor-pointer rounded-sm hover:bg-accent-soft/60" : ""}
            style={{
              fontSize: `${(((p.size ?? 18) * fit) / slideWidthPt) * 100}cqw`,
              fontWeight: p.bold || title ? 600 : 400,
              textAlign: p.align ?? (shape.placeholder === "center_title" || shape.placeholder === "subtitle" ? "center" : "left"),
              marginLeft: shape.bullets ? `${p.level * 4}%` : undefined,
              lineHeight: 1.2,
              marginBottom: "0.4em",
            }}
          >
            {shape.bullets && <span className="mr-[0.5em]">•</span>}
            {t}
          </p>
        );
      })}
    </div>
  );
}

function Slide({ slide, widthPt, heightPt, text, mode, onOpen }: {
  slide: { number: number; shapes: SlideShape[] };
  widthPt: number;
  heightPt: number;
  text: Texts;
  mode: Mode;
  onOpen: (id: string) => void;
}) {
  return (
    <div
      className="relative w-full overflow-hidden rounded-md border border-border bg-white text-[#111] shadow-sm"
      style={{ aspectRatio: `${widthPt} / ${heightPt}`, containerType: "inline-size" }}
    >
      {slide.shapes.map((sh, i) =>
        sh.kind === "picture" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={i} src={sh.image} alt="" className="absolute object-contain"
            style={{ left: `${sh.x * 100}%`, top: `${sh.y * 100}%`, width: `${sh.w * 100}%`, height: `${sh.h * 100}%` }} />
        ) : sh.kind === "table" ? (
          <table key={i} className="absolute border-collapse" style={{ left: `${sh.x * 100}%`, top: `${sh.y * 100}%`, width: `${sh.w * 100}%` }}>
            <tbody>
              {sh.rows?.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c} className="border border-[#999] px-[0.5%] align-top" style={{ fontSize: `${(14 / widthPt) * 100}cqw` }}>
                      {cell.map((p, k) => (
                        <div key={k} onClick={() => p.seg && onOpen(p.seg)} className={p.seg ? "cursor-pointer hover:bg-accent-soft/60" : ""}>
                          {text(p.seg, p.text, mode)}
                        </div>
                      ))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <TextBox key={`${i}-${mode}`} shape={sh} paragraphs={sh.paragraphs ?? []} slideWidthPt={widthPt} text={text} mode={mode} onOpen={onOpen} />
        ),
      )}
    </div>
  );
}

/** PowerPoint: each slide with its text boxes where they sit, speaker notes underneath. */
function SlideView({ layout, text, onOpen }: { layout: Extract<OfficeLayout, { format: "pptx" }>; text: Texts; onOpen: (id: string) => void }) {
  const [mode, setMode] = useState<Mode | "both">("translation");
  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-[11px] text-muted">Click a text to open its segment</span>
        <div className="ml-auto">
          <Toggle value={mode} options={[["translation", "Translation"], ["original", "Original"], ["both", "Side by side"]]} onChange={setMode} />
        </div>
      </div>
      <div className="space-y-6">
        {layout.slides.map((slide) => (
          <section key={slide.number}>
            <div className="mb-1 text-[10px] tracking-wider text-muted uppercase">Slide {slide.number}</div>
            {mode === "both" ? (
              <div className="grid grid-cols-2 gap-3">
                <Slide slide={slide} widthPt={layout.width_pt} heightPt={layout.height_pt} text={text} mode="original" onOpen={onOpen} />
                <Slide slide={slide} widthPt={layout.width_pt} heightPt={layout.height_pt} text={text} mode="translation" onOpen={onOpen} />
              </div>
            ) : (
              <div className="max-w-3xl">
                <Slide slide={slide} widthPt={layout.width_pt} heightPt={layout.height_pt} text={text} mode={mode} onOpen={onOpen} />
              </div>
            )}
            {slide.notes.some((p) => p.text.trim()) && (
              <div className={`mt-2 rounded-md bg-sidebar px-3 py-2 text-xs ${mode === "both" ? "" : "max-w-3xl"}`}>
                <span className="mr-1.5 text-[10px] tracking-wide text-muted uppercase">Notes</span>
                {slide.notes.map((p, i) => (
                  <span key={i} onClick={() => p.seg && onOpen(p.seg)} className={p.seg ? "cursor-pointer hover:text-accent" : ""}>
                    {text(p.seg, p.text, mode === "original" ? "original" : "translation")}{" "}
                  </span>
                ))}
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}

/** The Document tab for Excel and PowerPoint files: the file as it is arranged, in the original or translated. */
export function OfficeLayoutView({ sessionId, segments, onOpen }: { sessionId: string; segments: Segment[]; onOpen: (id: string) => void }) {
  const [layout, setLayout] = useState<OfficeLayout | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .officeLayout(sessionId)
      .then((l) => !cancelled && setLayout(l))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);
  const byId = useMemo(() => new Map(segments.map((s) => [s.id, s])), [segments]);
  const translations = useMemo(() => {
    const out = new Map<string, string>();
    for (const s of segments) {
      if (s.target && s.target !== s.source) out.set(stripCodes(s.source).trim().toLowerCase(), stripCodes(s.target).trim());
    }
    return out;
  }, [segments]);
  const formula: Formulas = (f, mode) => (mode === "original" ? f : translateFormula(f, translations));
  const text: Texts = (segId, fallback, mode) => {
    const seg = segId ? byId.get(segId) : undefined;
    if (!seg) return fallback;
    return stripCodes(mode === "original" ? seg.source : (seg.target ?? seg.source));
  };

  if (error) return <p className="text-sm text-del-fg">{error}</p>;
  if (!layout)
    return (
      <p className="flex items-center gap-2 text-sm text-muted">
        <Loader2 size={14} className="animate-spin" /> Reading the file’s layout…
      </p>
    );
  return layout.format === "xlsx" ? (
    <SheetView sheets={layout.sheets} text={text} formula={formula} onOpen={onOpen} />
  ) : (
    <SlideView layout={layout} text={text} onOpen={onOpen} />
  );
}

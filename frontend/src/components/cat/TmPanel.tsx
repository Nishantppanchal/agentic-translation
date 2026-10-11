"use client";

import { diffChars, diffWordsWithSpace } from "diff";
import { Ban, Database } from "lucide-react";
import { useMemo } from "react";
import { findTerms, noSpaceScript } from "@/lib/terms";
import type { Term, TmMatch } from "@/lib/types";

/** Source text with project terms underlined; hovering one shows its entry. */
export function TermText({ text, terms, onHover }: { text: string; terms: Term[]; onHover: (t: Term | null, el?: HTMLElement) => void }) {
  const hits = useMemo(() => findTerms(text, terms), [text, terms]);
  if (!hits.length) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  let pos = 0;
  hits.forEach((h, i) => {
    if (h.start > pos) parts.push(text.slice(pos, h.start));
    const forbidden = h.term.forbidden.length > 0;
    parts.push(
      <span
        key={i}
        onMouseEnter={(e) => onHover(h.term, e.currentTarget)}
        onMouseLeave={() => onHover(null)}
        className={`cursor-help rounded-sm underline decoration-2 underline-offset-2 ${
          h.term.target ? "decoration-accent/60" : "decoration-muted/60 decoration-dotted"
        } ${forbidden ? "bg-accent-soft/60" : ""}`}
      >
        {text.slice(h.start, h.end)}
      </span>,
    );
    pos = h.end;
  });
  if (pos < text.length) parts.push(text.slice(pos));
  return <>{parts}</>;
}

/** The hover card for a term (rendered once, fixed-positioned outside the virtualised rows). */
export function TermCard({ term, anchor }: { term: Term; anchor: DOMRect }) {
  const top = anchor.bottom + 6;
  const left = Math.min(anchor.left, window.innerWidth - 300);
  return (
    <div style={{ top, left }} className="pointer-events-none fixed z-50 w-72 rounded-lg border border-border bg-panel p-3 text-xs shadow-lg">
      <div className="text-sm">
        <b>{term.source}</b>
        {term.target && (
          <>
            {" "}
            → <b className="text-accent">{term.target}</b>
          </>
        )}
      </div>
      {term.note && <p className="mt-1 text-muted">{term.note}</p>}
      {term.forbidden.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1 text-del-fg">
          <Ban size={11} /> Never:
          {term.forbidden.map((f) => (
            <span key={f} className="rounded bg-del px-1">
              {f}
            </span>
          ))}
        </div>
      )}
      <div className="mt-1.5 text-[10px] tracking-wide text-muted uppercase">Project termbase · {term.status}</div>
    </div>
  );
}

function SourceDiff({ from, to }: { from: string; to: string }) {
  // What differs between the stored source and this segment's source (characters for CJK, words otherwise).
  const parts = noSpaceScript.test(to) ? diffChars(from, to) : diffWordsWithSpace(from, to);
  return (
    <>
      {parts.map((p, i) =>
        p.added ? (
          <ins key={i} className="rounded-sm bg-ins text-ins-fg no-underline">
            {p.value}
          </ins>
        ) : p.removed ? (
          <del key={i} className="rounded-sm bg-del text-del-fg">
            {p.value}
          </del>
        ) : (
          <span key={i}>{p.value}</span>
        ),
      )}
    </>
  );
}

const scoreStyle = (score: number) =>
  score >= 100 ? "bg-ins text-ins-fg" : score >= 85 ? "bg-accent-soft text-accent" : "bg-warn text-warn-fg";

/** TM matches for the active segment. Alt+1–3 (or Ctrl+1–3) inserts one into the target. */
export function TmPanel({
  source,
  matches,
  loading,
  editable,
  onInsert,
}: {
  source: string;
  matches: TmMatch[];
  loading: boolean;
  editable: boolean;
  onInsert: (target: string) => void;
}) {
  return (
    <div className="col-span-4 -mt-1 mb-1 ml-[76px] rounded-md border border-border bg-bg px-3 py-2 text-xs">
      <div className="mb-1 flex items-center gap-1.5 font-medium text-muted">
        <Database size={12} /> Translation memory
        {editable && matches.length > 0 && <span className="font-normal">· Alt+1–{Math.min(3, matches.length)} to insert</span>}
      </div>
      {loading && matches.length === 0 && <div className="text-muted">Looking up…</div>}
      {!loading && matches.length === 0 && <div className="text-muted">No matches of 75% or more.</div>}
      <div className="space-y-1.5">
        {matches.slice(0, 3).map((m, i) => (
          <button
            key={m.id}
            disabled={!editable}
            onMouseDown={(e) => e.preventDefault()} // keep focus (and the draft) in the target box
            onClick={() => onInsert(m.target)}
            className="grid w-full grid-cols-[22px_42px_1fr_1fr] items-start gap-2 rounded px-1 py-1 text-left hover:bg-accent-soft/50 disabled:hover:bg-transparent"
            title={m.origin ? `From ${m.origin}` : undefined}
          >
            <span className="font-mono text-muted">{i + 1}</span>
            <span className={`rounded px-1 text-center font-medium ${scoreStyle(m.score)}`}>{m.score}%</span>
            <span className="text-muted">{m.score >= 100 ? m.source : <SourceDiff from={m.source} to={source} />}</span>
            <span>{m.target}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

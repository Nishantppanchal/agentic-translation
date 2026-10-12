"use client";

import { BookOpen, Languages } from "lucide-react";
import type { Answer, Question, Segment } from "@/lib/types";

/** What the person picked for a question: one of the options, their own English term, or an explanation. */
export type Choice = { kind: "option"; index: number } | { kind: "term"; text: string } | { kind: "note"; text: string };

export const recommendedChoice = (q: Question): Choice =>
  q.options?.length ? { kind: "option", index: q.recommended ?? 0 } : { kind: "note", text: "" };

export function answerFor(q: Question, c: Choice): Answer | null {
  if (c.kind === "option") {
    const o = q.options?.[c.index];
    return o ? { target: o.target, note: "", recommended: c.index === (q.recommended ?? 0) } : null;
  }
  const text = c.text.trim();
  if (!text) return null;
  return c.kind === "term" ? { target: text } : { note: text };
}

export const isRecommended = (q: Question, c: Choice) => c.kind === "option" && c.index === (q.recommended ?? 0);

const radio = "mt-0.5 accent-[var(--color-accent)]";

/**
 * One term to decide, explained for someone who doesn't read the source language: what it means, the
 * sentence it's in (source and English), and the English options with the agents' recommendation.
 */
export function TermChoice({
  question: q,
  segments,
  choice,
  onChange,
  onJump,
  disabled,
}: {
  question: Question;
  segments: Map<string, Segment>;
  choice: Choice;
  onChange: (c: Choice) => void;
  onJump: (segmentId: string) => void;
  disabled?: boolean;
}) {
  const context = q.segment_ids.map((id) => segments.get(id)).find(Boolean);
  const english = q.gist || context?.target || "";
  const name = `q-${q.id}`;
  return (
    <div className="rounded-lg border border-border bg-panel p-3">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-base font-semibold">{q.term}</span>
        {q.meaning && <span className="text-sm text-fg/80">— {q.meaning}</span>}
      </div>
      {q.reason && <div className="mt-0.5 text-xs text-muted">Why it matters: {q.reason}</div>}
      {!!q.dictionary?.length && (
        <div className="mt-2 rounded-md border border-border bg-bg px-2 py-1.5 text-xs">
          {q.dictionary.map((d, i) => (
            <div key={i} className="flex gap-1.5 py-0.5">
              <BookOpen size={12} className="mt-0.5 shrink-0 text-muted" />
              <span className="min-w-0">
                <span className="font-medium">{d.translation}</span>
                {d.term && d.term.toLowerCase() !== q.term.toLowerCase() && <span className="text-muted"> ({d.term})</span>}
                {d.domain && <span className="text-muted"> · {d.domain}</span>}
                {d.definition && <span className="block text-fg/80">{d.definition}</span>}
                <span className="text-muted">
                  {d.url ? (
                    <a href={d.url} target="_blank" rel="noreferrer" className="underline">
                      {d.source || "Dictionary"}
                    </a>
                  ) : (
                    d.source || "Dictionary"
                  )}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}
      {context && (
        <button
          onClick={() => onJump(context.id)}
          className="mt-2 block w-full rounded-md bg-sidebar/70 px-2 py-1.5 text-left text-xs hover:bg-sidebar"
          title="Show in document"
        >
          <span className="line-clamp-2 text-muted">
            <span className="font-mono">{context.id}</span> {context.source}
          </span>
          {english && (
            <span className="mt-0.5 line-clamp-2 flex gap-1 text-fg/80">
              <Languages size={12} className="mt-0.5 shrink-0 text-muted" /> {english}
            </span>
          )}
        </button>
      )}
      <fieldset disabled={disabled} className="mt-2 space-y-1 text-sm">
        {(q.options ?? []).map((o, i) => (
          <label key={o.target} className="flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 hover:bg-accent-soft/40">
            <input
              type="radio"
              name={name}
              className={radio}
              checked={choice.kind === "option" && choice.index === i}
              onChange={() => onChange({ kind: "option", index: i })}
            />
            <span className="min-w-0 flex-1">
              <span className="font-medium">{o.target}</span>
              {i === (q.recommended ?? 0) && (
                <span className="ml-1.5 rounded bg-accent-soft px-1 py-px text-[10px] font-medium text-accent uppercase">recommended</span>
              )}
              {o.note && <span className="block text-xs text-muted">{o.note}</span>}
            </span>
          </label>
        ))}
        {(["term", "note"] as const).map((kind) => (
          <label key={kind} className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 hover:bg-accent-soft/40">
            <input
              type="radio"
              name={name}
              className={radio}
              checked={choice.kind === kind}
              onChange={() => onChange({ kind, text: choice.kind === kind ? choice.text : "" })}
            />
            <input
              value={choice.kind === kind ? choice.text : ""}
              onFocus={() => choice.kind !== kind && onChange({ kind, text: "" })}
              onChange={(e) => onChange({ kind, text: e.target.value })}
              placeholder={kind === "term" ? "Another English term…" : "Or explain what it means here…"}
              className="min-w-0 flex-1 rounded-md border border-border bg-bg px-2 py-1 text-sm outline-none focus:border-accent"
            />
          </label>
        ))}
      </fieldset>
    </div>
  );
}

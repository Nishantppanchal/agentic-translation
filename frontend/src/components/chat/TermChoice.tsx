"use client";

import { BookOpen, Languages } from "lucide-react";
import { cn } from "cn";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import type { Answer, Question, Segment } from "@/lib/types";
import { Markdown } from "../document/Markdown";

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

const valueOf = (c: Choice) => (c.kind === "option" ? `option-${c.index}` : c.kind);
const same = (a?: string, b?: string) => !!a && !!b && a.trim().toLowerCase() === b.trim().toLowerCase();

/**
 * One term to decide, explained for someone who doesn't read the source language: what it means, the
 * sentence it's in (source and English, the term marked in both), and the English options with the agents'
 * recommendation and what the dictionary says.
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
  const recommended = q.options?.[q.recommended ?? 0]?.target ?? q.guess;
  const fromDictionary = (target: string) => (q.dictionary ?? []).some((d) => same(d.translation, target));

  return (
    <div className="rounded-lg border border-border bg-card p-3 shadow-xs">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-base font-semibold">{q.term}</span>
        {q.meaning && <span className="text-sm text-foreground/80">— {q.meaning}</span>}
      </div>
      {q.reason && <div className="mt-0.5 text-xs text-muted-foreground">Why it matters: {q.reason}</div>}

      {context && (
        <button
          type="button"
          onClick={() => onJump(context.id)}
          className="mt-2 block w-full rounded-md bg-muted/70 px-2.5 py-2 text-left text-xs transition-colors hover:bg-muted"
          aria-label={`Show ${context.id} in the document`}
        >
          <span className="line-clamp-2 text-muted-foreground">
            <span className="mr-1 font-mono text-[10px]">{context.id}</span>
            <Markdown inline text={context.source} highlight={[q.term]} />
          </span>
          {english && (
            <span className="mt-1 flex gap-1.5 text-foreground/85">
              <Languages size={12} className="mt-0.5 shrink-0 text-muted-foreground" />
              <span className="line-clamp-2">
                <Markdown inline text={english} highlight={recommended ? [recommended] : []} />
              </span>
            </span>
          )}
        </button>
      )}

      {!!q.dictionary?.length && (
        <div className="mt-2 space-y-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs">
          {q.dictionary.map((d, i) => (
            <div key={i} className="flex gap-1.5">
              <BookOpen size={12} className="mt-0.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0">
                <span className="font-medium">{d.translation}</span>
                {d.term && d.term.toLowerCase() !== q.term.toLowerCase() && <span className="text-muted-foreground"> ({d.term})</span>}
                {d.domain && <span className="text-muted-foreground"> · {d.domain}</span>}
                {d.definition && <span className="block text-foreground/80">{d.definition}</span>}
                <span className="text-muted-foreground">
                  {d.url ? (
                    <a href={d.url} target="_blank" rel="noreferrer" className="underline underline-offset-2">
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

      <RadioGroup
        value={valueOf(choice)}
        onValueChange={(v) => {
          if (v.startsWith("option-")) onChange({ kind: "option", index: Number(v.slice(7)) });
          else onChange({ kind: v as "term" | "note", text: choice.kind !== "option" && choice.kind === v ? choice.text : "" });
        }}
        disabled={disabled}
        className="mt-2.5 gap-0.5"
        aria-label={`English for ${q.term}`}
      >
        {(q.options ?? []).map((o, i) => {
          const id = `q-${q.id}-o${i}`;
          return (
            <label
              key={o.target}
              htmlFor={id}
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 transition-colors hover:bg-accent",
                choice.kind === "option" && choice.index === i && "bg-primary-soft hover:bg-primary-soft",
              )}
            >
              <RadioGroupItem id={id} value={`option-${i}`} className="mt-0.5" />
              <span className="min-w-0 flex-1 text-sm">
                <span className="font-medium">{o.target}</span>
                {i === (q.recommended ?? 0) && (
                  <Badge className="ml-1.5 h-4 px-1.5 text-[10px] font-medium uppercase" variant="secondary">
                    recommended
                  </Badge>
                )}
                {fromDictionary(o.target) && (
                  <Badge variant="outline" className="ml-1 h-4 gap-0.5 px-1 text-[10px] font-normal">
                    <BookOpen className="size-2.5" /> dictionary
                  </Badge>
                )}
                {o.note && <span className="block text-xs text-muted-foreground">{o.note}</span>}
              </span>
            </label>
          );
        })}
        {(["term", "note"] as const).map((kind) => (
          <div key={kind} className="flex items-center gap-2.5 rounded-md px-2 py-1">
            <RadioGroupItem value={kind} aria-label={kind === "term" ? "Another English term" : "Explain what it means"} />
            <Input
              value={choice.kind === kind ? choice.text : ""}
              onFocus={() => choice.kind !== kind && onChange({ kind, text: "" })}
              onChange={(e) => onChange({ kind, text: e.target.value })}
              placeholder={kind === "term" ? "Another English term…" : "Or explain what it means here…"}
              disabled={disabled}
              className="h-8 min-w-0 flex-1 bg-background text-sm"
            />
          </div>
        ))}
      </RadioGroup>
    </div>
  );
}

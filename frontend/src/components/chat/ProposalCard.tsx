"use client";

import { Check, CheckCheck, FilePenLine, Loader2, X } from "lucide-react";
import { cn } from "cn";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Proposal, Segment } from "@/lib/types";
import { Markdown } from "../document/Markdown";
import { RichDiff } from "../document/RichDiff";
import { changeKey as key, type ProposalPick } from "./proposalPick";

/** The segment a change is in: its id (click to show it in the document), a label, and its source as context. */
function ChangeHead({ id, label, source, onJump }: { id: string; label?: string; source?: string; onJump: (id: string) => void }) {
  return (
    <>
      <div className="mb-1 flex items-center gap-2">
        <button type="button" onClick={() => onJump(id)} className="font-mono text-[11px] text-muted-foreground hover:text-primary">
          {id}
        </button>
        {label && (
          <Badge variant="secondary" className="h-4 px-1.5 text-[10px] font-normal uppercase">
            {label}
          </Badge>
        )}
      </div>
      {source && (
        <div className="mb-1.5 line-clamp-2 text-xs text-muted-foreground">
          <Markdown inline text={source} />
        </div>
      )}
    </>
  );
}

/** The editor's pending changes: review each change as it reads, untick what you don't want, accept or reject. */
export function ProposalCard({
  proposal,
  pick,
  segments,
  disabled,
  onAccept,
  onReject,
  onJump,
}: {
  proposal: Proposal;
  pick: ProposalPick; // shared with the segment grid
  segments: Segment[];
  disabled: boolean;
  onAccept: (changes: string[] | null, choices: Record<string, number> | null, confirm?: boolean) => Promise<void>;
  onReject: () => Promise<void>;
  onJump: (id: string) => void;
}) {
  const order = useMemo(() => new Map(segments.map((s, i) => [s.id, i])), [segments]);
  const source = useMemo(() => new Map(segments.map((s) => [s.id, s.source])), [segments]);
  const changes = useMemo(
    () => [...proposal.changes].sort((a, b) => (order.get(a.segment_id) ?? 0) - (order.get(b.segment_id) ?? 0)),
    [proposal.changes, order],
  );
  const { excluded, choices } = pick;
  const [busy, setBusy] = useState<"accept" | "confirm" | "reject" | null>(null);
  const glossary = Object.entries(proposal.glossary ?? {});
  const selectedCount = changes.filter((c) => !excluded.has(key(c))).length;
  const locked = disabled || !!busy;

  const targetChanges = changes.some((c) => c.field === "target" && !excluded.has(key(c)));
  const run = async (which: "accept" | "confirm" | "reject") => {
    setBusy(which);
    try {
      if (which === "reject") await onReject();
      else await onAccept(...pick.acceptArgs(changes), which === "confirm");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-primary/35 bg-card text-sm shadow-sm">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 border-b border-border bg-primary-soft px-3 py-2">
        <FilePenLine size={16} className="text-primary" />
        <span className="font-medium">
          Proposed changes · {changes.length} segment{changes.length === 1 ? "" : "s"}
          {glossary.length > 0 && ` · ${glossary.length} glossary`}
        </span>
        <span className="ml-auto text-xs text-muted-foreground">Nothing changes until you accept · also in the Segments tab</span>
      </div>

      <div className="scroll-thin max-h-[45vh] divide-y divide-border overflow-y-auto px-3">
        {changes.map((c) => {
          const k = key(c);
          const included = !excluded.has(k);
          return (
            <div key={k} className="flex gap-2.5 py-2.5">
              <Checkbox
                className="mt-0.5"
                checked={included}
                disabled={locked}
                onCheckedChange={(v) => pick.include(k, v === true)}
                aria-label={`Include the change to ${c.segment_id}`}
              />
              <div className={cn("min-w-0 flex-1 transition-opacity", !included && "opacity-40")}>
                {c.alternatives?.length ? (
                  <>
                    <ChangeHead id={c.segment_id} label="pick one" source={source.get(c.segment_id)} onJump={onJump} />
                    <RadioGroup
                      value={String(choices[k] ?? 0)}
                      onValueChange={(v) => pick.choose(k, Number(v))}
                      disabled={locked}
                      className="gap-1"
                      aria-label={`Alternatives for ${c.segment_id}`}
                    >
                      {c.alternatives.map((alt, i) => {
                        const id = `alt-${k}-${i}`;
                        return (
                          <label
                            key={i}
                            htmlFor={id}
                            className={cn(
                              "flex cursor-pointer items-start gap-2 rounded-md border px-2 py-1.5 transition-colors",
                              (choices[k] ?? 0) === i ? "border-primary/50 bg-primary-soft/60" : "border-border hover:bg-accent/60",
                            )}
                          >
                            <RadioGroupItem id={id} value={String(i)} className="mt-0.5" />
                            <div className="min-w-0 flex-1">
                              <RichDiff before={c.before} after={alt.text} />
                              {alt.note && <div className="mt-0.5 text-[11px] text-muted-foreground">{alt.note}</div>}
                            </div>
                          </label>
                        );
                      })}
                    </RadioGroup>
                  </>
                ) : (
                  <>
                    <ChangeHead
                      id={c.segment_id}
                      label={c.field === "source" ? "source / OCR fix" : undefined}
                      source={c.field === "target" ? source.get(c.segment_id) : undefined}
                      onJump={onJump}
                    />
                    <RichDiff before={c.before} after={c.after} />
                  </>
                )}
              </div>
            </div>
          );
        })}
        {glossary.map(([term, e]) => (
          <div key={term} className="flex items-center gap-2 py-2 text-xs">
            <Badge variant="secondary" className="h-4 px-1.5 text-[10px] font-normal uppercase">
              glossary
            </Badge>
            <span className="font-medium">{term}</span> → {e.target || e.note}
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-3 py-2">
        <Button variant="ghost" size="sm" onClick={() => run("reject")} disabled={locked} className="hover:text-del-fg">
          {busy === "reject" ? <Loader2 className="animate-spin" /> : <X />} Reject
        </Button>
        {targetChanges && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="sm" onClick={() => run("confirm")} disabled={locked}>
                {busy === "confirm" ? <Loader2 className="animate-spin" /> : <CheckCheck />} Accept &amp; confirm
              </Button>
            </TooltipTrigger>
            <TooltipContent>Accept, and confirm the new translations (they go into the project&apos;s translation memory)</TooltipContent>
          </Tooltip>
        )}
        <Button size="sm" onClick={() => run("accept")} disabled={locked || (selectedCount === 0 && glossary.length === 0)}>
          {busy === "accept" ? <Loader2 className="animate-spin" /> : <Check />}
          {excluded.size ? `Accept ${selectedCount} selected` : "Accept"}
        </Button>
      </div>
    </div>
  );
}

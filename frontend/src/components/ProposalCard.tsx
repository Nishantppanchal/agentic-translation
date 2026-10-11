"use client";

import { Check, FilePenLine, Loader2, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { Proposal, Segment } from "@/lib/types";
import { DiffText, SegmentDiff } from "./Diff";
import { changeKey as key, type ProposalPick } from "./proposalPick";

/** The editor's pending changes: review the diff, untick what you don't want, accept or reject. */
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
  onAccept: (changes: string[] | null, choices: Record<string, number> | null) => Promise<void>;
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
  const [busy, setBusy] = useState<"accept" | "reject" | null>(null);
  const glossary = Object.entries(proposal.glossary ?? {});
  const selectedCount = changes.filter((c) => !excluded.has(key(c))).length;

  const run = async (which: "accept" | "reject") => {
    setBusy(which);
    try {
      if (which === "reject") await onReject();
      else await onAccept(...pick.acceptArgs(changes));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-accent/40 bg-panel text-sm shadow-sm">
      <div className="flex items-center gap-2 border-b border-border bg-accent-soft px-3 py-2">
        <FilePenLine size={16} className="text-accent" />
        <span className="font-medium">
          Proposed changes · {changes.length} segment{changes.length === 1 ? "" : "s"}
          {glossary.length > 0 && ` · ${glossary.length} glossary`}
        </span>
        <span className="ml-auto text-xs text-muted">Also shown in the Segments tab · nothing is applied until you accept</span>
      </div>

      <div className="scroll-thin max-h-[45vh] divide-y divide-border overflow-y-auto px-3">
        {changes.map((c) => {
          const k = key(c);
          return (
            <div key={k} className="flex gap-2.5">
              <input
                type="checkbox"
                className="mt-3 accent-[var(--accent)]"
                checked={!excluded.has(k)}
                disabled={disabled || !!busy}
                onChange={(e) => pick.include(k, e.target.checked)}
              />
              <div className={`min-w-0 flex-1 ${excluded.has(k) ? "opacity-40" : ""}`}>
                {c.alternatives?.length ? (
                  <div className="py-2">
                    <div className="mb-1 flex items-center gap-2">
                      <button onClick={() => onJump(c.segment_id)} className="font-mono text-[11px] text-muted hover:text-accent">
                        {c.segment_id}
                      </button>
                      <span className="rounded bg-sidebar px-1.5 text-[10px] text-muted uppercase">pick one</span>
                    </div>
                    <div className="mb-1.5 line-clamp-2 text-xs text-muted">{source.get(c.segment_id)}</div>
                    <div className="space-y-1">
                      {c.alternatives.map((alt, i) => (
                        <label
                          key={i}
                          className={`flex cursor-pointer items-start gap-2 rounded-md border px-2 py-1.5 ${
                            (choices[k] ?? 0) === i ? "border-accent bg-accent-soft/40" : "border-border"
                          }`}
                        >
                          <input
                            type="radio"
                            name={`alt-${k}`}
                            className="mt-1 accent-[var(--accent)]"
                            checked={(choices[k] ?? 0) === i}
                            disabled={disabled || !!busy}
                            onChange={() => pick.choose(k, i)}
                          />
                          <div className="min-w-0 flex-1">
                            <DiffText before={c.before} after={alt.text} />
                            {alt.note && <div className="mt-0.5 text-[11px] text-muted">{alt.note}</div>}
                          </div>
                        </label>
                      ))}
                    </div>
                  </div>
                ) : (
                  <SegmentDiff
                    id={c.segment_id}
                    source={c.field === "target" ? source.get(c.segment_id) : undefined}
                    label={c.field === "source" ? "source / OCR fix" : undefined}
                    before={c.before}
                    after={c.after}
                    onJump={onJump}
                    compact
                  />
                )}
              </div>
            </div>
          );
        })}
        {glossary.map(([term, e]) => (
          <div key={term} className="py-2 text-xs">
            <span className="rounded bg-sidebar px-1.5 py-0.5 text-[10px] text-muted uppercase">glossary</span>{" "}
            <span className="font-medium">{term}</span> → {e.target || e.note}
          </div>
        ))}
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-border px-3 py-2">
        <button
          onClick={() => run("reject")}
          disabled={disabled || !!busy}
          className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs text-muted hover:text-del-fg disabled:opacity-40"
        >
          {busy === "reject" ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />} Reject
        </button>
        <button
          onClick={() => run("accept")}
          disabled={disabled || !!busy || (selectedCount === 0 && glossary.length === 0)}
          className="flex items-center gap-1 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          {busy === "accept" ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
          {excluded.size ? `Accept ${selectedCount} selected` : "Accept"}
        </button>
      </div>
    </div>
  );
}

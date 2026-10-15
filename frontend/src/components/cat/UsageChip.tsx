"use client";

import { useEffect, useState } from "react";
import { ModelLogo } from "@/components/settings/ModelLogo";
import { EFFORT_LABEL, useModelCatalog } from "@/components/settings/ModelChoices";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { api } from "@/lib/api";
import type { Effort, Usage } from "@/lib/types";

const fmtTokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));

/** Tokens spent on this document so far (all agents), with a per-step breakdown — by model and reasoning level —
 * on hover. */
export function UsageChip({ sessionId, refreshKey }: { sessionId: string; refreshKey: string }) {
  const [usage, setUsage] = useState<Usage | null>(null);
  const { models } = useModelCatalog();

  useEffect(() => {
    let cancelled = false;
    api
      .usage(sessionId)
      .then((u) => !cancelled && setUsage(u))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sessionId, refreshKey]);

  if (!usage || usage.total.calls === 0) return null;
  const t = usage.total;
  const model = (id: string) => models?.find((m) => m.id === id || m.model_name === id);
  return (
    <HoverCard openDelay={150} closeDelay={100}>
      <HoverCardTrigger asChild>
        <button
          className="flex h-7 items-center gap-1 rounded-full bg-muted px-2.5 text-[11px] text-muted-foreground tabular-nums transition-colors hover:text-foreground"
          aria-label={`${t.tokens} tokens used on this document`}
        >
          {fmtTokens(t.tokens)} tokens
        </button>
      </HoverCardTrigger>
      <HoverCardContent align="end" className="w-96 p-3 text-xs">
        <div className="mb-2 flex items-baseline justify-between">
          <span className="font-medium">Tokens used on this document</span>
          <span className="text-muted-foreground tabular-nums">
            {fmtTokens(t.tokens)} · {t.calls} call{t.calls === 1 ? "" : "s"}
          </span>
        </div>
        <table className="w-full">
          <tbody className="divide-y divide-border">
            {usage.rows.map((r) => {
              const m = model(r.model);
              return (
                <tr key={`${r.step}-${r.model}-${r.effort ?? ""}`} className="align-top">
                  <td className="py-1 pr-2">
                    {r.step}
                    <div className="flex items-center gap-1 truncate text-[10px] text-muted-foreground">
                      <ModelLogo model={m} size={11} />
                      {m?.label ?? r.model}
                      {r.effort ? ` · ${EFFORT_LABEL[r.effort as Effort] ?? r.effort}` : ""}
                      {r.reasoning_tokens ? ` · ${fmtTokens(r.reasoning_tokens)} thinking` : ""}
                    </div>
                  </td>
                  <td className="py-1 pr-2 text-right text-muted-foreground tabular-nums">{r.calls}×</td>
                  <td className="py-1 text-right tabular-nums" title={`${r.prompt_tokens} in · ${r.completion_tokens} out`}>
                    {fmtTokens(r.tokens)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </HoverCardContent>
    </HoverCard>
  );
}

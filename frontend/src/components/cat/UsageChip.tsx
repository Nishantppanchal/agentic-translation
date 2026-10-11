"use client";

import { Coins } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Usage } from "@/lib/types";

const fmtTokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));
const fmtUsd = (n: number) => (n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`);

/** Tokens and $ spent on this document so far (all agents), with a per-step breakdown on hover. */
export function UsageChip({ sessionId, refreshKey }: { sessionId: string; refreshKey: string }) {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [open, setOpen] = useState(false);

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
  return (
    <div className="relative" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <span className="flex items-center gap-1 rounded-full bg-sidebar px-2 py-0.5 text-[11px] text-muted">
        <Coins size={12} />
        {t.priced ? fmtUsd(t.cost_usd) : `≥ ${fmtUsd(t.cost_usd)}`} · {fmtTokens(t.tokens)} tokens
      </span>
      {open && (
        <div className="absolute top-7 right-0 z-30 w-80 rounded-lg border border-border bg-panel p-3 text-xs shadow-lg">
          <div className="mb-2 font-medium">Cost of this document</div>
          <table className="w-full">
            <tbody>
              {usage.rows.map((r) => (
                <tr key={`${r.step}-${r.model}`} className="align-top">
                  <td className="py-0.5 pr-2">
                    {r.step}
                    <div className="truncate text-[10px] text-muted">{r.model}</div>
                  </td>
                  <td className="py-0.5 pr-2 text-right text-muted">
                    {r.calls}× · {fmtTokens(r.prompt_tokens + r.completion_tokens)}
                  </td>
                  <td className="py-0.5 text-right">{r.cost_usd == null ? "?" : fmtUsd(r.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!t.priced && <p className="mt-2 text-[10px] text-muted">Some models have no known price.</p>}
        </div>
      )}
    </div>
  );
}

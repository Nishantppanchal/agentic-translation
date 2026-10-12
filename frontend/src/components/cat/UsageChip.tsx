"use client";

import { Cpu } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Usage } from "@/lib/types";

const fmtTokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));

/** Tokens spent on this document so far (all agents), with a per-step breakdown on hover. */
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
        <Cpu size={12} />
        {fmtTokens(t.tokens)} tokens
      </span>
      {open && (
        <div className="absolute top-7 right-0 z-30 w-80 rounded-lg border border-border bg-panel p-3 text-xs shadow-lg">
          <div className="mb-2 font-medium">Tokens used on this document</div>
          <table className="w-full">
            <tbody>
              {usage.rows.map((r) => (
                <tr key={`${r.step}-${r.model}`} className="align-top">
                  <td className="py-0.5 pr-2">
                    {r.step}
                    <div className="truncate text-[10px] text-muted">{r.model}</div>
                  </td>
                  <td className="py-0.5 pr-2 text-right text-muted">{r.calls}×</td>
                  <td className="py-0.5 text-right" title={`${r.prompt_tokens} in · ${r.completion_tokens} out`}>
                    {fmtTokens(r.tokens)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

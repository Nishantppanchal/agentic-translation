"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { QaIssue, QaReport, Segment } from "@/lib/types";

/** Automatic QA for a document, re-run (debounced) whenever its segments change. */
export function useQa(sessionId: string, segments: Segment[], enabled: boolean) {
  const [state, setState] = useState<{ sessionId: string; report: QaReport } | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      api
        .qa(sessionId)
        .then((report) => !cancelled && setState({ sessionId, report }))
        .catch(() => {});
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [sessionId, segments, enabled, tick]);

  const refresh = useCallback(() => setTick((n) => n + 1), []);
  const ignore = useCallback(
    async (ids: string[], ignored = true) => {
      await api.ignoreQa(sessionId, ids, ignored);
      refresh();
    },
    [sessionId, refresh],
  );

  const report = state?.sessionId === sessionId ? state.report : null;
  return { report, refresh, ignore };
}

export type QaState = ReturnType<typeof useQa>;

/** Open (not ignored) issues per segment. */
export function issuesBySegment(report: QaReport | null): Map<string, QaIssue[]> {
  const out = new Map<string, QaIssue[]>();
  for (const i of report?.issues ?? []) {
    if (i.ignored) continue;
    out.set(i.segment_id, [...(out.get(i.segment_id) ?? []), i]);
  }
  return out;
}

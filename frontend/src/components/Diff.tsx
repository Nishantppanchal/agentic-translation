"use client";

import { diffWordsWithSpace } from "diff";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Segment } from "@/lib/types";

/** Word-level inline diff. */
export function DiffText({ before, after, className = "" }: { before: string; after: string; className?: string }) {
  const parts = diffWordsWithSpace(before, after);
  return (
    <div className={`text-sm leading-relaxed whitespace-pre-wrap ${className}`}>
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
    </div>
  );
}

/** One changed segment: id, source (for context) and the diff. */
export function SegmentDiff({
  id,
  source,
  before,
  after,
  label,
  onJump,
  compact = false,
}: {
  id: string;
  source?: string;
  before: string;
  after: string;
  label?: string;
  onJump?: (id: string) => void;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "py-2" : "rounded-lg border border-border p-3"}>
      <div className="mb-1 flex items-center gap-2">
        <button onClick={() => onJump?.(id)} className="font-mono text-[11px] text-muted hover:text-accent">
          {id}
        </button>
        {label && <span className="rounded bg-sidebar px-1.5 text-[10px] text-muted uppercase">{label}</span>}
      </div>
      {source && <div className="mb-1.5 line-clamp-2 text-xs text-muted">{source}</div>}
      <DiffText before={before} after={after} />
    </div>
  );
}

const snapshotCache = new Map<string, Record<string, string>>();

async function snapshot(sessionId: string, version: number) {
  const key = `${sessionId}:${version}`;
  if (!snapshotCache.has(key)) snapshotCache.set(key, (await api.getVersion(sessionId, version)).segments);
  return snapshotCache.get(key)!;
}

/** Inline diff of a version against its predecessor (fetched on demand). */
export function VersionDiff({
  sessionId,
  version,
  segments,
  onJump,
}: {
  sessionId: string;
  version: number;
  segments: Segment[];
  onJump?: (id: string) => void;
}) {
  const [pair, setPair] = useState<{ before: Record<string, string>; after: Record<string, string> } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([snapshot(sessionId, version - 1), snapshot(sessionId, version)])
      .then(([before, after]) => !cancelled && setPair({ before, after }))
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [sessionId, version]);

  if (error) return <p className="text-xs text-del-fg">{error}</p>;
  if (!pair) return <p className="text-xs text-muted">Loading diff…</p>;
  const changed = segments.filter((s) => (pair.before[s.id] ?? "") !== (pair.after[s.id] ?? ""));
  if (changed.length === 0) return <p className="text-xs text-muted">No text changes.</p>;
  return (
    <div className="divide-y divide-border">
      {changed.map((s) => (
        <SegmentDiff
          key={s.id}
          id={s.id}
          source={s.source}
          before={pair.before[s.id] ?? ""}
          after={pair.after[s.id] ?? ""}
          onJump={onJump}
          compact
        />
      ))}
    </div>
  );
}

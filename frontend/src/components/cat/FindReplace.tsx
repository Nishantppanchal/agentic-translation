"use client";

import { CaseSensitive, Loader2, Regex, WholeWord, X } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import type { ReplaceMatch, ReplaceOptions } from "@/lib/types";
import { DiffText } from "../document/Diff";

/**
 * Find & replace in the translations: preview every change as a diff, untick what you don't want,
 * then apply — the changes are saved as human edits in one new version. Locked segments are skipped.
 */
export function FindReplace({
  sessionId,
  editable,
  onApplied,
  onClose,
}: {
  sessionId: string;
  editable: boolean;
  onApplied: (version: number | null) => void;
  onClose: () => void;
}) {
  const [opts, setOpts] = useState<ReplaceOptions>({ find: "", replace: "", regex: false, case: false, whole_word: false, scope: "all" });
  const [preview, setPreview] = useState<{ matches: ReplaceMatch[]; locked: number; for: string } | null>(null);
  const [skip, setSkip] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify(opts);
  const stale = preview && preview.for !== key;

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.replacePreview(sessionId, opts);
      setPreview({ ...res, for: key });
      setSkip(new Set());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const ids = preview.matches.map((m) => m.segment_id).filter((id) => !skip.has(id));
      const res = await api.replaceApply(sessionId, { ...opts, ids });
      setPreview(null);
      onApplied(res.version);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (k: "case" | "whole_word" | "regex", icon: React.ReactNode, title: string) => (
    <button
      onClick={() => setOpts((o) => ({ ...o, [k]: !o[k] }))}
      className={`rounded p-1 ${opts[k] ? "bg-accent text-white" : "text-muted hover:text-fg"}`}
      title={title}
      aria-pressed={opts[k]}
    >
      {icon}
    </button>
  );
  const chosen = preview ? preview.matches.length - skip.size : 0;
  const total = preview?.matches.reduce((n, m) => n + (skip.has(m.segment_id) ? 0 : m.count), 0) ?? 0;

  return (
    <div className="mb-3 rounded-lg border border-border bg-bg p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={opts.find}
          onChange={(e) => setOpts({ ...opts, find: e.target.value })}
          onKeyDown={(e) => e.key === "Enter" && opts.find && run()}
          placeholder="Find in translations…"
          className="min-w-40 flex-1 rounded-md border border-border bg-panel px-2 py-1 text-sm outline-none focus:border-accent"
          autoFocus
        />
        <input
          value={opts.replace}
          onChange={(e) => setOpts({ ...opts, replace: e.target.value })}
          onKeyDown={(e) => e.key === "Enter" && opts.find && run()}
          placeholder={opts.regex ? "Replace with ($1 for groups)…" : "Replace with…"}
          className="min-w-40 flex-1 rounded-md border border-border bg-panel px-2 py-1 text-sm outline-none focus:border-accent"
        />
        <div className="flex items-center gap-0.5">
          {toggle("case", <CaseSensitive size={15} />, "Match case")}
          {toggle("whole_word", <WholeWord size={15} />, "Whole word")}
          {toggle("regex", <Regex size={15} />, "Regular expression")}
        </div>
        <select
          value={opts.scope}
          onChange={(e) => setOpts({ ...opts, scope: e.target.value as ReplaceOptions["scope"] })}
          className="rounded-md border border-border bg-panel px-1.5 py-1"
          title="Which segments"
        >
          <option value="all">All segments</option>
          <option value="unconfirmed">Not yet confirmed</option>
        </select>
        <button onClick={run} disabled={!opts.find || busy} className="rounded-md border border-border px-2 py-1 hover:border-accent disabled:opacity-40">
          {busy && !preview ? <Loader2 size={12} className="animate-spin" /> : "Preview"}
        </button>
        <button onClick={onClose} className="p-1 text-muted hover:text-fg" title="Close">
          <X size={14} />
        </button>
      </div>
      {error && <div className="mt-2 rounded bg-del px-2 py-1 text-del-fg">{error}</div>}
      {preview && (
        <div className={`mt-2 ${stale ? "opacity-50" : ""}`}>
          <div className="mb-1.5 flex items-center gap-2 text-muted">
            {preview.matches.length === 0
              ? "No matches."
              : `${total} replacement${total === 1 ? "" : "s"} in ${chosen} segment${chosen === 1 ? "" : "s"}`}
            {preview.locked > 0 && <span>· {preview.locked} locked segment{preview.locked === 1 ? "" : "s"} skipped</span>}
            {stale && <span className="text-warn-fg">· options changed — preview again</span>}
            {preview.matches.length > 0 && (
              <button
                onClick={apply}
                disabled={!editable || busy || !!stale || chosen === 0}
                className="ml-auto flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-white disabled:opacity-40"
                title={editable ? "Saved as your edits in a new version; changed segments go back to draft" : "Read-only while the agents are working"}
              >
                {busy && <Loader2 size={12} className="animate-spin" />}
                Replace {chosen}
              </button>
            )}
          </div>
          <div className="scroll-thin max-h-72 space-y-1 overflow-y-auto">
            {preview.matches.map((m) => (
              <label key={m.segment_id} className="flex cursor-pointer items-start gap-2 rounded px-1 py-1 hover:bg-sidebar/60">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={!skip.has(m.segment_id)}
                  onChange={() =>
                    setSkip((s) => {
                      const next = new Set(s);
                      if (next.has(m.segment_id)) next.delete(m.segment_id);
                      else next.add(m.segment_id);
                      return next;
                    })
                  }
                />
                <span className="w-10 shrink-0 pt-0.5 font-mono text-[10px] text-muted">{m.segment_id}</span>
                <DiffText before={m.before} after={m.after} className="!text-xs" />
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

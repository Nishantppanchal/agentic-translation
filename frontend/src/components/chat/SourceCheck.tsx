"use client";

import { AlertTriangle, ArrowDownUp, Check, Eye, FileSearch, Loader2, X } from "lucide-react";
import { useState } from "react";
import type { SourceFix } from "@/lib/types";
import { DiffText } from "../document/Diff";

/**
 * The source check: shown while a PDF or image waits after reading. The person compares the reading with the
 * page images and asks the chat to fix it; each page fix the chat proposes is shown here to accept or reject.
 */
export function SourceCheck({
  fixes,
  onDecide,
  onContinue,
  onAskToCheck,
  chatBusy,
}: {
  fixes: SourceFix[];
  onDecide: (page: number, accept: boolean) => Promise<void>;
  onContinue: () => Promise<void>;
  onAskToCheck: () => void; // the chat looks at the pages itself (for someone who can't read the source)
  chatBusy: boolean; // the chat is working
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key);
    try {
      await action();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="rounded-xl border border-warn-fg/30 bg-warn/40 p-4 text-sm">
      <div className="flex items-center gap-2 font-medium">
        <FileSearch size={16} className="text-warn-fg" /> Check the source before translating
      </div>
      <p className="mt-1 text-xs text-muted">
        Compare the reading with the page images in <b>Source &amp; notes → Page images &amp; OCR</b>. If something is
        wrong, describe it below — e.g. “page 1 has two columns: read the left one first”, “the stamp&apos;s text is inside
        the second paragraph”, “the table lost its last row”. I&apos;ll propose a fix for the page.
      </p>
      {fixes.length === 0 && (
        <button
          onClick={onAskToCheck}
          disabled={chatBusy}
          className="mt-2 flex items-center gap-1.5 rounded-lg border border-warn-fg/30 bg-panel px-2.5 py-1 text-xs font-medium hover:border-accent disabled:opacity-40"
          title="The chat looks at each page next to its reading and tells you what looks wrong"
        >
          <Eye size={13} /> Check the pages for me
        </button>
      )}

      {fixes.map((fix) => (
        <div key={fix.id} className="mt-3 rounded-lg border border-border bg-panel p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="text-xs">
              <span className="font-medium">Page {fix.page}</span>
              {fix.reason && <span className="text-muted"> — {fix.reason}</span>}
              {fix.origin === "reread" && <span className="ml-1 rounded bg-accent-soft px-1 text-[10px] text-accent">read again</span>}
            </div>
            <div className="flex shrink-0 gap-1.5">
              <button
                onClick={() => run(`r${fix.page}`, () => onDecide(fix.page, false))}
                disabled={!!busy}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted hover:text-fg disabled:opacity-40"
              >
                <X size={12} /> Reject
              </button>
              <button
                onClick={() => run(`a${fix.page}`, () => onDecide(fix.page, true))}
                disabled={!!busy}
                className="flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-xs font-medium text-white disabled:opacity-40"
              >
                {busy === `a${fix.page}` ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} Accept
              </button>
            </div>
          </div>
          {fix.word_changes.length > 0 && (
            <div className="mt-2 flex gap-1.5 rounded-md bg-warn/60 px-2 py-1 text-xs text-warn-fg">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <span>Words would change — compare with the page image: {fix.word_changes.join("; ")}</span>
            </div>
          )}
          {!!fix.moved?.length && (
            <div className="mt-2 flex gap-1.5 rounded-md bg-warn/60 px-2 py-1 text-xs text-warn-fg">
              <ArrowDownUp size={12} className="mt-0.5 shrink-0" />
              <span>Text moves — check the reading order against the page image: {fix.moved.join("; ")}</span>
            </div>
          )}
          {fix.word_changes.length === 0 && !fix.moved?.length && (
            <div className="mt-2 text-xs text-ins-fg">Only the structure changes: the same words, in the same order.</div>
          )}
          <DiffText before={fix.before} after={fix.after} className="mt-2 max-h-72 overflow-y-auto rounded-md bg-sidebar/60 p-2 text-xs" />
        </div>
      ))}

      <div className="mt-3 flex items-center justify-end gap-2">
        {fixes.length > 0 && (
          <span className="text-xs text-muted">
            {fixes.length} page fix{fixes.length === 1 ? "" : "es"} not decided {fixes.length === 1 ? "is" : "are"} left out if you
            continue.
          </span>
        )}
        <button
          onClick={() => run("continue", onContinue)}
          disabled={!!busy || chatBusy}
          className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          {busy === "continue" && <Loader2 size={12} className="animate-spin" />}
          Continue to translation
        </button>
      </div>
    </div>
  );
}

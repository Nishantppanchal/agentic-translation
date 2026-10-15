"use client";

import { CaseSensitive, Loader2, Regex, Replace, Search, WholeWord, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
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

  const toggle = (k: "case" | "whole_word" | "regex", icon: React.ReactNode, label: string) => (
    <Tooltip>
      <TooltipTrigger asChild>
        <Toggle size="sm" pressed={opts[k]} onPressedChange={(on) => setOpts((o) => ({ ...o, [k]: on }))} aria-label={label} className="data-[state=on]:bg-primary-soft data-[state=on]:text-primary">
          {icon}
        </Toggle>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
  const chosen = preview ? preview.matches.length - skip.size : 0;
  const total = preview?.matches.reduce((n, m) => n + (skip.has(m.segment_id) ? 0 : m.count), 0) ?? 0;

  return (
    <div className="mb-3 rounded-xl border border-border bg-background p-3 text-xs shadow-xs">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-40 flex-1">
          <Search size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={opts.find}
            onChange={(e) => setOpts({ ...opts, find: e.target.value })}
            onKeyDown={(e) => e.key === "Enter" && opts.find && run()}
            placeholder="Find in translations…"
            className="h-8 bg-card pl-8"
            autoFocus
            aria-label="Find"
          />
        </div>
        <div className="relative min-w-40 flex-1">
          <Replace size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={opts.replace}
            onChange={(e) => setOpts({ ...opts, replace: e.target.value })}
            onKeyDown={(e) => e.key === "Enter" && opts.find && run()}
            placeholder={opts.regex ? "Replace with ($1 for groups)…" : "Replace with…"}
            className="h-8 bg-card pl-8"
            aria-label="Replace with"
          />
        </div>
        <div className="flex items-center gap-0.5">
          {toggle("case", <CaseSensitive />, "Match case")}
          {toggle("whole_word", <WholeWord />, "Whole word")}
          {toggle("regex", <Regex />, "Regular expression")}
        </div>
        <Select value={opts.scope} onValueChange={(v) => setOpts({ ...opts, scope: v as ReplaceOptions["scope"] })}>
          <SelectTrigger size="sm" className="bg-card text-xs" aria-label="Which segments">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All segments</SelectItem>
            <SelectItem value="unconfirmed">Not yet confirmed</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="outline" size="sm" onClick={run} disabled={!opts.find || busy}>
          {busy && !preview && <Loader2 className="animate-spin" />} Preview
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close find and replace">
          <X />
        </Button>
      </div>
      {error && <div className="mt-2 rounded-md bg-del px-2 py-1 text-del-fg">{error}</div>}
      {preview && (
        <div className={`mt-2.5 transition-opacity ${stale ? "opacity-50" : ""}`}>
          <div className="mb-1.5 flex items-center gap-2 text-muted-foreground">
            {preview.matches.length === 0
              ? "No matches."
              : `${total} replacement${total === 1 ? "" : "s"} in ${chosen} segment${chosen === 1 ? "" : "s"}`}
            {preview.locked > 0 && <span>· {preview.locked} locked segment{preview.locked === 1 ? "" : "s"} skipped</span>}
            {stale && <span className="text-warn-fg">· options changed — preview again</span>}
            {preview.matches.length > 0 && (
              <Button
                size="sm"
                onClick={apply}
                disabled={!editable || busy || !!stale || chosen === 0}
                className="ml-auto h-7"
                title={editable ? "Saved as your edits in a new version; changed segments go back to draft" : "Read-only while the agents are working"}
              >
                {busy && <Loader2 className="animate-spin" />}
                Replace {chosen}
              </Button>
            )}
          </div>
          <div className="scroll-thin max-h-72 space-y-0.5 overflow-y-auto">
            {preview.matches.map((m) => (
              <label key={m.segment_id} className="flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 hover:bg-accent">
                <Checkbox
                  className="mt-0.5"
                  checked={!skip.has(m.segment_id)}
                  onCheckedChange={() =>
                    setSkip((s) => {
                      const next = new Set(s);
                      if (next.has(m.segment_id)) next.delete(m.segment_id);
                      else next.add(m.segment_id);
                      return next;
                    })
                  }
                  aria-label={`Replace in ${m.segment_id}`}
                />
                <span className="w-10 shrink-0 pt-0.5 font-mono text-[10px] text-muted-foreground">{m.segment_id}</span>
                <DiffText before={m.before} after={m.after} className="!text-xs" />
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

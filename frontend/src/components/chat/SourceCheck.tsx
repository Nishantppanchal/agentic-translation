"use client";

import { AlertTriangle, ArrowDownUp, Check, Eye, FileSearch, Loader2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { rise } from "@/lib/motion";
import type { SourceFix } from "@/lib/types";
import { RichDiff } from "../document/RichDiff";

/**
 * The source check: shown while a PDF or image waits after reading. The person compares the reading with the
 * page images and asks the chat to fix it; each page fix the chat proposes is shown here (as the page will read,
 * with the markdown one click away) to accept or reject.
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
    <div className="rounded-xl border border-warn-fg/25 bg-warn/40 p-4 text-sm">
      <div className="flex items-center gap-2 font-medium text-warn-fg">
        <FileSearch size={16} /> Check the source before translating
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Compare the reading with the page images in <b>Source &amp; notes → Page images &amp; OCR</b>. If something is
        wrong, describe it below — e.g. “page 1 has two columns: read the left one first”, “the stamp&apos;s text is inside
        the second paragraph”, “the table lost its last row”. I&apos;ll propose a fix for the page.
      </p>
      {fixes.length === 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="outline" size="sm" onClick={onAskToCheck} disabled={chatBusy} className="mt-2.5 bg-card">
              <Eye /> Check the pages for me
            </Button>
          </TooltipTrigger>
          <TooltipContent>The chat looks at each page next to its reading and tells you what looks wrong</TooltipContent>
        </Tooltip>
      )}

      <AnimatePresence initial={false}>
        {fixes.map((fix) => (
          <motion.div key={fix.id} {...rise} className="mt-3 rounded-lg border border-border bg-card p-3 shadow-xs">
            <div className="flex items-start justify-between gap-2">
              <div className="text-xs">
                <span className="font-medium">Page {fix.page}</span>
                {fix.reason && <span className="text-muted-foreground"> — {fix.reason}</span>}
                {(fix.origin === "reread" || fix.origin === "figure") && (
                  <Badge variant="secondary" className="ml-1.5 h-4 px-1.5 text-[10px] font-normal text-primary">
                    {fix.origin === "figure" ? "picture → text" : "read again"}
                  </Badge>
                )}
              </div>
              <div className="flex shrink-0 gap-1.5">
                <Button variant="ghost" size="xs" onClick={() => run(`r${fix.page}`, () => onDecide(fix.page, false))} disabled={!!busy}>
                  {busy === `r${fix.page}` ? <Loader2 className="animate-spin" /> : <X />} Reject
                </Button>
                <Button size="xs" onClick={() => run(`a${fix.page}`, () => onDecide(fix.page, true))} disabled={!!busy}>
                  {busy === `a${fix.page}` ? <Loader2 className="animate-spin" /> : <Check />} Accept
                </Button>
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
            <div className="scroll-thin mt-2 max-h-72 overflow-y-auto rounded-md bg-muted/60 p-2.5">
              <RichDiff before={fix.before} after={fix.after} />
            </div>
          </motion.div>
        ))}
      </AnimatePresence>

      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {fixes.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {fixes.length} page fix{fixes.length === 1 ? "" : "es"} not decided {fixes.length === 1 ? "is" : "are"} left out if you
            continue.
          </span>
        )}
        <Button size="sm" onClick={() => run("continue", onContinue)} disabled={!!busy || chatBusy}>
          {busy === "continue" && <Loader2 className="animate-spin" />}
          Continue to translation
        </Button>
      </div>
    </div>
  );
}

"use client";

import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { cn } from "cn";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fade } from "@/lib/motion";
import type { DocSettings, SessionSummary } from "@/lib/types";
import { DocSettingsChip } from "./DocSettingsChip";
import { docTitle } from "./Sidebar";
import { StatusBadge } from "./StatusBadge";

/** Above the chat and the document: the English title the analysis gave the document (else its file name), the
 * file name, its status, a one-line summary (click for both lines), its models, and the document panel toggle. */
export function TopBar({
  summary,
  settings,
  busy,
  onSettingsSaved,
  panelOpen,
  onTogglePanel,
}: {
  summary: SessionSummary;
  settings: DocSettings | undefined;
  busy: boolean;
  onSettingsSaved: () => void;
  panelOpen: boolean;
  onTogglePanel: (() => void) | null; // null: no document panel yet (nothing to show)
}) {
  const [expanded, setExpanded] = useState(false);
  const title = docTitle(summary);
  const abstract = summary.abstract?.trim();
  return (
    <header className="flex shrink-0 items-start gap-3 border-b border-border bg-background/80 px-5 py-2.5 backdrop-blur">
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <AnimatePresence mode="wait" initial={false}>
            <motion.h1 key={title} {...fade} className="truncate text-base font-semibold tracking-tight" title={title}>
              {title}
            </motion.h1>
          </AnimatePresence>
          <StatusBadge status={summary.status} />
        </div>
        <div className="flex min-w-0 items-baseline gap-2 text-xs text-muted-foreground">
          {title !== summary.filename && <span className="shrink-0 truncate font-mono text-[11px]">{summary.filename}</span>}
          {abstract && (
            <button
              onClick={() => setExpanded(!expanded)}
              aria-expanded={expanded}
              className={cn("min-w-0 text-left hover:text-foreground", expanded ? "line-clamp-none whitespace-normal" : "truncate")}
              title={expanded ? "Show less" : "Show the whole summary"}
            >
              {title !== summary.filename && <span className="mr-2 text-border">·</span>}
              {abstract}
            </button>
          )}
          {!abstract && title === summary.filename && <span className="truncate">{summary.source_lang} → English</span>}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 pt-0.5">
        {settings && <DocSettingsChip sessionId={summary.id} settings={settings} busy={busy} onSaved={onSettingsSaved} />}
        {onTogglePanel && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={onTogglePanel} aria-label={panelOpen ? "Hide the document" : "Show the document"} className="text-muted-foreground hover:text-foreground">
                {panelOpen ? <PanelRightClose /> : <PanelRightOpen />}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">{panelOpen ? "Hide the document" : "Show the document"}</TooltipContent>
          </Tooltip>
        )}
      </div>
    </header>
  );
}

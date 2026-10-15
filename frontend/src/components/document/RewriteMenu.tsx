"use client";

import { ChevronDown, CornerDownLeft, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { REWRITES } from "@/lib/rewrites";
import type { TaskKind } from "@/lib/types";

export type RunTask = (kind: TaskKind, segmentIds: string[], instruction: string, n: number) => Promise<void>;

/** "Rewrite ▾": ask the agent to rewrite these segments (more formal, simpler, shorter, alternatives, or your own
 * instruction). The result comes back as a proposal. Disabled, with the reason, while the document can't change. */
export function RewriteMenu({
  ids,
  editable,
  onRunTask,
  label = "Rewrite",
  className = "",
  onDone,
  onOpenChange,
  compact = false,
}: {
  ids: string[];
  editable: boolean;
  onRunTask: RunTask;
  label?: string;
  className?: string;
  onDone?: () => void;
  onOpenChange?: (open: boolean) => void;
  compact?: boolean; // an icon button (the grid rows)
}) {
  const [open, _setOpen] = useState(false);
  const setOpen = (o: boolean) => {
    _setOpen(o);
    onOpenChange?.(o);
  };
  const [custom, setCustom] = useState("");
  const run = async (kind: TaskKind, instruction: string, n: number) => {
    setOpen(false);
    setCustom("");
    onDone?.();
    try {
      await onRunTask(kind, ids, instruction, n);
      toast("Rewriting…", { description: "The result comes back as a proposal in the chat to accept or reject." });
    } catch (e) {
      toast.error("Couldn't start the rewrite", { description: String(e).replace(/^Error: /, "") });
    }
  };
  const trigger = compact ? (
    <button
      type="button"
      disabled={!editable || ids.length === 0}
      className={`flex h-6 min-w-6 items-center justify-center rounded-md px-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-40 data-[state=open]:bg-accent data-[state=open]:text-foreground ${className}`}
      aria-label={`${label} ${ids.join(", ")}`}
    >
      <Wand2 size={12} />
    </button>
  ) : (
    <button
      type="button"
      disabled={!editable || ids.length === 0}
      onMouseDown={(e) => e.preventDefault()} // keep a text selection (the selection toolbar) alive
      className={`flex items-center gap-1 rounded-md border border-border bg-card px-1.5 py-0.5 text-[11px] text-muted-foreground shadow-xs transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-50 data-[state=open]:text-foreground ${className}`}
      aria-label={`${label} ${ids.join(", ")}`}
    >
      <Wand2 size={12} /> {label}
      <ChevronDown size={11} className="opacity-60" />
    </button>
  );
  if (!editable) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0}>{trigger}</span>
        </TooltipTrigger>
        <TooltipContent>Rewrites open when the agents have finished</TooltipContent>
      </Tooltip>
    );
  }
  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      {compact ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>Rewrite: more formal, simpler, shorter, alternatives…</TooltipContent>
        </Tooltip>
      ) : (
        <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      )}
      <DropdownMenuContent align="end" className="w-64" onCloseAutoFocus={(e) => e.preventDefault()}>
        <DropdownMenuLabel className="flex items-center gap-1.5 text-xs font-normal text-muted-foreground">
          <Sparkles size={12} className="text-primary" /> Rewrite {ids.length === 1 ? ids[0] : `${ids.length} segments`}
        </DropdownMenuLabel>
        {REWRITES.map((r) => (
          <DropdownMenuItem key={r.label} onSelect={() => run(r.kind, r.instruction, r.n)} className="flex-col items-start gap-0">
            <span>{r.label}</span>
            <span className="text-[11px] text-muted-foreground">{r.hint}</span>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <div className="px-1.5 pt-0.5 pb-1">
          <label className="flex items-center gap-1 rounded-md border border-input bg-background px-2 focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/40">
            <input
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              // the menu's own keys (typeahead, arrows) stay out of the text box
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key === "Enter" && custom.trim()) run("retranslate", custom.trim(), 1);
              }}
              placeholder="Custom: your own instruction…"
              className="h-7 min-w-0 flex-1 bg-transparent text-xs outline-none"
              aria-label="Your own rewrite instruction"
            />
            <CornerDownLeft size={12} className="shrink-0 text-muted-foreground" aria-hidden />
          </label>
          <p className="mt-1 px-0.5 text-[10px] text-muted-foreground">Results come back as a proposal to accept or reject.</p>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

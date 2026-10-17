"use client";

import { ImageIcon, MessageSquare, MessageSquareQuote } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { rise } from "@/lib/motion";
import type { Segment } from "@/lib/types";
import { RewriteMenu, type RunTask } from "./RewriteMenu";

export const FLAG_LABEL: Record<string, string> = { untranslated: "Not translated", merged: "Check: merged text?" };
export const FLAG_HELP: Record<string, string> = {
  untranslated: "The translation is missing or still in the source language. Review couldn't fix it — edit it or ask in chat.",
  merged: "Text may have moved between this segment and a neighbour. Compare with the source.",
};

/** How the reading views show and open a segment's comments. */
export type CommentsUi = { open: string | null; toggle: (id: string) => void; thread: (seg: Segment) => React.ReactNode };

/** What the reading views can do with a segment from its hover toolbar. */
export type ShellActions = {
  onReference: (id: string) => void;
  comments: CommentsUi;
  editable: boolean; // rewrites (the document can change)
  onRunTask: RunTask;
};

const toolButton =
  "flex items-center gap-1 rounded-md border border-border bg-card px-1.5 py-0.5 text-[11px] text-muted-foreground shadow-xs transition-colors hover:text-foreground";

/** A segment in the reading views (Reading, Side by side, Source): comment markers and flags under it, a hover
 * toolbar (comment, rewrite, reference in chat), and its comment thread when open. `id="seg-…"` is what the
 * chat's jumps and the selection toolbar find. */
export function SegmentShell({
  seg,
  highlighted,
  actions,
  rewrite = true,
  compact = false,
  children,
}: {
  seg: Segment;
  highlighted: boolean;
  actions: ShellActions;
  rewrite?: boolean; // offer Rewrite ▾ (not in the source view)
  compact?: boolean; // in a table cell: no margins reaching out of it
  children: React.ReactNode;
}) {
  const { comments, onReference } = actions;
  const open = (seg.comments ?? []).filter((c) => !c.resolved).length;
  const canRewrite = rewrite && seg.translatable && !!seg.target && !seg.locked;
  return (
    <div
      id={`seg-${seg.id}`}
      data-seg={seg.id}
      className={`group relative transition-colors duration-300 ${compact ? "rounded-sm px-1.5 py-0.5" : "-mx-3 rounded-lg px-3 py-0.5"} ${
        highlighted ? "bg-primary-soft" : "hover:bg-muted/60"
      } ${open ? "shadow-[inset_2px_0_0_var(--primary)]" : ""}`}
    >
      {children}
      {(!!seg.flags?.length || (seg.pages?.length ?? 0) > 1 || open > 0) && (
        <div className="mt-0.5 mb-1 flex flex-wrap items-center gap-1.5">
          {open > 0 && (
            <button
              onClick={() => comments.toggle(seg.id)}
              className="flex items-center gap-1 rounded-full bg-primary-soft px-2 py-0.5 text-[10px] font-medium text-primary hover:bg-primary/15"
              aria-expanded={comments.open === seg.id}
            >
              <MessageSquare size={11} /> {open} comment{open === 1 ? "" : "s"}
            </button>
          )}
          {seg.flags?.map((f) => (
            <Tooltip key={f}>
              <TooltipTrigger asChild>
                <span tabIndex={0} className="rounded-full bg-warn px-2 py-0.5 text-[10px] font-medium text-warn-fg">
                  {FLAG_LABEL[f] ?? f}
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-64">{FLAG_HELP[f] ?? f}</TooltipContent>
            </Tooltip>
          ))}
          {(seg.pages?.length ?? 0) > 1 && (
            <span className="text-[10px] text-muted-foreground italic">↪ continues onto page {seg.pages!.slice(1).join(", ")}</span>
          )}
        </div>
      )}
      <AnimatePresence initial={false}>
        {comments.open === seg.id && (
          <motion.div key="thread" {...rise}>
            {comments.thread(seg)}
          </motion.div>
        )}
      </AnimatePresence>
      <div className="absolute top-1 -right-1 z-10 hidden items-center gap-1 group-focus-within:flex group-hover:flex has-[[data-state=open]]:flex">
        <button onClick={() => comments.toggle(seg.id)} className={toolButton} aria-label={`Comment on ${seg.id}`}>
          <MessageSquare size={12} /> Comment
        </button>
        {canRewrite && <RewriteMenu ids={[seg.id]} editable={actions.editable} onRunTask={actions.onRunTask} />}
        <Tooltip>
          <TooltipTrigger asChild>
            <button onClick={() => onReference(seg.id)} className={toolButton} aria-label={`Reference ${seg.id} in the chat`}>
              <MessageSquareQuote size={12} /> {seg.id}
            </button>
          </TooltipTrigger>
          <TooltipContent>Reference this passage in the chat</TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}

/** A picture from the source document, with the text found inside it shown (and translated) as a legend, where it
 * is in the file (Word / PowerPoint / Excel), and its alt text (translated) when it has one. */
export function FigureBlock({
  sessionId,
  seg,
  legend,
  alt,
  muted = false,
}: {
  sessionId: string;
  seg: Segment;
  legend: string | null;
  alt?: Segment | null; // the picture's own alt text (a segment of kind "alt")
  muted?: boolean;
}) {
  const office = !!seg.loc; // pictures from Word / PowerPoint / Excel have a place in the file
  return (
    <figure className="my-2">
      {seg.image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={api.figureUrl(sessionId, seg.image)}
          alt={(alt?.target ?? alt?.source) || `Figure ${seg.figure ?? ""}`}
          className="max-h-80 max-w-full rounded-md border border-border bg-white"
        />
      ) : (
        <div className="flex h-16 w-40 items-center justify-center rounded-md border border-dashed border-border text-muted-foreground">
          <ImageIcon size={18} />
        </div>
      )}
      {(seg.where || alt) && office && (
        <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-[11px] text-muted-foreground">
          {seg.where && <span>{seg.where}</span>}
          {alt && <AltLine seg={alt} />}
        </div>
      )}
      {legend && (
        <figcaption className={`mt-1.5 border-l-2 border-border pl-2 text-xs whitespace-pre-line ${muted ? "text-muted-foreground" : ""}`}>
          <span className="mr-1 text-[10px] tracking-wide text-muted-foreground uppercase">Text in {office ? "picture" : "figure"}</span>
          {legend}
        </figcaption>
      )}
    </figure>
  );
}

/** A picture's alt text (the author's description, translated): one muted line. */
export function AltLine({ seg, side = "target" }: { seg: Segment; side?: "source" | "target" }) {
  const text = side === "source" ? seg.source : (seg.target ?? seg.source);
  return (
    <span className="min-w-0">
      <span className="mr-1 text-[10px] tracking-wide uppercase">Alt text</span>
      <span className={side === "target" && !seg.target ? "italic" : ""}>{text}</span>
    </span>
  );
}

/** Alt-text segments sit just before their picture: the picture each belongs to, and those with no picture shown
 * (a picture too small, in an old format, or past the limit, still has a description to translate). */
export function pairAltText(segments: Segment[]) {
  const altOf = new Map<string, Segment>(); // figure id → its alt-text segment
  const paired = new Set<string>();
  segments.forEach((s, i) => {
    if (s.kind !== "alt") return;
    const next = segments[i + 1];
    if (next?.kind === "figure" && next.page === s.page) {
      altOf.set(next.id, s);
      paired.add(s.id);
    }
  });
  return { altOf, paired };
}

export function PageBreak({ page, label }: { page: number; label?: string }) {
  return (
    <div className="my-5 flex items-center gap-3 text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
      <div className="h-px flex-1 bg-border" /> {label ?? `Page ${page}`} <div className="h-px flex-1 bg-border" />
    </div>
  );
}

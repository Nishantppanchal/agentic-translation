"use client";

import { Check, Loader2, MessageSquare, RotateCcw, SendHorizontal, Trash2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { rise } from "@/lib/motion";
import type { Role, Segment, SegmentComment } from "@/lib/types";

// Unsent comments, per document and segment: closing a thread (or switching views) doesn't lose what you typed.
const drafts = new Map<string, string>();

const when = (at: number) =>
  new Date(at * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function IconAction({ label, onClick, disabled, danger = false, children }: { label: string; onClick: () => void; disabled?: boolean; danger?: boolean; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          onMouseDown={(e) => e.preventDefault()} // keep focus where it was (e.g. the target box)
          onClick={onClick}
          className={`rounded p-1 text-muted-foreground transition-colors hover:bg-accent disabled:opacity-40 ${danger ? "hover:text-del-fg" : "hover:text-foreground"}`}
          aria-label={label}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/** The comments on one segment, with Resolve / Reopen / Delete and a box to add one. Shared by the grid and the reading views. */
export function CommentThread({
  sessionId,
  segId,
  comments,
  canComment,
  role,
  onChanged,
  onClose,
  autoFocus = false,
  className = "",
}: {
  sessionId: string;
  segId: string;
  comments: SegmentComment[];
  canComment: boolean; // false while agents are working on the document
  role: Role;
  onChanged: (seg: Segment | null) => void; // null: the segment is gone (reload the document)
  onClose?: () => void;
  autoFocus?: boolean;
  className?: string;
}) {
  const key = `${sessionId}:${segId}`;
  const [text, setText] = useState(() => drafts.get(key) ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const edit = (value: string) => {
    setText(value);
    if (value) drafts.set(key, value);
    else drafts.delete(key);
  };

  const act = async (call: () => Promise<{ segment: Segment | null }>, posted = false) => {
    setBusy(true);
    setError(null);
    try {
      const { segment } = await call();
      if (posted) edit(""); // cleared only once the comment is saved
      onChanged(segment);
    } catch (e) {
      setError(String(e).replace(/^Error: /, ""));
    } finally {
      setBusy(false);
    }
  };

  const post = () => {
    if (text.trim() && !busy) act(() => api.addComment(sessionId, segId, text.trim(), role), true);
  };

  return (
    <div
      className={`rounded-lg border border-border bg-background px-3 py-2.5 text-xs shadow-xs ${className}`}
      onKeyDown={(e) => {
        if (e.key === "Escape" && onClose) {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
        <MessageSquare size={12} /> Comments on <span className="font-mono">{segId}</span>
        {onClose && (
          <button onClick={onClose} className="ml-auto rounded p-0.5 hover:bg-accent hover:text-foreground" aria-label="Close comments">
            <X size={13} />
          </button>
        )}
      </div>
      <AnimatePresence initial={false}>
        {comments.map((c) => (
          <motion.div key={c.id} {...rise} layout className={`group/comment flex items-start gap-2 py-1 ${c.resolved ? "opacity-55" : ""}`}>
            <span
              className={`mt-px shrink-0 rounded-full px-1.5 text-[10px] font-medium capitalize ${
                c.role === "reviewer" ? "bg-primary-soft text-primary" : "bg-muted text-muted-foreground"
              }`}
            >
              {c.role}
            </span>
            <span className={`min-w-0 flex-1 text-[13px] leading-snug whitespace-pre-wrap ${c.resolved ? "line-through" : ""}`}>{c.text}</span>
            <span className="shrink-0 pt-px text-[10px] text-muted-foreground" title={new Date(c.at * 1000).toLocaleString()}>
              {when(c.at)}
            </span>
            {canComment && (
              <span className="flex shrink-0 items-center opacity-60 transition-opacity group-hover/comment:opacity-100 focus-within:opacity-100">
                <IconAction label={c.resolved ? "Reopen" : "Resolve"} disabled={busy} onClick={() => act(() => api.resolveComment(sessionId, segId, c.id, !c.resolved))}>
                  {c.resolved ? <RotateCcw size={12} /> : <Check size={12} />}
                </IconAction>
                <IconAction label="Delete" danger disabled={busy} onClick={() => act(() => api.deleteComment(sessionId, segId, c.id))}>
                  <Trash2 size={12} />
                </IconAction>
              </span>
            )}
          </motion.div>
        ))}
      </AnimatePresence>
      {canComment ? (
        <div className="mt-1.5 flex items-end gap-1.5 rounded-md border border-input bg-card px-2 py-1 focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/40">
          <textarea
            value={text}
            autoFocus={autoFocus}
            rows={Math.min(4, text.split("\n").length)}
            onChange={(e) => edit(e.target.value)}
            onKeyDown={(e) => {
              // Enter posts, Shift+Enter starts a new line; never while an input method is composing (e.g. Chinese).
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                e.preventDefault();
                post();
              }
            }}
            placeholder={`Add a comment as ${role} — Enter to post, Shift+Enter for a new line`}
            className="min-w-0 flex-1 resize-none bg-transparent py-0.5 text-[13px] outline-none placeholder:text-muted-foreground"
            aria-label={`Comment on ${segId}`}
          />
          <button
            onClick={post}
            disabled={busy || !text.trim()}
            className="mb-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground transition-opacity disabled:opacity-30"
            aria-label="Post comment"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <SendHorizontal size={12} />}
          </button>
        </div>
      ) : (
        <p className="mt-1 text-muted-foreground">{comments.length ? "" : "No comments yet. "}Comments open when the agents finish.</p>
      )}
      {error && <p className="mt-1 text-del-fg">{error}</p>}
    </div>
  );
}

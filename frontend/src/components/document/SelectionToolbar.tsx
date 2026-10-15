"use client";

import { autoUpdate, flip, FloatingPortal, offset, shift, useFloating } from "@floating-ui/react";
import { Lightbulb, ListTree, MessageSquarePlus } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { pop } from "@/lib/motion";
import { RewriteMenu, type RunTask } from "./RewriteMenu";

const MAX_QUOTE = 400; // characters of the selection quoted in a chat message

type Picked = { ids: string[]; text: string; rect: DOMRect };

/** What a selection covers: the segments it touches (elements with `data-seg` inside `root`) and its text. */
function readSelection(root: HTMLElement): Picked | null {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  if (!root.contains(range.commonAncestorContainer)) return null;
  const text = sel.toString().replace(/\s+/g, " ").trim();
  if (text.length < 2) return null;
  const ids = [...root.querySelectorAll<HTMLElement>("[data-seg]")].filter((el) => range.intersectsNode(el)).map((el) => el.dataset.seg!);
  if (!ids.length) return null;
  const rect = range.getBoundingClientRect();
  return { ids, text, rect: rect.width || rect.height ? rect : (range.getClientRects()[0] ?? rect) };
}

const idsLabel = (ids: string[]) => (ids.length <= 3 ? ids.join(", ") : `${ids[0]}–${ids[ids.length - 1]}`);
const quote = (text: string) => (text.length > MAX_QUOTE ? `${text.slice(0, MAX_QUOTE)}…` : text);

function Action({
  label,
  hint,
  icon,
  disabled,
  why,
  onClick,
}: {
  label: string;
  hint: string;
  icon: React.ReactNode;
  disabled: boolean;
  why: string;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={disabled ? 0 : -1} className="inline-flex">
          <button
            type="button"
            disabled={disabled}
            onClick={onClick}
            className="flex h-7 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-foreground/90 transition-colors hover:bg-accent disabled:pointer-events-none disabled:opacity-40"
          >
            {icon}
            {label}
          </button>
        </span>
      </TooltipTrigger>
      <TooltipContent>{disabled ? why : hint}</TooltipContent>
    </Tooltip>
  );
}

/** Ask about a selection: select words in Reading or Side by side and a small toolbar offers Explain, Other options,
 * Rewrite ▾ and Ask… — the answer or proposal comes back in the chat. It hides on Esc, on scroll and when the
 * selection goes. */
export function SelectionToolbar({
  rootRef,
  enabled,
  canAsk,
  editable,
  onSend,
  onRunTask,
  onDraft,
}: {
  rootRef: React.RefObject<HTMLElement | null>;
  enabled: boolean; // the view shows segments (Reading, Side by side)
  canAsk: boolean; // the chat takes a message (nothing running)
  editable: boolean; // rewrites and alternatives (the document can change)
  onSend: (text: string) => void;
  onRunTask: RunTask;
  onDraft: (text: string) => void;
}) {
  const [picked, setPicked] = useState<Picked | null>(null);
  const [floating, setFloating] = useState<HTMLElement | null>(null);
  const holding = useRef(false); // a menu of the toolbar is open: keep it even if the selection changes
  const dragging = useRef(false);
  const { refs, floatingStyles } = useFloating({
    open: !!picked,
    placement: "top",
    strategy: "fixed",
    middleware: [offset(8), flip({ padding: 8 }), shift({ padding: 8 })],
    whileElementsMounted: autoUpdate,
    elements: { floating },
  });
  // The selection's rectangle as the toolbar's (virtual) anchor.
  useEffect(() => {
    if (picked) refs.setPositionReference({ getBoundingClientRect: () => picked.rect });
  }, [picked, refs]);

  const hide = useCallback(() => {
    if (!holding.current) setPicked(null);
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!enabled || !root) return;
    let frame = 0;
    const check = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (dragging.current || holding.current) return;
        setPicked(readSelection(root));
      });
    };
    const down = (e: PointerEvent) => {
      if (root.contains(e.target as Node)) {
        dragging.current = true;
        hide();
      }
    };
    const up = () => {
      if (!dragging.current) return;
      dragging.current = false;
      check();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        holding.current = false;
        setPicked(null);
      } else if (e.shiftKey) check(); // selecting with the keyboard
    };
    const selectionChange = () => !dragging.current && !holding.current && check();
    root.addEventListener("pointerdown", down);
    root.addEventListener("scroll", hide, { passive: true });
    document.addEventListener("pointerup", up);
    document.addEventListener("keyup", key);
    document.addEventListener("selectionchange", selectionChange);
    return () => {
      cancelAnimationFrame(frame);
      root.removeEventListener("pointerdown", down);
      root.removeEventListener("scroll", hide);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("keyup", key);
      document.removeEventListener("selectionchange", selectionChange);
    };
  }, [enabled, rootRef, hide]);

  const done = () => {
    holding.current = false;
    setPicked(null);
    window.getSelection()?.removeAllRanges();
  };

  const show = enabled && picked;
  return (
    <FloatingPortal>
      <AnimatePresence>
        {show && (
          <div ref={setFloating} style={floatingStyles} className="z-50">
            <motion.div
              {...pop}
              role="toolbar"
              aria-label={`Ask about the selection in ${idsLabel(picked.ids)}`}
              onMouseDown={(e) => e.preventDefault()} // clicking the toolbar keeps the selection
              className="flex items-center gap-0.5 rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg"
            >
              <Action
                label="Explain"
                hint="What it says and why it is translated this way (an answer in the chat; nothing changes)"
                icon={<Lightbulb size={13} className="text-primary" />}
                disabled={!canAsk}
                why="The chat answers once the agents have finished"
                onClick={() => {
                  onSend(
                    `Explain this passage from ${idsLabel(picked.ids)}: «${quote(picked.text)}» — what it says and why it is translated this way. Answer only; don't change anything.`,
                  );
                  done();
                }}
              />
              <Action
                label="Other options"
                hint="Three other ways to translate these segments, to pick from (a proposal)"
                icon={<ListTree size={13} />}
                disabled={!editable}
                why="Alternatives open when the agents have finished"
                onClick={() => {
                  onRunTask("alternatives", picked.ids, "", 3);
                  done();
                }}
              />
              <RewriteMenu
                ids={picked.ids}
                editable={editable}
                onRunTask={onRunTask}
                onDone={done}
                onOpenChange={(o) => {
                  holding.current = o; // the menu takes focus: keep the toolbar while it is open
                }}
                className="h-7 border-0 bg-transparent px-2 text-xs font-medium text-foreground/90 shadow-none hover:bg-accent"
              />
              <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
              <Action
                label="Ask…"
                hint="Quote it in the chat box and ask your own question"
                icon={<MessageSquarePlus size={13} />}
                disabled={!canAsk}
                why="The chat opens once the agents have finished"
                onClick={() => {
                  onDraft(`> «${quote(picked.text)}» (${idsLabel(picked.ids)})\n`);
                  done();
                }}
              />
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </FloatingPortal>
  );
}

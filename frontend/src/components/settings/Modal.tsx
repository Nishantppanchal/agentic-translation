"use client";

import { X } from "lucide-react";
import { Dialog } from "radix-ui";

/** A modal (Radix Dialog: focus trap, Esc, and the pickers and popovers inside it work); a click outside closes
 * it. `onClose` may decline (e.g. to ask about unsaved changes first) by returning false. */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  width = 640,
}: {
  open: boolean;
  onClose: () => boolean | void;
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40 data-[state=open]:animate-[fade-in_120ms_ease-out]" />
        <Dialog.Content
          // focus the dialog itself on open (not its first button), so nothing looks pressed
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            (e.currentTarget as HTMLElement | null)?.focus();
          }}
          tabIndex={-1}
          style={{ width: `min(${width}px, calc(100vw - 32px))` }}
          className="fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100vh-48px)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl border border-border bg-card text-foreground shadow-xl outline-none data-[state=open]:animate-[pop-in_140ms_ease-out]"
        >
          <div className="flex items-center justify-between border-b border-border px-5 py-3">
            <Dialog.Title className="text-sm font-semibold">{title}</Dialog.Title>
            <Dialog.Close className="rounded-md p-1 text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50" aria-label="Close">
              <X size={16} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">{description ?? title}</Dialog.Description>
          <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

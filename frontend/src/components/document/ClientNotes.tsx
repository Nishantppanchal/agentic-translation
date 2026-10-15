"use client";

import { Copy, Download, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useImperativeHandle, useState } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/settings/Modal";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { ClientNotesState } from "@/lib/types";
import { Markdown } from "./Markdown";

const errorText = (e: unknown) => {
  const msg = String(e).replace(/^Error: /, "");
  if (msg.startsWith("404")) return "Notes for the client aren't available on this server yet.";
  if (msg.startsWith("409")) return "There's nothing to write notes about yet: the document has no text.";
  if (msg.startsWith("502")) return "The AI couldn't write the notes just now. Try again in a moment.";
  return msg.replace(/^\d{3}: /, "");
};

/** Notes for the client: the decisions taken, the assumptions, open queries, what was left untranslated and the
 * quality checks — written by the Assist model from the document's own records. Copy them, download them, or
 * write them again after more changes. Notes written before open as they were. */
export function ClientNotes({
  ref,
  open,
  onClose,
  sessionId,
  filename,
  saved,
  latest,
  onSaved,
}: {
  ref?: React.Ref<{ write: () => void }>; // the menu that opens it starts the writing when there are no notes yet
  open: boolean;
  onClose: () => void;
  sessionId: string;
  filename: string;
  saved: ClientNotesState | null; // the notes stored with the document, if any
  latest: number; // the latest version (to say when the notes are older)
  onSaved: () => void; // new notes were stored with the document
}) {
  const [fresh, setFresh] = useState<ClientNotesState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const notes = fresh ?? saved;

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.clientNotes(sessionId);
      setFresh({ text: res.text, version: res.version, at: res.at });
      if (res.stored) onSaved();
      else toast("Notes written", { description: "Not saved with the document (the agents were working); copy or download them." });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  useImperativeHandle(ref, () => ({ write: () => !busy && generate() }));

  const copy = async () => {
    if (!notes) return;
    try {
      await navigator.clipboard.writeText(notes.text);
      toast.success("Copied", { description: "The notes are on your clipboard, as Markdown." });
    } catch {
      toast.error("Couldn't copy to the clipboard");
    }
  };
  const download = () => {
    if (!notes) return;
    const url = URL.createObjectURL(new Blob([notes.text], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename.replace(/\.[^.]+$/, "")} - notes for the client.md`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const older = notes?.version != null && latest > notes.version;

  return (
    <Modal open={open} onClose={onClose} title="Notes for the client" description="Decisions, assumptions and open queries to send with the translation" width={760}>
      <div className="flex min-h-0 flex-col gap-4">
        <p className="flex items-start gap-2 text-xs text-muted-foreground">
          <Sparkles size={14} className="mt-0.5 shrink-0 text-primary" />
          <span>
            Written by the AI from this document&apos;s records: your answers and the terms decided, the assumptions it made, open queries
            and comments, what was left untranslated, and the quality checks. Read them before sending.
          </span>
        </p>
        {notes && (
          <div className="-mb-2 flex items-center gap-2 text-[11px] text-muted-foreground">
            Written {new Date(notes.at * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
            {notes.version != null && <> · for v{notes.version}</>}
            {older && <span className="rounded-full bg-warn px-1.5 text-warn-fg">the translation has changed since (v{latest})</span>}
          </div>
        )}
        {busy && !notes ? (
          <div className="space-y-3 rounded-lg border border-border p-4" aria-busy>
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        ) : error && !notes ? (
          <p className="rounded-lg bg-del px-3 py-2 text-sm text-del-fg">{error}</p>
        ) : notes ? (
          <div className={`rounded-lg border border-border bg-background px-5 py-4 transition-opacity ${busy ? "opacity-50" : ""}`}>
            <Markdown text={notes.text} />
          </div>
        ) : null}
        {error && notes && <p className="text-xs text-del-fg">{error}</p>}
        <div className="sticky -bottom-4 -mx-5 -mb-4 flex items-center gap-2 border-t border-border bg-card/95 px-5 py-3 backdrop-blur">
          <Button variant="ghost" size="sm" onClick={generate} disabled={busy} className="mr-auto">
            {busy ? <Loader2 className="animate-spin" /> : <RefreshCw />} {notes ? "Write them again" : "Write the notes"}
          </Button>
          <Button variant="outline" size="sm" onClick={copy} disabled={!notes || busy}>
            <Copy /> Copy
          </Button>
          <Button size="sm" onClick={download} disabled={!notes || busy}>
            <Download /> Download .md
          </Button>
        </div>
      </div>
    </Modal>
  );
}

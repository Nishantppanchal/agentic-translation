"use client";

import { ChevronDown, Download, NotebookPen } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import type { ClientNotesState, ExportFormat } from "@/lib/types";
import { ClientNotes } from "./ClientNotes";

/** Downloads, grouped as the backend lists them (the translated Office file, Word, Markdown, the translation summary),
 * and "Translation summary…", which writes it. */
export function ExportMenu({
  sessionId,
  filename,
  version,
  latest,
  refreshKey,
  notes,
  onNotesSaved,
}: {
  sessionId: string;
  filename: string;
  version?: number;
  latest: number;
  refreshKey: string;
  notes: ClientNotesState | null; // the translation summary stored with the document
  onNotesSaved: () => void; // reload the document (its notes, and the "notes" download)
}) {
  const [formats, setFormats] = useState<ExportFormat[]>([]);
  const [notesOpen, setNotesOpen] = useState(false);
  const notesRef = useRef<{ write: () => void }>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    api
      .exportFormats(sessionId)
      // the notes download appears once notes are written ("Translation summary…" below writes it)
      .then((all) => setFormats(all.filter((f) => f.id !== "notes" || f.available)))
      .catch(() => setFormats([]));
  }, [sessionId, refreshKey, reload]);

  const groups = [...new Set(formats.map((f) => f.group))];
  return (
    <>
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <button
                className="flex h-8 items-center gap-0.5 rounded-md px-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground data-[state=open]:bg-accent data-[state=open]:text-foreground"
                aria-label="Download"
              >
                <Download size={16} />
                <ChevronDown size={12} className="opacity-60" />
              </button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>Download{version ? ` v${version}` : ""}</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="end" className="w-80">
          {groups.map((g, gi) => (
            <div key={g}>
              {gi > 0 && <DropdownMenuSeparator />}
              <DropdownMenuLabel className="text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">{g}</DropdownMenuLabel>
              {formats
                .filter((f) => f.group === g)
                .map((f) =>
                  f.available ? (
                    <DropdownMenuItem key={f.id} asChild>
                      <a href={api.exportUrl(sessionId, f.id === "notes" ? undefined : version, "target", f.id)} className="flex items-start justify-between gap-3">
                        <span className="min-w-0">
                          {f.label}
                          {f.note && <span className="mt-0.5 block text-[11px] text-warn-fg">{f.note}</span>}
                        </span>
                        <span className="shrink-0 pt-0.5 text-[10px] text-muted-foreground uppercase">{f.id === "md" ? "md/zip" : f.ext}</span>
                      </a>
                    </DropdownMenuItem>
                  ) : (
                    <DropdownMenuItem key={f.id} disabled className="flex items-start justify-between gap-3">
                      <span className="min-w-0">
                        {f.label}
                        {f.note && <span className="mt-0.5 block text-[11px]">{f.note}</span>}
                      </span>
                      <span className="shrink-0 pt-0.5 text-[10px] uppercase">n/a</span>
                    </DropdownMenuItem>
                  ),
                )}
            </div>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => {
              setNotesOpen(true);
              if (!notes) notesRef.current?.write(); // nothing written yet: write them now
            }}
            className="items-start"
          >
            <NotebookPen className="mt-0.5" />
            <span>
              Translation summary…
              <span className="block text-[11px] text-muted-foreground">Decisions, assumptions and open queries, written for you to send</span>
            </span>
          </DropdownMenuItem>
          {version && <div className="px-2 pt-1 pb-1.5 text-[10px] text-muted-foreground">Downloads version v{version}</div>}
        </DropdownMenuContent>
      </DropdownMenu>
      <ClientNotes
        ref={notesRef}
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        sessionId={sessionId}
        filename={filename}
        saved={notes}
        latest={latest}
        onSaved={() => {
          setReload((n) => n + 1);
          onNotesSaved();
        }}
      />
    </>
  );
}

"use client";

import { ChevronDown, Download, Loader2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ExportFormat } from "@/lib/types";

/** Grouped download menu (Original layout · Reflowed · Review · Exchange) + importing a returned XLIFF. */
export function ExportMenu({
  sessionId,
  version,
  refreshKey,
  canImport = false,
  onImported,
}: {
  sessionId: string;
  version?: number;
  refreshKey: string;
  canImport?: boolean;
  onImported?: () => void;
}) {
  const [formats, setFormats] = useState<ExportFormat[]>([]);
  const [open, setOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const importFile = async (file: File) => {
    setImporting(true);
    setMessage(null);
    try {
      const r = await api.importXliff(sessionId, file);
      setMessage(r.changes ? `${r.changes} change${r.changes === 1 ? "" : "s"} proposed — review them in the chat.` : "No changes to apply.");
      onImported?.();
    } catch (e) {
      setMessage(String(e));
    } finally {
      setImporting(false);
    }
  };

  useEffect(() => {
    api.exportFormats(sessionId).then(setFormats).catch(() => setFormats([]));
  }, [sessionId, refreshKey]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const groups = [...new Set(formats.map((f) => f.group))];
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 rounded-md px-1.5 py-1 text-muted hover:bg-sidebar hover:text-fg"
        title="Export"
      >
        <Download size={16} />
        <ChevronDown size={12} />
      </button>
      {open && (
        <div className="absolute top-8 right-0 z-30 w-72 rounded-lg border border-border bg-panel p-1.5 text-sm shadow-lg">
          {groups.map((g) => (
            <div key={g} className="mb-1 last:mb-0">
              <div className="px-2 pt-1 pb-0.5 text-[10px] font-medium tracking-wide text-muted uppercase">{g}</div>
              {formats
                .filter((f) => f.group === g)
                .map((f) =>
                  f.available ? (
                    <a
                      key={f.id}
                      href={api.exportUrl(sessionId, version, "target", f.id)}
                      onClick={() => setOpen(false)}
                      className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-sidebar"
                    >
                      <span>
                        {f.label}
                        {f.note && <span className="mt-0.5 block text-[11px] text-warn-fg">{f.note}</span>}
                      </span>
                      <span className="text-[10px] text-muted uppercase">{f.id === "md" ? "md/zip" : f.ext}</span>
                    </a>
                  ) : (
                    <div
                      key={f.id}
                      className="flex cursor-not-allowed items-center justify-between rounded-md px-2 py-1.5 text-muted opacity-60"
                      title={
                        f.id === "original"
                          ? "Only for Word, PowerPoint, Excel and XLIFF documents"
                          : "Needs a PDF or a page image; scans also need the layout server (PP-OCRv5) to find the text lines"
                      }
                    >
                      {f.label}
                      <span className="text-[10px] uppercase">n/a</span>
                    </div>
                  ),
                )}
            </div>
          ))}
          <div className="mt-1 border-t border-border pt-1">
            <button
              disabled={!canImport || importing}
              onClick={() => fileRef.current?.click()}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-sidebar disabled:opacity-50"
              title={canImport ? "Bring back an XLIFF translated or reviewed in another CAT tool — changes come in as a proposal" : "Available when the agents have finished"}
            >
              {importing ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} Import a returned XLIFF…
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".xlf,.xliff,.xml"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) importFile(f);
              }}
            />
            {message && <div className="px-2 pb-1 text-[11px] text-muted">{message}</div>}
          </div>
          {version && <div className="border-t border-border px-2 pt-1.5 text-[10px] text-muted">Exports version v{version}</div>}
        </div>
      )}
    </div>
  );
}

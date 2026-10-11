"use client";

import { ArrowRight, FileUp, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import type { Project } from "@/lib/types";

const ACCEPT = ".pdf,.docx,.pptx,.xlsx,.xlf,.xliff,.png,.jpg,.jpeg,.webp,.txt,.md";

export function UploadPanel({
  languages,
  projects,
  initialProject,
  onSubmit,
}: {
  languages: string[];
  projects: Project[];
  initialProject: string | null;
  onSubmit: (file: File, sourceLang: string, projectId: string | null) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [projectId, setProjectId] = useState<string | null>(initialProject);
  const [ownSource, setSource] = useState("auto-detect");
  const project = projects.find((p) => p.id === projectId) ?? null;
  // A project fixes the source language.
  const source = project?.source_lang || ownSource;
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(file, source, project?.id ?? null);
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="w-full max-w-xl">
        <h1 className="text-2xl font-semibold tracking-tight">Translate a document into English</h1>
        <p className="mt-1 text-sm text-muted">
          Upload a PDF or image (read with OCR), a Word, PowerPoint or Excel file, or an XLIFF file from another CAT tool
          (read directly, formatting kept). Agents read the whole document, ask you about terms that need a decision
          (explained in English), then translate, review and refine. Keep improving it by chatting, and download it in its
          original format.
        </p>

        <div
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files?.[0];
            if (f) setFile(f);
          }}
          className={`mt-6 flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition ${
            dragging ? "border-accent bg-accent-soft" : "border-border bg-panel hover:border-accent"
          }`}
        >
          <FileUp className="text-muted" size={32} />
          {file ? (
            <p className="mt-3 text-sm font-medium">
              {file.name} <span className="text-muted">({(file.size / 1024).toFixed(0)} KB)</span>
            </p>
          ) : (
            <p className="mt-3 text-sm text-muted">Drop a file here or click to browse</p>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>

        {projects.length > 0 && (
          <label className="mt-4 block text-sm">
            <span className="text-muted">Project</span>
            <select
              value={projectId ?? ""}
              onChange={(e) => setProjectId(e.target.value || null)}
              className="mt-1 w-full rounded-lg border border-border bg-panel px-3 py-2"
            >
              <option value="">No project</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.source_lang} → English)
                </option>
              ))}
            </select>
            {project && (
              <span className="mt-1 block text-xs text-muted">
                Uses the project&apos;s style guide, {project.terms} term{project.terms === 1 ? "" : "s"} and {project.tm_units} translation-memory unit
                {project.tm_units === 1 ? "" : "s"}.
              </span>
            )}
          </label>
        )}

        <div className="mt-4 flex items-end gap-3 text-sm">
          <label className="flex-1">
            <span className="text-muted">From</span>
            <select
              value={source}
              disabled={!!project}
              onChange={(e) => setSource(e.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-panel px-3 py-2 disabled:opacity-60"
            >
              <option value="auto-detect">Auto-detect</option>
              {languages.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>
          </label>
          <ArrowRight size={16} className="mb-3 text-muted" />
          <div className="flex-1">
            <span className="text-muted">Into</span>
            <div className="mt-1 rounded-lg border border-border bg-sidebar px-3 py-2">English</div>
          </div>
        </div>

        {error && <p className="mt-3 text-sm text-del-fg">{error}</p>}

        <button
          disabled={!file || busy}
          onClick={submit}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white disabled:opacity-40"
        >
          {busy && <Loader2 size={16} className="animate-spin" />}
          Translate
        </button>
      </div>
    </div>
  );
}

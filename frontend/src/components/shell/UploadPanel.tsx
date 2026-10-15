"use client";

import { ArrowRight, BookOpen, Brain, FileImage, FileSpreadsheet, FileText, FileUp, Loader2, Presentation, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { cn } from "cn";
import { useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { SettingsUpdate } from "@/lib/api";
import { rise, spring } from "@/lib/motion";
import type { ModelChoices, Project } from "@/lib/types";
import { ChoicesDialog } from "../settings/ChoicesDialog";
import { changedSteps, groupSummaries, useModelCatalog } from "../settings/ModelChoices";
import { ModelLogo } from "../settings/ModelLogo";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.docx,.docm,.pptx,.pptm,.xlsx,.xlsm,.txt,.md,.markdown";
const FORMATS = ["PDF", "Images", "Word", "PowerPoint", "Excel", "Text / Markdown"];
const NO_PROJECT = "none";
const AUTO = "auto-detect";

function FileIcon({ name }: { name: string | null }) {
  const ext = name?.split(".").pop()?.toLowerCase() ?? "";
  if (!name) return <FileUp size={22} />;
  if (["xlsx", "xlsm"].includes(ext)) return <FileSpreadsheet size={22} />;
  if (["pptx", "pptm"].includes(ext)) return <Presentation size={22} />;
  if (["png", "jpg", "jpeg", "webp"].includes(ext)) return <FileImage size={22} />;
  return <FileText size={22} />;
}

const size = (bytes: number) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

export function UploadPanel({
  languages,
  projects,
  initialProject,
  onSubmit,
}: {
  languages: string[];
  projects: Project[];
  initialProject: string | null;
  onSubmit: (file: File, sourceLang: string, projectId: string | null, overrides?: SettingsUpdate) => Promise<void>;
}) {
  const catalog = useModelCatalog();
  // This document's own models and dictionary; null = the defaults (Settings).
  const [own, setOwn] = useState<{ models: ModelChoices; dictionary: boolean } | null>(null);
  const [choosing, setChoosing] = useState(false);
  const defaults = catalog.settings ? { models: catalog.settings.models, dictionary: catalog.settings.dictionary.enabled } : null;
  const effective = own ?? defaults;
  const [file, setFile] = useState<File | null>(null);
  const [projectId, setProjectId] = useState<string | null>(initialProject);
  const [ownSource, setSource] = useState(AUTO);
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
      const overrides: SettingsUpdate | undefined =
        own && catalog.settings
          ? {
              models: changedSteps(own.models, catalog.settings.models),
              ...(own.dictionary !== catalog.settings.dictionary.enabled ? { dictionary: own.dictionary } : {}),
            }
          : undefined;
      await onSubmit(file, source, project?.id ?? null, overrides);
    } catch (e) {
      setError(String(e).replace(/^Error: /, ""));
      setBusy(false);
    }
  };

  const dictOn = !!effective?.dictionary && !!catalog.settings?.dictionary.available;

  return (
    <div className="scroll-thin flex h-full justify-center overflow-y-auto p-8">
      <motion.div {...rise} className="my-auto w-full max-w-xl py-6">
        <h1 className="text-2xl font-semibold tracking-tight">Translate a document into English</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          The agents read the whole document, ask you about terms that need a decision (explained in English), then translate,
          review and refine it. Keep improving it by chatting, and download it.
        </p>

        <motion.div
          role="button"
          tabIndex={0}
          aria-label={file ? `Chosen: ${file.name}. Choose another file` : "Choose a file to translate"}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), inputRef.current?.click())}
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
          animate={{ scale: dragging ? 1.015 : 1 }}
          transition={spring}
          className={cn(
            "mt-6 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50",
            dragging ? "border-primary bg-primary-soft" : file ? "border-primary/40 bg-card" : "border-border bg-card hover:border-primary/50",
          )}
        >
          <motion.span
            key={file?.name ?? "none"}
            initial={{ scale: 0.85, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={spring}
            className={cn("flex size-12 items-center justify-center rounded-full", file ? "bg-primary-soft text-primary" : "bg-muted text-muted-foreground")}
          >
            <FileIcon name={file?.name ?? null} />
          </motion.span>
          <AnimatePresence mode="wait" initial={false}>
            {file ? (
              <motion.div key="file" {...rise} className="mt-3 flex items-center gap-2 text-sm">
                <span className="max-w-80 truncate font-medium">{file.name}</span>
                <span className="text-muted-foreground">{size(file.size)}</span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setFile(null);
                    if (inputRef.current) inputRef.current.value = "";
                  }}
                  className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                  aria-label="Remove the file"
                >
                  <X size={14} />
                </button>
              </motion.div>
            ) : (
              <motion.div key="empty" {...rise} className="mt-3 text-sm">
                <span className="font-medium">Drop a file here</span> <span className="text-muted-foreground">or click to browse</span>
              </motion.div>
            )}
          </AnimatePresence>
          <div className="mt-3 flex flex-wrap justify-center gap-1">
            {FORMATS.map((f) => (
              <Badge key={f} variant="secondary" className="font-normal text-muted-foreground">
                {f}
              </Badge>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">PDFs and images are read with OCR; Word, PowerPoint and Excel keep their layout.</p>
          <input ref={inputRef} type="file" accept={ACCEPT} className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </motion.div>

        <div className="mt-5 grid gap-4">
          {projects.length > 0 && (
            <div className="grid gap-1.5">
              <Label htmlFor="upload-project" className="text-muted-foreground">
                Project
              </Label>
              <Select value={projectId ?? NO_PROJECT} onValueChange={(v) => setProjectId(v === NO_PROJECT ? null : v)}>
                <SelectTrigger id="upload-project" className="w-full bg-card">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_PROJECT}>No project</SelectItem>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name} <span className="text-muted-foreground">({p.source_lang} → English)</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {project && (
                <span className="text-xs text-muted-foreground">
                  Uses the project&apos;s style guide, {project.terms} term{project.terms === 1 ? "" : "s"} and {project.tm_units} translation-memory unit
                  {project.tm_units === 1 ? "" : "s"}.
                </span>
              )}
            </div>
          )}

          <div className="flex items-end gap-3">
            <div className="grid flex-1 gap-1.5">
              <Label htmlFor="upload-from" className="text-muted-foreground">
                From
              </Label>
              <Select value={source} onValueChange={setSource} disabled={!!project}>
                <SelectTrigger id="upload-from" className="w-full bg-card">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={AUTO}>Auto-detect</SelectItem>
                  {[...new Set([...languages, ...(project?.source_lang ? [project.source_lang] : [])])].map((l) => (
                    <SelectItem key={l} value={l}>
                      {l}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <ArrowRight size={16} className="mb-2.5 shrink-0 text-muted-foreground" />
            <div className="grid flex-1 gap-1.5">
              <span className="text-sm font-medium text-muted-foreground">Into</span>
              <div className="flex h-9 items-center rounded-md border border-input bg-muted px-3 text-sm">English</div>
            </div>
          </div>

          <div className="grid gap-1.5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                <Brain size={14} /> Models {own && <Badge className="ml-1 h-4 bg-primary-soft px-1.5 text-[10px] text-primary">this document</Badge>}
              </span>
              <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => setChoosing(true)} disabled={!catalog.settings || !catalog.models}>
                <Brain /> Change
              </Button>
            </div>
            {effective && catalog.settings ? (
              <div className="flex flex-wrap gap-1.5">
                {groupSummaries(effective.models, catalog.settings, catalog.models).map(({ group, model, label }) => (
                  <button
                    key={group.id}
                    onClick={() => setChoosing(true)}
                    className="flex h-7 max-w-full items-center gap-1.5 rounded-full border border-border bg-card px-2.5 text-xs shadow-xs transition-colors hover:border-primary/40"
                    title={group.help}
                  >
                    {/* the company's logo; a group whose steps use different models: the generic one */}
                    {model ? <ModelLogo model={model} size={13} /> : <Brain size={13} className="shrink-0 text-muted-foreground" />}
                    <span className="text-muted-foreground">{group.label}:</span>
                    <span className="truncate">{label}</span>
                  </button>
                ))}
                <button
                  onClick={() => setChoosing(true)}
                  className="flex h-7 items-center gap-1.5 rounded-full border border-border bg-card px-2.5 text-xs shadow-xs transition-colors hover:border-primary/40"
                >
                  <BookOpen size={13} className={dictOn ? "text-primary" : "text-muted-foreground"} />
                  <span className="text-muted-foreground">Dictionary:</span> {dictOn ? "on" : "off"}
                </button>
              </div>
            ) : catalog.error ? (
              <p className="text-xs text-del-fg">Couldn&apos;t load the models: {catalog.error}</p>
            ) : (
              <div className="flex gap-1.5">
                <Skeleton className="h-7 w-48 rounded-full" />
                <Skeleton className="h-7 w-40 rounded-full" />
                <Skeleton className="h-7 w-32 rounded-full" />
              </div>
            )}
          </div>
        </div>

        {effective && catalog.settings && catalog.models && (
          <ChoicesDialog
            open={choosing}
            onClose={() => setChoosing(false)}
            title="Models for this document"
            note="Only this document uses these; the defaults for every new document are in Settings."
            models={catalog.models}
            settings={catalog.settings}
            value={effective}
            dictionary={catalog.settings.dictionary}
            saveLabel="Use for this document"
            onSave={(v) => setOwn(v)}
          />
        )}

        <AnimatePresence>
          {error && (
            <motion.p {...rise} className="mt-4 rounded-lg bg-del px-3 py-2 text-sm text-del-fg">
              {error}
            </motion.p>
          )}
        </AnimatePresence>

        <Button size="lg" disabled={!file || busy} onClick={submit} className="mt-6 w-full">
          {busy && <Loader2 className="animate-spin" />}
          Translate
        </Button>
      </motion.div>
    </div>
  );
}

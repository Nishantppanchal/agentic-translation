"use client";

import { ChevronDown, Loader2 } from "lucide-react";
import { useState } from "react";
import { cn } from "cn";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import type { AppSettingsView, DocSettings, ModelInfo, StepChoice } from "@/lib/types";
import { choiceLabel, defaultEffort, EFFORT_LABEL, EffortToggle, ModelSelect } from "../settings/ModelChoices";
import { ModelLogo } from "../settings/ModelLogo";

/** The model the chat runs on for this document (and its reasoning level), changed right from the chat box. It
 * applies from the next message; not while the agents are working (the server refuses then). */
export function ChatModelPicker({
  sessionId,
  settings: doc,
  models,
  catalog,
  busy,
  onSaved,
}: {
  sessionId: string;
  settings: DocSettings;
  models: ModelInfo[];
  catalog: AppSettingsView;
  busy: boolean;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const choice = doc.models.editor;
  if (!choice) return null;
  const model = models.find((m) => m.id === choice.model);
  const fallback = defaultEffort(catalog, models, "editor", choice.model);

  const save = async (next: StepChoice) => {
    setSaving(true);
    setError(null);
    try {
      await api.patchSessionSettings(sessionId, { models: { editor: next } });
      onSaved();
    } catch (e) {
      setError(String(e).replace(/^Error: /, "").replace(/^409: .*/, "Wait for the agents to finish."));
    } finally {
      setSaving(false);
    }
  };

  const trigger = (
    <button
      type="button"
      disabled={busy}
      className={cn(
        "flex max-w-56 min-w-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-xs text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50",
        open && "bg-accent text-foreground",
      )}
      aria-label={`Chat model: ${choiceLabel(choice, models, catalog, "editor")}. Change`}
    >
      {saving ? <Loader2 size={13} className="animate-spin" /> : <ModelLogo model={model} size={13} />}
      <span className="truncate">{choiceLabel(choice, models, catalog, "editor")}</span>
      <ChevronDown size={12} className="shrink-0 opacity-60" />
    </button>
  );

  if (busy) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span>{trigger}</span>
        </TooltipTrigger>
        <TooltipContent>The chat model can change once the agents finish</TooltipContent>
      </Tooltip>
    );
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-80 space-y-3">
        <div>
          <div className="text-sm font-medium">Chat model</div>
          <div className="text-xs text-muted-foreground">For this document. It looks at page images, so only models that read images.</div>
        </div>
        <ModelSelect
          value={choice.model}
          models={models}
          visionOnly
          onChange={(id) => save({ model: id, effort: models.find((m) => m.id === id)?.thinking && model?.thinking ? choice.effort : null })}
          label="Chat model"
          className="w-full"
        />
        <EffortToggle
          value={choice.effort}
          model={model}
          fallback={fallback}
          onChange={(effort) => save({ ...choice, effort })}
          label="Chat reasoning level"
          compact
        />
        {model?.thinking && fallback && (
          <div className="text-[11px] text-muted-foreground">
            {choice.effort === null ? (
              <>Following the default level: {EFFORT_LABEL[fallback.effort]} ({fallback.from})</>
            ) : (
              <button type="button" onClick={() => save({ ...choice, effort: null })} className="text-primary hover:underline">
                Use the default level ({EFFORT_LABEL[fallback.effort]})
              </button>
            )}
          </div>
        )}
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>Applies from your next message.</span>
          {saving && <Loader2 size={12} className="animate-spin" />}
        </div>
        {error && <p className="text-xs text-del-fg">{error}</p>}
      </PopoverContent>
    </Popover>
  );
}

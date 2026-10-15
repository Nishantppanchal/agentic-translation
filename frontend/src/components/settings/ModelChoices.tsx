"use client";

import { BookOpen, ChevronRight, Eye, Lightbulb, RotateCcw } from "lucide-react";
import { cn } from "cn";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import type { AppSettingsView, DictionaryStatus, Effort, ModelChoices, ModelInfo, StepChoice, StepGroup, StepId } from "@/lib/types";
import { ModelLogo, ServerBadge } from "./ModelLogo";
import { PipelineFlow } from "./PipelineFlow";

export const EFFORTS: Effort[] = ["instant", "low", "medium", "high"];
export const EFFORT_LABEL: Record<Effort, string> = { instant: "Instant", low: "Low", medium: "Medium", high: "High" };
export const EFFORT_HELP: Record<Effort, string> = {
  instant: "No thinking: the fastest and cheapest.",
  low: "A little thinking first.",
  medium: "Thinks before answering: slower, more tokens.",
  high: "Thinks the longest: the slowest, the most tokens.",
};
const FROM: Record<string, string> = { "pipeline.yaml": "pipeline.yaml", "models.yaml": "models.yaml", "built-in": "the app's default" };

/** The model list and the app's settings (Settings, the upload panel, a document's settings, the chat box). */
export function useModelCatalog() {
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [settings, setSettings] = useState<AppSettingsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    Promise.all([api.models(), api.getSettings()])
      .then(([m, s]) => {
        setModels(m);
        setSettings(s);
        setError(null);
      })
      .catch((e) => setError(String(e).replace(/^Error: /, "")));
  }, []);
  useEffect(load, [load]);
  return { models, settings, setSettings, error, reload: load };
}

export const sameChoice = (a: StepChoice | undefined, b: StepChoice | undefined) =>
  !!a && !!b && a.model === b.model && (a.effort ?? null) === (b.effort ?? null);

/** One choice for all the steps of a group, or "mixed" when they differ. */
export function groupChoice(choices: ModelChoices, steps: StepId[]): StepChoice | "mixed" {
  const first = choices[steps[0]];
  return steps.every((s) => sameChoice(choices[s], first)) ? first : "mixed";
}

/** The level "Default" stands for on this step with this model, and where it's set; null for a model that doesn't think. */
export function defaultEffort(settings: AppSettingsView | null, models: ModelInfo[] | null, step: StepId, modelId: string) {
  const d = settings?.defaults?.[step]?.[modelId];
  if (d) return { effort: d.effort, from: FROM[d.from] ?? d.from };
  const m = models?.find((x) => x.id === modelId);
  return m?.thinking && m.default_effort ? { effort: m.default_effort, from: "models.yaml" } : null;
}

/** The level a step actually runs at: the one chosen, or the default (and whether it is the default). */
export function effectiveEffort(settings: AppSettingsView | null, models: ModelInfo[] | null, step: StepId, choice: StepChoice) {
  const m = models?.find((x) => x.id === choice.model);
  if (!m?.thinking) return null;
  if (choice.effort) return { effort: choice.effort, isDefault: false, from: null as string | null };
  const d = defaultEffort(settings, models, step, choice.model);
  return d ? { effort: d.effort, isDefault: true, from: d.from as string | null } : null;
}

export const modelLabel = (models: ModelInfo[] | null, id: string) => models?.find((m) => m.id === id)?.label ?? id;

/** "Claude Haiku 5.5 · Low" (the level as it runs; "(default)" when nobody chose it). */
export function choiceLabel(
  choice: StepChoice | "mixed",
  models: ModelInfo[] | null,
  settings: AppSettingsView | null = null,
  step: StepId | null = null,
  { showDefault = false } = {},
): string {
  if (choice === "mixed") return "Mixed";
  const level = step ? effectiveEffort(settings, models, step, choice) : choice.effort ? { effort: choice.effort, isDefault: false } : null;
  const effort = level ? ` · ${EFFORT_LABEL[level.effort]}${showDefault && level.isDefault ? " (default)" : ""}` : "";
  return `${modelLabel(models, choice.model)}${effort}`;
}

/** Only steps whose choice differs from `base` (what an upload or a document sends). */
export function changedSteps(choices: ModelChoices, base: ModelChoices): Partial<ModelChoices> {
  const out: Partial<ModelChoices> = {};
  for (const step of Object.keys(choices) as StepId[]) if (!sameChoice(choices[step], base[step])) out[step] = choices[step];
  return out;
}

/** One chip per group, for compact summaries (the upload panel, the document chip): the group's model with its
 * logo, and its level — or the levels when the steps run at different ones ("Qwen3.8 Flash · Instant / Low"). */
export function groupSummaries(choices: ModelChoices, settings: AppSettingsView, models: ModelInfo[] | null) {
  return settings.groups.map((g) => {
    const ids = [...new Set(g.steps.map((s) => choices[s]?.model))];
    const model = ids.length === 1 ? (models?.find((m) => m.id === ids[0]) ?? null) : null;
    const levels = [
      ...new Set(g.steps.map((s) => (choices[s] ? effectiveEffort(settings, models, s, choices[s]) : null)).map((l) => (l ? EFFORT_LABEL[l.effort] : null))),
    ].filter(Boolean);
    const label = ids.length > 1 ? "Mixed models" : `${model?.label ?? ids[0]}${levels.length ? ` · ${levels.join(" / ")}` : ""}`;
    return { group: g, choice: groupChoice(choices, g.steps), model, label };
  });
}

// --------------------------------------------------------------------------- //
// Pickers
// --------------------------------------------------------------------------- //

/** A model picker: logo, name, where it runs, and what it can do. Models that can't read images are listed but
 * disabled for steps that look at pages. */
export function ModelSelect({
  value,
  models,
  visionOnly,
  onChange,
  label,
  className,
  size = "default",
}: {
  value: string | "mixed";
  models: ModelInfo[];
  visionOnly: boolean;
  onChange: (id: string) => void;
  label: string;
  className?: string;
  size?: "sm" | "default";
}) {
  const current = models.find((m) => m.id === value);
  return (
    <Select value={value === "mixed" ? undefined : value} onValueChange={onChange}>
      <SelectTrigger aria-label={label} size={size} className={cn("min-w-0 bg-card", className)}>
        <SelectValue placeholder={value === "mixed" ? "Mixed (see each step)" : `Unavailable: ${value}`}>
          {current && (
            <span className="flex min-w-0 items-center gap-2">
              <ModelLogo model={current} size={15} />
              <span className="truncate">{current.label}</span>
            </span>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="max-h-96">
        {models.map((m) => {
          const blocked = visionOnly && !m.vision;
          return (
            <SelectItem key={m.id} value={m.id} disabled={blocked} className="py-2">
              <span className="flex min-w-0 items-start gap-2.5">
                <ModelLogo model={m} size={18} className="mt-0.5" />
                <span className="min-w-0">
                  <span className="block font-medium">{m.label}</span>
                  <span className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
                    <span className="font-mono">{m.model_name}</span>·<ServerBadge model={m} />
                  </span>
                  <span className="mt-1 flex flex-wrap gap-1">
                    {m.vision && (
                      <Badge variant="secondary" className="h-5 gap-1 px-1.5 text-[10px]">
                        <Eye /> Reads images
                      </Badge>
                    )}
                    {m.thinking && (
                      <Badge variant="secondary" className="h-5 gap-1 px-1.5 text-[10px]">
                        <Lightbulb /> Thinks
                      </Badge>
                    )}
                    {blocked && <span className="text-[11px] text-del-fg">Can&apos;t read page images</span>}
                  </span>
                </span>
              </span>
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}

/** Instant / Low / Medium / High. Nobody chose one: the default level is selected and tagged; picking one pins it
 * ("Use default" goes back). A model that doesn't think says so. */
export function EffortToggle({
  value,
  model,
  fallback,
  onChange,
  label,
  compact = false,
}: {
  value: Effort | null | "mixed";
  model: ModelInfo | undefined;
  fallback: { effort: Effort; from: string } | null; // what Default stands for
  onChange: (e: Effort | null) => void;
  label: string;
  compact?: boolean;
}) {
  if (!model?.thinking) {
    return (
      <span className={cn("flex h-8 shrink-0 items-center text-xs text-muted-foreground", compact ? "" : "w-[248px]")}>
        This model doesn&apos;t reason
      </span>
    );
  }
  const shown = value === "mixed" ? undefined : (value ?? fallback?.effort);
  return (
    <div className={cn("flex shrink-0 flex-col gap-1", compact ? "" : "w-[248px]")}>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={shown ?? ""}
        onValueChange={(v) => v && onChange(v === fallback?.effort && value === null ? null : (v as Effort))}
        aria-label={label}
        className="w-full"
      >
        {EFFORTS.map((e) => (
          <Tooltip key={e}>
            <TooltipTrigger asChild>
              <ToggleGroupItem
                value={e}
                className="relative flex-1 text-xs aria-checked:bg-primary-soft aria-checked:font-medium aria-checked:text-primary"
                aria-label={`${EFFORT_LABEL[e]}${fallback?.effort === e ? " (default)" : ""}`}
              >
                {EFFORT_LABEL[e]}
                {fallback?.effort === e && (
                  <span className="absolute top-0.5 right-0.5 size-1.5 rounded-full bg-primary/70" aria-hidden />
                )}
              </ToggleGroupItem>
            </TooltipTrigger>
            <TooltipContent>
              {EFFORT_HELP[e]}
              {fallback?.effort === e && ` The default here (from ${fallback.from}).`}
            </TooltipContent>
          </Tooltip>
        ))}
      </ToggleGroup>
      {!compact && (
        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          {value === "mixed" ? (
            "Steps differ"
          ) : value === null ? (
            fallback && <>Default: {EFFORT_LABEL[fallback.effort]} ({fallback.from})</>
          ) : (
            <>
              Chosen: {EFFORT_LABEL[value]}
              <button type="button" onClick={() => onChange(null)} className="text-primary hover:underline">
                Use default{fallback ? ` (${EFFORT_LABEL[fallback.effort]})` : ""}
              </button>
            </>
          )}
        </span>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// The editor: diagram, one row per group, and each step under Advanced
// --------------------------------------------------------------------------- //

/** Model and reasoning level per group of steps (with the pipeline diagram showing what each changes), and per
 * step under "Advanced" or by clicking a step in the diagram. `base`: what a row counts as changed from (and
 * resets to) — pipeline.yaml in Settings, the app's defaults for one document. */
export function ModelChoicesEditor({
  value,
  onChange,
  models,
  settings,
  base,
  baseLabel,
}: {
  value: ModelChoices;
  onChange: (next: ModelChoices) => void;
  models: ModelInfo[];
  settings: AppSettingsView;
  base: ModelChoices;
  baseLabel: string;
}) {
  const byId = useMemo(() => new Map(models.map((m) => [m.id, m])), [models]);
  const [hover, setHover] = useState<StepId[] | null>(null);
  const [pulse, setPulse] = useState<{ steps: StepId[]; at: number } | null>(null);
  const set = (steps: StepId[], update: (old: StepChoice) => StepChoice) => {
    const next = { ...value };
    for (const s of steps) next[s] = update(value[s]);
    onChange(next);
    setPulse((p) => ({ steps, at: (p?.at ?? 0) + 1 }));
  };
  // A model that doesn't think has no level; a thinking one keeps the level it had (or follows the default).
  const pickModel = (steps: StepId[], id: string) =>
    set(steps, (old) => ({ model: id, effort: byId.get(id)?.thinking && byId.get(old.model)?.thinking ? old.effort : null }));
  const pickEffort = (steps: StepId[], effort: Effort | null) => set(steps, (old) => ({ ...old, effort }));
  const reset = (steps: StepId[]) => {
    const next = { ...value };
    for (const s of steps) if (base[s]) next[s] = base[s];
    onChange(next);
    setPulse((p) => ({ steps, at: (p?.at ?? 0) + 1 }));
  };
  const changed = new Set((Object.keys(value) as StepId[]).filter((s) => !sameChoice(value[s], base[s])));
  const stepLabel = new Map(settings.steps.map((s) => [s.step, s.label]));
  const differs = (s: StepId, g: StepGroup) => !sameChoice(value[s], value[g.steps[0]]);

  const row = (key: string, label: string, help: string | null, steps: StepId[], vision: boolean, extra?: React.ReactNode) => {
    // The model and the level are shown as "mixed" separately: steps on one model at different levels are one model.
    const modelId = steps.every((s) => value[s].model === value[steps[0]].model) ? value[steps[0]].model : "mixed";
    const effort = steps.every((s) => (value[s].effort ?? null) === (value[steps[0]].effort ?? null)) ? (value[steps[0]].effort ?? null) : "mixed";
    const model = modelId === "mixed" ? undefined : byId.get(modelId);
    const thinking = model ?? steps.map((s) => byId.get(value[s].model)).find((m) => m?.thinking);
    const fallback = modelId === "mixed" ? null : defaultEffort(settings, models, steps[0], modelId);
    const isChanged = steps.some((s) => changed.has(s));
    return (
      <div
        key={key}
        className="group/row flex items-start gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-accent/60 focus-within:bg-accent/60"
        onMouseEnter={() => setHover(steps)}
        onMouseLeave={() => setHover(null)}
        onFocus={() => setHover(steps)}
        onBlur={() => setHover(null)}
      >
        <div className="w-40 shrink-0 pt-1.5">
          <div className="flex items-center gap-1.5 text-sm font-medium">
            {label}
            {isChanged && <span className="size-1.5 rounded-full bg-primary" title={`Changed from ${baseLabel}`} />}
            {extra}
          </div>
          {help && <div className="text-[11px] leading-snug text-muted-foreground">{help}</div>}
        </div>
        <ModelSelect value={modelId} models={models} visionOnly={vision} onChange={(id) => pickModel(steps, id)} label={`${label} model`} className="h-8 flex-1" size="sm" />
        <EffortToggle
          value={effort}
          model={thinking}
          fallback={fallback}
          onChange={(e) => pickEffort(steps.filter((s) => byId.get(value[s].model)?.thinking), e)}
          label={`${label} reasoning level`}
        />
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={() => reset(steps)}
              disabled={!isChanged}
              className="mt-1 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:invisible"
              aria-label={`Reset ${label} to ${baseLabel}`}
            >
              <RotateCcw size={14} />
            </button>
          </TooltipTrigger>
          <TooltipContent>Back to {baseLabel}</TooltipContent>
        </Tooltip>
      </div>
    );
  };

  return (
    <div className="space-y-3">
      <PipelineFlow
        spec={settings.flow}
        choices={value}
        models={models}
        settings={settings}
        highlight={hover}
        changed={changed}
        pulse={pulse}
        onChange={(step, choice) => set([step], () => choice)}
      />
      <div className="-mx-2">{settings.groups.map((g) => row(g.id, g.label, g.help, g.steps, g.vision))}</div>
      <Collapsible>
        <CollapsibleTrigger className="group/adv flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ChevronRight size={12} className="transition-transform group-data-[state=open]/adv:rotate-90" /> Advanced: a model for each step
          <span className="ml-1">(or click a step in the diagram)</span>
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-1 border-l border-border pl-2">
          {settings.groups.flatMap((g) =>
            g.steps.map((s) =>
              row(
                s,
                stepLabel.get(s) ?? s,
                null,
                [s],
                settings.steps.find((x) => x.step === s)?.vision ?? false,
                g.steps.length > 1 && differs(s, g) ? (
                  <Badge variant="outline" className="h-4 px-1 text-[9px] font-normal">
                    differs from {g.label}
                  </Badge>
                ) : null,
              ),
            ),
          )}
        </CollapsibleContent>
      </Collapsible>
      <p className="text-[11px] text-muted-foreground">
        Reading and Chat need models that read images. Reasoning levels are for models marked <code>thinking: true</code> in
        models.yaml; each step&apos;s default level comes from pipeline.yaml, then the model&apos;s own <code>effort</code>, then Medium.
      </p>
    </div>
  );
}

/** Use the dictionary (when one is set up). */
export function DictionarySwitch({ status, on, onChange }: { status: DictionaryStatus; on: boolean; onChange: (on: boolean) => void }) {
  return (
    <label className="flex items-start gap-3">
      <Switch checked={on && status.available} disabled={!status.available} onCheckedChange={onChange} className="mt-0.5" />
      <span className="text-sm">
        <span className="flex items-center gap-1.5 font-medium">
          <BookOpen size={14} className="text-muted-foreground" /> Dictionary
        </span>
        <span className="block text-xs text-muted-foreground">
          {status.available
            ? "Look key terms up in the dictionary service: its senses become question options and evidence for the translator."
            : status.reason}
        </span>
      </span>
    </label>
  );
}

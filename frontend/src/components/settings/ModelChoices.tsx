"use client";

import { BookOpen, Eye, Lightbulb, RotateCcw, TriangleAlert } from "lucide-react";
import { cn } from "cn";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import type {
  AppSettingsView,
  DictionaryStatus,
  Effort,
  ModelChoices,
  ModelInfo,
  SecondReaderStatus,
  StepChoice,
  StepId,
} from "@/lib/types";
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
    const first = models?.find((m) => m.id === ids[0])?.label ?? ids[0];
    const label =
      ids.length > 1 ? `${first} + ${ids.length - 1} more` : `${model?.label ?? ids[0]}${levels.length ? ` · ${levels.join(" / ")}` : ""}`;
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
  disabled = false,
  placeholder,
}: {
  value: string | "mixed";
  models: ModelInfo[];
  visionOnly: boolean;
  onChange: (id: string) => void;
  label: string;
  className?: string;
  size?: "sm" | "default";
  disabled?: boolean;
  placeholder?: string; // shown with no model chosen ("Set all…")
}) {
  const current = models.find((m) => m.id === value);
  return (
    <Select value={value === "mixed" ? "" : value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger aria-label={label} size={size} className={cn("min-w-0 bg-card", className)}>
        <SelectValue placeholder={placeholder ?? (value === "mixed" ? "Mixed" : `Unavailable: ${value}`)}>
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

/** The level as a compact dropdown (the list in Settings): Default (and what it stands for), or a level to pin. */
export function EffortSelect({
  value,
  model,
  fallback,
  onChange,
  label,
  disabled = false,
}: {
  value: Effort | null;
  model: ModelInfo | undefined;
  fallback: { effort: Effort; from: string } | null; // what Default stands for
  onChange: (e: Effort | null) => void;
  label: string;
  disabled?: boolean;
}) {
  if (!model?.thinking) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="flex h-8 w-32 shrink-0 items-center px-2.5 text-xs text-muted-foreground" tabIndex={0}>
            No levels
          </span>
        </TooltipTrigger>
        <TooltipContent>This model doesn&apos;t reason, so it has no reasoning level.</TooltipContent>
      </Tooltip>
    );
  }
  const DEFAULT = "default";
  return (
    <Select value={value ?? DEFAULT} onValueChange={(v) => onChange(v === DEFAULT ? null : (v as Effort))} disabled={disabled}>
      <SelectTrigger size="sm" aria-label={label} className="h-8 w-32 shrink-0 bg-card">
        <SelectValue>
          {value ? (
            EFFORT_LABEL[value]
          ) : (
            <span>
              {fallback ? EFFORT_LABEL[fallback.effort] : "Default"} <span className="text-muted-foreground">· default</span>
            </span>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={DEFAULT}>
          <span>
            <span className="block">Default{fallback ? ` (${EFFORT_LABEL[fallback.effort]})` : ""}</span>
            {fallback && <span className="block text-xs text-muted-foreground">from {fallback.from}</span>}
          </span>
        </SelectItem>
        {EFFORTS.map((e) => (
          <SelectItem key={e} value={e}>
            <span>
              <span className="block">{EFFORT_LABEL[e]}</span>
              <span className="block text-xs text-muted-foreground">{EFFORT_HELP[e]}</span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// --------------------------------------------------------------------------- //
// The editor: one list, in sections as the pipeline runs, one row per step
// --------------------------------------------------------------------------- //

/** What's wrong with the choices as they stand (shown on the step's row while choosing): the readers and their
 * judge should be different models, and so should the reviewer and the translator. */
function rowWarnings(c: ModelChoices, secondOn: boolean): Partial<Record<StepId, string>> {
  const out: Partial<Record<StepId, string>> = {};
  if (secondOn && c.ocr_second && c.ocr_second.model === c.ocr?.model)
    out.ocr_second = "The same model as the first reading: the two would tend to misread alike. Pick another company's.";
  if (c.ocr_check && (c.ocr_check.model === c.ocr?.model || (secondOn && c.ocr_check.model === c.ocr_second?.model)))
    out.ocr_check = "One of the readers: it would tend to side with its own reading. Pick a third model.";
  if (c.review && c.review.model === c.translate?.model)
    out.review = "The same model as Translation: a different one catches more.";
  return out;
}

/** The second reading's switch, as its row needs it. */
export type SecondSwitch = { status: SecondReaderStatus; on: boolean; onChange: (on: boolean) => void };

/** Models (and reasoning levels) step by step, in sections as the pipeline runs: each step's name and what it does,
 * its model and level, and a reset when it differs from `base` (pipeline.yaml in Settings, the app's defaults for
 * one document). "Set all" gives a section one model (not Reading: its readers and judge are meant to differ).
 * `second`: the second reading's switch, on its row. */
export function ModelChoicesEditor({
  value,
  onChange,
  models,
  settings,
  base,
  baseLabel,
  second,
}: {
  value: ModelChoices;
  onChange: (next: ModelChoices) => void;
  models: ModelInfo[];
  settings: AppSettingsView;
  base: ModelChoices;
  baseLabel: string;
  second?: SecondSwitch;
}) {
  const byId = useMemo(() => new Map(models.map((m) => [m.id, m])), [models]);
  const info = useMemo(() => new Map(settings.steps.map((s) => [s.step, s])), [settings.steps]);
  const set = (steps: StepId[], update: (old: StepChoice) => StepChoice) => {
    const next = { ...value };
    for (const s of steps) next[s] = update(value[s]);
    onChange(next);
  };
  // A model that doesn't think has no level; a thinking one keeps the level it had (or follows the default).
  const pickModel = (steps: StepId[], id: string) =>
    set(steps, (old) => ({ model: id, effort: byId.get(id)?.thinking && byId.get(old.model)?.thinking ? old.effort : null }));
  const secondOn = second ? second.on && second.status.available : true;
  const warnings = rowWarnings(value, secondOn);

  const row = (step: StepId) => {
    const choice = value[step];
    if (!choice) return null;
    const s = info.get(step);
    const model = byId.get(choice.model);
    const changed = !sameChoice(choice, base[step]);
    const off = step === "ocr_second" && !!second && !secondOn;
    const label = s?.label ?? step;
    return (
      <div key={step} className="flex items-center gap-3 px-3 py-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-sm font-medium">
            {label}
            {changed && <span className="size-1.5 rounded-full bg-primary" title={`Changed from ${baseLabel}`} />}
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {step === "ocr_second" && second && !second.status.available
              ? second.status.reason
              : off
                ? "Off: each page is read once, then checked"
                : s?.help}
          </p>
          {!off && warnings[step] && (
            <p className="mt-1 flex items-start gap-1.5 text-xs text-warn-fg">
              <TriangleAlert size={12} className="mt-0.5 shrink-0" /> {warnings[step]}
            </p>
          )}
        </div>
        {step === "ocr_second" && second && (
          <Switch
            checked={secondOn}
            disabled={!second.status.available}
            onCheckedChange={second.onChange}
            aria-label="Second reading on"
            className="shrink-0"
          />
        )}
        <ModelSelect
          value={choice.model}
          models={models}
          visionOnly={!!s?.vision}
          onChange={(id) => pickModel([step], id)}
          label={`${label} model`}
          className="h-8 w-56 shrink-0"
          size="sm"
          disabled={off}
        />
        <EffortSelect
          value={choice.effort}
          model={model}
          fallback={defaultEffort(settings, models, step, choice.model)}
          onChange={(effort) => set([step], (old) => ({ ...old, effort }))}
          label={`${label} reasoning level`}
          disabled={off}
        />
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={() => base[step] && set([step], () => base[step])}
              disabled={!changed}
              className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:invisible"
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
    <div className="space-y-5">
      {settings.groups.map((g) => (
        <section key={g.id} aria-label={g.label}>
          <div className="mb-1.5 flex items-end justify-between gap-3 px-1">
            <div className="min-w-0">
              <h3 className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">{g.label}</h3>
              {g.help && <p className="text-xs text-muted-foreground">{g.help}</p>}
            </div>
            {!g.distinct && g.steps.length > 1 && (
              <ModelSelect
                value="mixed"
                placeholder="Set all…"
                models={models}
                visionOnly={g.vision}
                onChange={(id) => pickModel(g.steps, id)}
                label={`One model for every ${g.label} step`}
                className="h-7 w-auto shrink-0 gap-1 border-0 bg-transparent px-2 text-xs text-primary shadow-none hover:bg-accent"
                size="sm"
              />
            )}
          </div>
          <div className="divide-y divide-border rounded-lg border border-border bg-card shadow-xs">{g.steps.map(row)}</div>
        </section>
      ))}
    </div>
  );
}

/** The pipeline as a diagram, for its own tab: click a step to change its model (the same choices as the list). */
export function PipelineEditor({
  value,
  onChange,
  models,
  settings,
  base,
  off = [],
}: {
  value: ModelChoices;
  onChange: (next: ModelChoices) => void;
  models: ModelInfo[];
  settings: AppSettingsView;
  base: ModelChoices;
  off?: StepId[]; // steps switched off (the second reading)
}) {
  const [pulse, setPulse] = useState<{ steps: StepId[]; at: number } | null>(null);
  const changed = new Set((Object.keys(value) as StepId[]).filter((s) => !sameChoice(value[s], base[s])));
  return (
    <PipelineFlow
      spec={settings.flow}
      choices={value}
      models={models}
      settings={settings}
      highlight={null}
      changed={changed}
      pulse={pulse}
      off={off}
      onChange={(step, choice) => {
        onChange({ ...value, [step]: choice });
        setPulse((p) => ({ steps: [step], at: (p?.at ?? 0) + 1 }));
      }}
    />
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

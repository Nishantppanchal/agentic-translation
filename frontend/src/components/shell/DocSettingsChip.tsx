"use client";

import { BookOpen, Brain, ChevronDown } from "lucide-react";
import { cn } from "cn";
import { useState } from "react";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { api } from "@/lib/api";
import type { DocSettings } from "@/lib/types";
import { ChoicesDialog } from "../settings/ChoicesDialog";
import { changedSteps, choiceLabel, groupChoice, groupSummaries, useModelCatalog } from "../settings/ModelChoices";
import { ModelLogo } from "../settings/ModelLogo";

/** The document's models: its translation model on the chip (logo, name, reasoning level), every group and the
 * dictionary on hover; a click changes them for its next run. */
export function DocSettingsChip({
  sessionId,
  settings,
  busy,
  onSaved,
}: {
  sessionId: string;
  settings: DocSettings;
  busy: boolean; // the agents are working on it: changes wait
  onSaved: () => void;
}) {
  const catalog = useModelCatalog();
  const [open, setOpen] = useState(false);
  const app = catalog.settings;
  const translating = app?.groups.find((g) => g.id === "translating");
  const choice = translating ? groupChoice(settings.models, translating.steps) : settings.models.translate;
  const model = choice && choice !== "mixed" ? catalog.models?.find((m) => m.id === choice.model) : undefined;
  const main = choice ? choiceLabel(choice, catalog.models, app, translating?.steps[0] ?? "translate") : "";
  const dict = settings.dictionary.enabled;
  // (a document view from before the second reading has no status: shown as off)
  const second = settings.second_reader ?? { available: false, enabled: false, reason: null, warnings: [] };
  const twice = second.enabled;

  return (
    <>
      <HoverCard openDelay={250} closeDelay={80}>
        <HoverCardTrigger asChild>
          <button
            onClick={() => setOpen(true)}
            className="flex h-7 items-center gap-1.5 rounded-full border border-border bg-card px-2.5 text-xs text-muted-foreground shadow-xs transition-colors hover:border-primary/40 hover:text-foreground"
            aria-label={`Models for this document: ${main}. Dictionary ${dict ? "on" : "off"}. Change`}
          >
            {model ? <ModelLogo model={model} size={13} /> : <Brain size={13} className="shrink-0" />}
            <span className="hidden max-w-44 truncate text-foreground lg:inline">{main}</span>
            <BookOpen size={12} className={cn(dict && settings.dictionary.available ? "text-primary" : "opacity-40")} />
            <ChevronDown size={12} className="opacity-60" />
          </button>
        </HoverCardTrigger>
        {app && (
          <HoverCardContent align="end" className="w-80 p-3">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-medium">
              <Brain size={13} className="text-muted-foreground" /> This document&apos;s models
            </div>
            <div className="space-y-1.5">
              {groupSummaries(settings.models, app, catalog.models).map(({ group, choice: c, model: m, label }) => (
                <div key={group.id} className="flex items-center justify-between gap-3 text-xs">
                  <span className="text-muted-foreground">{group.label}</span>
                  <span className="flex min-w-0 items-center gap-1.5">
                    {m ? <ModelLogo model={m} size={12} /> : <Brain size={12} className="shrink-0 text-muted-foreground" />}
                    <span className="truncate">{c === "mixed" ? label : choiceLabel(c, catalog.models, app, group.steps[0], { showDefault: true })}</span>
                  </span>
                </div>
              ))}
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="text-muted-foreground">Second reading of scans</span>
                <span>{second.available ? (twice ? "on" : "off") : "off"}</span>
              </div>
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="text-muted-foreground">Dictionary</span>
                <span>{settings.dictionary.available ? (dict ? "on" : "off") : "not set up"}</span>
              </div>
            </div>
            <div className="mt-2.5 border-t border-border pt-2 text-[11px] text-muted-foreground">
              Click to change. Applies from the next run{busy ? ", once the agents finish" : ""}.
            </div>
          </HoverCardContent>
        )}
      </HoverCard>
      {catalog.models && app && (
        <ChoicesDialog
          open={open}
          onClose={() => setOpen(false)}
          title="Models for this document"
          note="Changes apply from this document's next run (a chat message, a task, a retry). Other documents keep theirs."
          models={catalog.models}
          settings={app}
          value={{ models: settings.models, dictionary: dict, second: twice }}
          dictionary={settings.dictionary}
          second={second}
          saveLabel="Save"
          disabledReason={busy ? "Wait for the agents to finish." : null}
          onSave={async (v) => {
            await api.patchSessionSettings(sessionId, {
              models: changedSteps(v.models, settings.models),
              ...(v.dictionary !== dict && settings.dictionary.available ? { dictionary: v.dictionary } : {}),
              ...(v.second !== twice && second.available ? { second_reader: v.second } : {}),
            });
            onSaved();
          }}
        />
      )}
    </>
  );
}

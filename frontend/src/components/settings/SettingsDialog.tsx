"use client";

import { BookOpen, Brain, Loader2, Palette, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import type { AppSettingsView, ModelChoices, ModelInfo, StepChoice, StepId } from "@/lib/types";
import { Modal } from "./Modal";
import { DictionarySwitch, ModelChoicesEditor, sameChoice, useModelCatalog } from "./ModelChoices";
import { ThemeControl } from "./ThemeControl";

/** App settings: the models and references new documents start with, the AI assist, and the theme. Closing with
 * unsaved changes asks first. */
export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [dirty, setDirty] = useState(false);
  const [asking, setAsking] = useState(false);
  const close = () => (dirty ? setAsking(true) : onClose());
  const done = () => {
    setAsking(false);
    setDirty(false);
    onClose();
  };
  return (
    <Modal open={open} onClose={close} title="Settings" description="Models, references, AI assist and appearance" width={1040}>
      <SettingsBody onDirty={setDirty} asking={asking} onKeep={() => setAsking(false)} onClose={done} />
    </Modal>
  );
}

function SettingsBody({
  onDirty,
  asking,
  onKeep,
  onClose,
}: {
  onDirty: (dirty: boolean) => void;
  asking: boolean;
  onKeep: () => void;
  onClose: () => void;
}) {
  const { models, settings, setSettings, error } = useModelCatalog();
  if (error) return <p className="text-sm text-del-fg">Couldn&apos;t load the settings: {error}</p>;
  if (!models || !settings)
    return (
      <div className="space-y-3">
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-52 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  return <SettingsForm models={models} settings={settings} onSaved={setSettings} onDirty={onDirty} asking={asking} onKeep={onKeep} onClose={onClose} />;
}

function SettingsForm({
  models,
  settings,
  onSaved,
  onDirty,
  asking,
  onKeep,
  onClose,
}: {
  models: ModelInfo[];
  settings: AppSettingsView;
  onSaved: (s: AppSettingsView) => void;
  onDirty: (dirty: boolean) => void;
  asking: boolean;
  onKeep: () => void;
  onClose: () => void;
}) {
  const [choices, setChoices] = useState<ModelChoices>(settings.models);
  const [dictionary, setDictionary] = useState(settings.dictionary.enabled);
  const [assist, setAssist] = useState(settings.assist ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty =
    (Object.keys(choices) as StepId[]).some((s) => !sameChoice(choices[s], settings.models[s])) ||
    dictionary !== settings.dictionary.enabled ||
    assist !== (settings.assist ?? true);
  const change = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    onDirty(true);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      // A step left at pipeline.yaml's choice is stored as "no override".
      const body = Object.fromEntries(
        (Object.keys(choices) as StepId[]).map((s) => [s, sameChoice(choices[s], settings.configured[s]) ? null : choices[s]]),
      ) as Record<StepId, StepChoice | null>;
      onSaved(
        await api.putSettings({
          models: body,
          ...(settings.dictionary.available ? { dictionary } : {}),
          ...(assist !== (settings.assist ?? true) ? { assist } : {}),
        }),
      );
      onDirty(false);
      toast.success("Settings saved", { description: "New documents use them; each document keeps its own choice." });
    } catch (e) {
      setError(String(e).replace(/^Error: /, ""));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-col">
      <Tabs defaultValue="models" className="gap-4">
        <TabsList>
          <TabsTrigger value="models">
            <Brain /> Models
          </TabsTrigger>
          <TabsTrigger value="references">
            <BookOpen /> References
          </TabsTrigger>
          <TabsTrigger value="assist">
            <Sparkles /> AI assist
          </TabsTrigger>
          <TabsTrigger value="appearance">
            <Palette /> Appearance
          </TabsTrigger>
        </TabsList>
        <TabsContent value="models" className="space-y-2">
          <p className="text-sm text-muted-foreground">
            The models new documents start with. Each document keeps its own choice (change it from the document&apos;s header, or the
            chat model from the chat box). Hover a row to see the steps it changes; click a step to change only that one.
          </p>
          <ModelChoicesEditor
            value={choices}
            onChange={change(setChoices)}
            models={models}
            settings={settings}
            base={settings.configured}
            baseLabel="the default"
          />
        </TabsContent>
        <TabsContent value="references" className="space-y-4">
          <DictionarySwitch status={settings.dictionary} on={dictionary} onChange={change(setDictionary)} />
          <p className="text-xs text-muted-foreground">
            Precedence when they disagree: the project termbase, then your answers, then the translation memory, then the dictionary,
            then the AI&apos;s own choice. A dictionary that disagrees with the AI becomes a question for you.
          </p>
        </TabsContent>
        <TabsContent value="assist" className="space-y-4">
          <label className="flex items-start gap-3">
            <Switch checked={assist} onCheckedChange={change(setAssist)} className="mt-0.5" />
            <span className="text-sm">
              <span className="font-medium">Suggestions in the chat</span>
              <span className="block text-xs text-muted-foreground">
                Suggested next prompts after each answer, and Tab to complete what you&apos;re typing. Each uses a small call to the
                Assist model (Models tab).
              </span>
            </span>
          </label>
        </TabsContent>
        <TabsContent value="appearance" className="space-y-2">
          <p className="text-sm text-muted-foreground">System follows your computer&apos;s light or dark setting.</p>
          <ThemeControl />
        </TabsContent>
      </Tabs>

      <div className="sticky -bottom-4 -mx-5 -mb-4 mt-5 flex items-center gap-2 border-t border-border bg-card/95 px-5 py-3 backdrop-blur">
        {asking ? (
          <>
            <span className="mr-auto text-sm">Discard your unsaved changes?</span>
            <Button variant="ghost" size="sm" onClick={onKeep}>
              Keep editing
            </Button>
            <Button variant="destructive" size="sm" onClick={onClose}>
              Discard
            </Button>
          </>
        ) : (
          <>
            <span className="mr-auto flex items-center gap-1.5 text-xs text-muted-foreground">
              {error ? (
                <span className="text-del-fg">{error}</span>
              ) : dirty ? (
                <>
                  <span className="size-1.5 rounded-full bg-primary" /> Unsaved changes
                </>
              ) : null}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setChoices(settings.configured);
                onDirty(true);
              }}
              title="Back to config/pipeline.yaml's models"
            >
              Reset to default
            </Button>
            <Button variant="outline" size="sm" onClick={onClose}>
              {dirty ? "Cancel" : "Close"}
            </Button>
            <Button size="sm" onClick={save} disabled={busy || !dirty}>
              {busy && <Loader2 className="animate-spin" />} Save
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

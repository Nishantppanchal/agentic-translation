"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { AppSettingsView, DictionaryStatus, ModelChoices, ModelInfo } from "@/lib/types";
import { Modal } from "./Modal";
import { DictionarySwitch, ModelChoicesEditor } from "./ModelChoices";

/** One document's models and dictionary: before uploading it, or for its next run. Changes are compared with (and
 * reset to) the app's defaults from Settings. */
export function ChoicesDialog({
  open,
  onClose,
  title,
  note,
  models,
  settings,
  value,
  dictionary,
  saveLabel,
  onSave,
  disabledReason,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  note: string;
  models: ModelInfo[];
  settings: AppSettingsView;
  value: { models: ModelChoices; dictionary: boolean };
  dictionary: DictionaryStatus;
  saveLabel: string;
  onSave: (v: { models: ModelChoices; dictionary: boolean }) => Promise<void> | void;
  disabledReason?: string | null; // e.g. while the agents are working on the document
}) {
  return (
    <Modal open={open} onClose={onClose} title={title} description={note} width={1040}>
      <ChoicesForm
        key={JSON.stringify(value)} // a fresh draft each time it opens with other values
        note={note}
        models={models}
        settings={settings}
        value={value}
        dictionary={dictionary}
        saveLabel={saveLabel}
        onSave={onSave}
        onClose={onClose}
        disabledReason={disabledReason}
      />
    </Modal>
  );
}

function ChoicesForm({
  note,
  models,
  settings,
  value,
  dictionary,
  saveLabel,
  onSave,
  onClose,
  disabledReason,
}: {
  note: string;
  models: ModelInfo[];
  settings: AppSettingsView;
  value: { models: ModelChoices; dictionary: boolean };
  dictionary: DictionaryStatus;
  saveLabel: string;
  onSave: (v: { models: ModelChoices; dictionary: boolean }) => Promise<void> | void;
  onClose: () => void;
  disabledReason?: string | null;
}) {
  const [choices, setChoices] = useState(value.models);
  const [dict, setDict] = useState(value.dictionary);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave({ models: choices, dictionary: dict });
      onClose();
    } catch (e) {
      setError(String(e).replace(/^Error: /, ""));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex min-h-0 flex-col gap-4">
      <p className="text-sm text-muted-foreground">{note}</p>
      <ModelChoicesEditor value={choices} onChange={setChoices} models={models} settings={settings} base={settings.models} baseLabel="the defaults in Settings" />
      <DictionarySwitch status={dictionary} on={dict} onChange={setDict} />
      <div className="sticky -bottom-4 -mx-5 -mb-4 flex items-center gap-2 border-t border-border bg-card/95 px-5 py-3 backdrop-blur">
        <span className="mr-auto text-xs">
          {error ? <span className="text-del-fg">{error}</span> : disabledReason ? <span className="text-warn-fg">{disabledReason}</span> : null}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setChoices(settings.models);
            setDict(settings.dictionary.enabled);
          }}
          title="The defaults new documents use (Settings)"
        >
          Use the defaults
        </Button>
        <Button variant="outline" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button size="sm" onClick={save} disabled={busy || !!disabledReason}>
          {busy && <Loader2 className="animate-spin" />} {saveLabel}
        </Button>
      </div>
    </div>
  );
}

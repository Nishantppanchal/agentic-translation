"use client";

import { HelpCircle, Loader2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { Answer, Question, Segment } from "@/lib/types";
import { answerFor, type Choice, isRecommended, recommendedChoice, TermChoice } from "./TermChoice";

/** Shown while the pipeline is paused: decide every term at once (recommendations preselected), then resume. */
export function ClarifyForm({
  questions,
  segments,
  onSubmit,
  onJump,
}: {
  questions: Question[];
  segments: Map<string, Segment>;
  onSubmit: (answers: Record<string, Answer | null>) => Promise<void>;
  onJump: (segmentId: string) => void;
}) {
  const [choices, setChoices] = useState<Record<string, Choice>>(() =>
    Object.fromEntries(questions.map((q) => [q.id, recommendedChoice(q)])),
  );
  const [busy, setBusy] = useState(false);
  const choiceOf = (q: Question) => choices[q.id] ?? recommendedChoice(q);
  const changed = questions.filter((q) => !isRecommended(q, choiceOf(q))).length;
  const beforeTranslating = questions.some((q) => q.origin === "analysis");

  const submit = async (skipAll: boolean) => {
    setBusy(true);
    try {
      await onSubmit(Object.fromEntries(questions.map((q) => [q.id, skipAll ? null : answerFor(q, choiceOf(q))])));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-warn-fg/25 bg-warn/45 p-4 text-sm">
      <div className="flex items-center gap-2 font-medium text-warn-fg">
        <HelpCircle size={16} />
        {questions.length} term{questions.length === 1 ? "" : "s"} to decide {beforeTranslating ? "before I translate" : "before the review"}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Each term is explained in plain English, with the sentence it appears in. My recommendation is preselected — if
        you&apos;re not sure, just continue. Terms you choose yourself become approved project terms; recommendations you
        just accept are saved as <i>proposed</i> (a suggestion for later documents, which you can approve in the termbase).
      </p>
      <div className="mt-3 space-y-3">
        {questions.map((q) => (
          <TermChoice
            key={q.id}
            question={q}
            segments={segments}
            choice={choiceOf(q)}
            onChange={(c) => setChoices((all) => ({ ...all, [q.id]: c }))}
            onJump={onJump}
            disabled={busy}
          />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => submit(true)} disabled={busy} title="Don't record any decision; the AI keeps its guesses">
          Skip — let the AI decide
        </Button>
        <Button size="sm" onClick={() => submit(false)} disabled={busy}>
          {busy && <Loader2 className="animate-spin" />}
          {changed === 0 ? "Accept all recommendations & continue" : `Continue with my ${changed} change${changed === 1 ? "" : "s"}`}
        </Button>
      </div>
    </div>
  );
}

"use client";

import { Check, HelpCircle, X } from "lucide-react";
import { useState } from "react";
import type { Answer, Question, Segment } from "@/lib/types";
import { answerFor, recommendedChoice, TermChoice } from "./TermChoice";

/** A term raised after the pipeline (by the reviewer or in chat): answering asks the editor to apply it. */
export function QuestionCard({
  question,
  segments,
  disabled,
  onAnswer,
  onJump,
}: {
  question: Question;
  segments: Map<string, Segment>;
  disabled: boolean;
  onAnswer: (answer: Answer | null) => void;
  onJump: (segmentId: string) => void;
}) {
  const [choice, setChoice] = useState(() => recommendedChoice(question));
  const answer = answerFor(question, choice);

  return (
    <div className="rounded-xl border border-warn-fg/30 bg-warn/60 p-3 text-sm">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium">
        <HelpCircle size={14} className="text-warn-fg" />
        How should this term be translated?
      </div>
      <TermChoice question={question} segments={segments} choice={choice} onChange={setChoice} onJump={onJump} disabled={disabled} />
      <div className="mt-2 flex justify-end gap-1.5">
        <button
          type="button"
          disabled={disabled}
          onClick={() => onAnswer(null)}
          className="flex items-center gap-1 rounded-md border border-border bg-panel px-2 py-1 text-xs text-muted hover:text-fg disabled:opacity-40"
          title="Keep the current translation"
        >
          <X size={13} /> Keep current
        </button>
        <button
          type="button"
          disabled={disabled || !answer}
          onClick={() => answer && onAnswer(answer)}
          className="flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-xs text-white disabled:opacity-40"
          title="The agent proposes the changes for you to accept"
        >
          <Check size={13} /> Apply
        </button>
      </div>
    </div>
  );
}

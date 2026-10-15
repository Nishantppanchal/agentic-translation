"use client";

import { Check, HelpCircle, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
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
    <div className="rounded-xl border border-warn-fg/25 bg-warn/50 p-3 text-sm">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-warn-fg">
        <HelpCircle size={14} />
        How should this term be translated?
      </div>
      <TermChoice question={question} segments={segments} choice={choice} onChange={setChoice} onJump={onJump} disabled={disabled} />
      <div className="mt-2.5 flex justify-end gap-1.5">
        <Button variant="ghost" size="sm" disabled={disabled} onClick={() => onAnswer(null)} title="Keep the current translation">
          <X /> Keep current
        </Button>
        <Button size="sm" disabled={disabled || !answer} onClick={() => answer && onAnswer(answer)} title="The agent proposes the changes for you to accept">
          <Check /> Apply
        </Button>
      </div>
    </div>
  );
}

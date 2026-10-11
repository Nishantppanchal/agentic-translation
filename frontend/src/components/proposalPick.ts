"use client";

import { useMemo, useState } from "react";
import type { Proposal, ProposalChange } from "@/lib/types";

export const changeKey = (c: { segment_id: string; field: string }) => `${c.segment_id}|${c.field}`;

/**
 * What the person decided about a pending proposal: which changes are left out and which alternative
 * is picked. Shared by the chat card and the segment grid, so a decision in one shows in the other.
 * Only exclusions are stored, so changes added later in the conversation default to included.
 */
export interface ProposalPick {
  excluded: Set<string>;
  choices: Record<string, number>;
  include: (key: string, included: boolean) => void;
  choose: (key: string, index: number) => void;
  /** Arguments for accept: null = everything, the first alternative each. */
  acceptArgs: (changes: ProposalChange[]) => [string[] | null, Record<string, number> | null];
}

export function useProposalPick(proposal: Proposal | null): ProposalPick {
  const [state, setState] = useState<{ id: string | null; excluded: Set<string>; choices: Record<string, number> }>({
    id: null,
    excluded: new Set(),
    choices: {},
  });
  const id = proposal?.id ?? null;
  return useMemo(() => {
    // A new proposal starts with everything included.
    const fresh = () => ({ id, excluded: new Set<string>(), choices: {} as Record<string, number> });
    const current = state.id === id ? state : fresh();
    return {
      excluded: current.excluded,
      choices: current.choices,
      include: (key, included) =>
        setState((s) => {
          const base = s.id === id ? s : fresh();
          const excluded = new Set(base.excluded);
          if (included) excluded.delete(key);
          else excluded.add(key);
          return { ...base, excluded };
        }),
      choose: (key, index) =>
        setState((s) => {
          const base = s.id === id ? s : fresh();
          return { ...base, choices: { ...base.choices, [key]: index } };
        }),
      acceptArgs: (changes) => [
        current.excluded.size ? changes.filter((c) => !current.excluded.has(changeKey(c))).map(changeKey) : null,
        Object.keys(current.choices).length ? current.choices : null,
      ],
    };
  }, [state, id]);
}

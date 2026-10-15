import type { TaskKind } from "./types";

/** One-click rewrite requests for one or more segments (the agent's result comes back as a proposal to accept
 * or reject). Used by the grid's selection bar, the Rewrite ▾ menus and the selection toolbar. */
export interface RewritePreset {
  label: string;
  kind: TaskKind;
  instruction: string;
  n: number;
  hint: string;
}

export const REWRITES: RewritePreset[] = [
  { label: "More formal", kind: "retranslate", instruction: "More formal register.", n: 1, hint: "A more formal register" },
  { label: "Simpler", kind: "retranslate", instruction: "Simpler, plain language for non-experts.", n: 1, hint: "Plain language for non-experts" },
  {
    label: "Shorter",
    kind: "retranslate",
    instruction: "More concise: as short as possible without losing meaning.",
    n: 1,
    hint: "As short as possible without losing meaning",
  },
  { label: "3 alternatives", kind: "alternatives", instruction: "", n: 3, hint: "Three different ways to say it; you pick one" },
];

"use client";

import { useEffect, useState } from "react";
import { assistApi, type AssistSuggestion } from "@/lib/api";

/** Suggested next prompts for a ready document. `nonce` ≥ 0 while it's idle and ready (the timeline's length, so a
 * finished run asks again); -1 otherwise. Any failure, the switch off in Settings, or a model error mean none. */
export function useSuggestions(sessionId: string, nonce: number, enabled: boolean): AssistSuggestion[] {
  const [found, setFound] = useState<{ key: string; list: AssistSuggestion[] } | null>(null);
  const key = `${sessionId}:${nonce}`;
  useEffect(() => {
    if (nonce < 0 || !enabled) return;
    const ctrl = new AbortController();
    assistApi
      .suggestions(sessionId, ctrl.signal)
      .then((r) => setFound({ key, list: r.disabled || r.error ? [] : (r.suggestions ?? []).filter((s) => s.label && s.prompt).slice(0, 3) }))
      .catch(() => {});
    return () => ctrl.abort();
  }, [sessionId, nonce, enabled, key]);
  return enabled && found?.key === key ? found.list : [];
}

/** A completion of what's being typed, as ghost text: asked for after a 400 ms pause with ≥ 4 characters, the
 * caret at the end and no composition in progress; typing again cancels the request. Only a completion of exactly
 * the current text is returned. Answers are kept per document, by text. */
export function useCompletion(sessionId: string, text: string, active: boolean): string {
  const [cache, setCache] = useState<{ sessionId: string; byText: Map<string, string> }>({ sessionId, byText: new Map() });
  const known = cache.sessionId === sessionId ? cache.byText.get(text) : undefined;
  const wanted = active && text.trim().length >= 4;
  useEffect(() => {
    if (!wanted || known !== undefined) return;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      assistApi
        .complete(sessionId, text, ctrl.signal)
        .then((r) => {
          setCache((c) => {
            const byText = new Map(c.sessionId === sessionId ? c.byText : []);
            byText.set(text, r.completion ?? "");
            if (byText.size > 200) byText.delete(byText.keys().next().value as string);
            return { sessionId, byText };
          });
        })
        .catch(() => {});
    }, 400);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [sessionId, text, wanted, known]);
  return wanted && known ? joinCompletion(text, known) : "";
}

/** The completion as it goes after the text — exactly as the server sent it (a leading space starts a new word;
 * none finishes the word being typed), without doubling a space the text already ends with. */
export function joinCompletion(text: string, completion: string): string {
  if (!completion.trim()) return "";
  return /\s$/.test(text) ? completion.replace(/^\s+/, "") : completion;
}

"use client";

import { BookMarked, BookOpen, ChevronRight, Database, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { LookupItem } from "@/lib/types";
import { Markdown } from "../document/Markdown";

const SOURCE = {
  dictionary: { label: "Dictionary", Icon: BookOpen },
  tm: { label: "Translation memory", Icon: Database },
  termbase: { label: "Termbase", Icon: BookMarked },
} as const;

/** One line for a lookup: what was looked up and the gist of the answer. */
export function lookupLabel(it: LookupItem): string {
  const { label } = SOURCE[it.source] ?? SOURCE.dictionary;
  if (it.status === "pending") return `${label}: ${it.purpose}…`;
  if (it.via === "pipeline") return it.text ?? `${label}: ${it.hits} of ${it.queries} found`;
  const first = it.results[0];
  if (it.status !== "done") return `${label}: ${it.note ?? it.status}`;
  if (!first?.entries.length) return `${label}: nothing for “${first?.query ?? ""}”`;
  const more = first.entries.length > 1 ? ` (+${first.entries.length - 1})` : "";
  return `${label}: “${first.query}” → ${first.entries[0].target}${more}`;
}

/** A lookup in the run log, with what it found (open it to see each entry and where it comes from). */
export function LookupRow({ item }: { item: LookupItem }) {
  const { Icon } = SOURCE[item.source] ?? SOURCE.dictionary;
  const found = item.results.filter((r) => r.entries.length);
  const head = (
    <>
      {item.status === "pending" ? <Loader2 size={13} className="shrink-0 animate-spin text-primary" /> : <Icon size={13} className="shrink-0" />}
      <span className="min-w-0 truncate">{lookupLabel(item)}</span>
    </>
  );
  if (!found.length) return <div className="flex items-center gap-1.5">{head}</div>;
  return (
    <Collapsible>
      <CollapsibleTrigger className="group/lookup flex max-w-full items-center gap-1.5 rounded-sm text-left transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50">
        {head}
        <ChevronRight size={13} className="shrink-0 transition-transform group-data-[state=open]/lookup:rotate-90" />
      </CollapsibleTrigger>
      <CollapsibleContent className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden">
        <div className="mt-1 mb-1.5 ml-5 space-y-2 rounded-lg border border-border bg-card px-3 py-2 text-xs text-foreground shadow-xs">
          {found.map((r, i) => (
            <div key={i}>
              <div className="flex items-baseline gap-2">
                <span className="font-medium">{r.query}</span>
                {r.outcome && (
                  <Badge variant="secondary" className="h-4 px-1.5 text-[10px] font-normal">
                    {r.outcome}
                  </Badge>
                )}
              </div>
              <ul className="mt-0.5 space-y-0.5 pl-3">
                {r.entries.map((e, k) => (
                  <li key={k} className="text-muted-foreground">
                    {e.score != null && <span className="mr-1 font-medium text-foreground tabular-nums">{e.score}%</span>}
                    {e.source_text && (
                      <>
                        <Markdown inline text={e.source_text} /> →{" "}
                      </>
                    )}
                    <span className="text-foreground">{e.target ? <Markdown inline text={e.target} /> : "—"}</span>
                    {e.detail && <span> · {e.detail}</span>}
                    {e.ref && <span className="text-[10px]"> · {e.ref}</span>}
                    {e.badge && (
                      <Badge variant="outline" className="ml-1 h-4 px-1 text-[10px] font-normal">
                        {e.badge}
                      </Badge>
                    )}
                    {!!e.forbidden?.length && <span className="text-del-fg"> · never: {e.forbidden.join(", ")}</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

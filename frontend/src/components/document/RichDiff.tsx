"use client";

import { diffChars, diffWordsWithSpace } from "diff";
import type { Element, ElementContent, Root, RootContent, Text } from "hast";
import { Code2 } from "lucide-react";
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified } from "unified";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { noSpaceScript } from "@/lib/terms";
import { DiffText } from "./Diff";
import { markdownCode } from "./Markdown";

const OBJECT = /\[\^(\d+)\]/g;
const prep = (md: string) => md.replace(OBJECT, (_m, n) => `\`⦿${n}\``); // as Markdown.tsx shows them

type Parent = Root | Element;

/** The text of markdown as it renders (the same pipeline react-markdown runs), node by node in reading order. */
function renderedText(md: string): string {
  const processor = unified().use(remarkParse).use(remarkGfm).use(remarkRehype);
  const tree = processor.runSync(processor.parse(prep(md))) as Root;
  let out = "";
  const walk = (n: Parent) => {
    for (const c of n.children) {
      if (c.type === "text") out += c.value;
      else if (c.type === "element") walk(c);
    }
  };
  walk(tree);
  return out;
}

type Op = { at: number; kind: "ins"; end: number } | { at: number; kind: "del"; text: string };

/** A rehype plugin: on the "after" tree, wrap inserted text in <ins> and put deleted text back as <del>, at the
 * place it was — so the change reads in the rendered document (headings, lists, tables), not in markdown. */
function rehypeDiff(ops: Op[]) {
  return () => (tree: Root) => {
    let offset = 0;
    // Inside these only cells (and rows) may sit: their whitespace text is counted but never wrapped.
    const STRUCTURE = new Set(["table", "thead", "tbody", "tfoot", "tr", "ul", "ol"]);
    const visit = (parent: Parent) => {
      const next: (RootContent | ElementContent)[] = [];
      const bare = parent.type === "element" && STRUCTURE.has(parent.tagName);
      for (const child of parent.children) {
        if (child.type === "element") {
          visit(child);
          next.push(child);
          continue;
        }
        if (child.type !== "text") {
          next.push(child);
          continue;
        }
        const start = offset;
        const end = start + child.value.length;
        offset = end;
        if (bare) {
          next.push(child);
          continue;
        }
        const here = ops.filter((o) => (o.kind === "ins" ? o.at < end && o.end > start : o.at >= start && (o.at < end || o.at === end)));
        if (!here.length) {
          next.push(child);
          continue;
        }
        let pos = start;
        const text = (a: number, b: number): Text => ({ type: "text", value: child.value.slice(a - start, b - start) });
        for (const o of here.sort((a, b) => a.at - b.at || (a.kind === "del" ? -1 : 1))) {
          if (o.kind === "del") {
            if (o.at > pos) next.push(text(pos, o.at));
            pos = Math.max(pos, o.at);
            next.push({ type: "element", tagName: "del", properties: { className: ["diff-del"] }, children: [{ type: "text", value: o.text }] });
            o.at = Number.NaN; // placed once
          } else {
            const a = Math.max(o.at, start);
            const b = Math.min(o.end, end);
            if (a > pos) next.push(text(pos, a));
            next.push({ type: "element", tagName: "ins", properties: { className: ["diff-ins"] }, children: [text(a, b)] });
            pos = b;
          }
        }
        if (pos < end) next.push(text(pos, end));
      }
      parent.children = next as typeof parent.children;
    };
    visit(tree);
  };
}

/** Operations on the "after" text: [at, end) inserted, or `text` deleted at `at`. */
function diffOps(before: string, after: string): Op[] {
  const parts = noSpaceScript.test(after + before) ? diffChars(before, after) : diffWordsWithSpace(before, after);
  const ops: Op[] = [];
  let at = 0;
  for (const p of parts) {
    if (p.added) {
      ops.push({ at, kind: "ins", end: at + p.value.length });
      at += p.value.length;
    } else if (p.removed) {
      if (p.value.trim()) ops.push({ at, kind: "del", text: p.value });
    } else at += p.value.length;
  }
  return ops;
}

/** A change shown as the document reads: the new version rendered, with what was added and removed marked. Only
 * formatting changed: a note says so. The markdown toggle shows the raw diff (useful for OCR structure fixes). */
export function RichDiff({ before, after, className = "", toggle = true }: { before: string; after: string; className?: string; toggle?: boolean }) {
  const [raw, setRaw] = useState(false);
  const { ops, formatOnly } = useMemo(() => {
    const a = renderedText(before);
    const b = renderedText(after);
    return { ops: diffOps(a, b), formatOnly: a === b && before !== after };
  }, [before, after]);
  return (
    <div className={`group/diff relative ${className}`}>
      {toggle && (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={() => setRaw(!raw)}
              aria-pressed={raw}
              className={`absolute -top-1 right-0 z-10 rounded p-1 text-muted-foreground opacity-0 transition-opacity group-hover/diff:opacity-100 hover:text-foreground focus-visible:opacity-100 ${raw ? "opacity-100 text-primary" : ""}`}
              aria-label={raw ? "Show the change as it reads" : "Show the markdown"}
            >
              <Code2 size={13} />
            </button>
          </TooltipTrigger>
          <TooltipContent>{raw ? "Show it as it reads" : "Show the markdown"}</TooltipContent>
        </Tooltip>
      )}
      {raw ? (
        <DiffText before={before} after={after} className="font-mono text-xs" />
      ) : (
        <div className="prose-doc text-sm [&_.diff-del]:rounded-sm [&_.diff-del]:bg-del [&_.diff-del]:text-del-fg [&_.diff-ins]:rounded-sm [&_.diff-ins]:bg-ins [&_.diff-ins]:text-ins-fg [&_.diff-ins]:no-underline">
          {/* a new plugin per diff: react-markdown runs it on this text's own tree */}
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeDiff(ops.map((o) => ({ ...o })))]} components={{ code: markdownCode }}>
            {prep(after)}
          </ReactMarkdown>
          {formatOnly && <p className="mt-1 text-[11px] text-muted-foreground italic">Only the formatting changed (bold, headings, lists or table layout).</p>}
        </div>
      )}
    </div>
  );
}

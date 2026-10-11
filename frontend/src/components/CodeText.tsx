"use client";

import { type CodeNode, parseCodes, PLACEHOLDER_SYMBOL } from "@/lib/codes";

function spanClass(label: string): string {
  const l = label.toLowerCase();
  const out: string[] = [];
  if (l.includes("bold")) out.push("font-semibold");
  if (l.includes("italic")) out.push("italic");
  if (l.includes("underline")) out.push("underline");
  if (l.includes("strike")) out.push("line-through");
  if (l.includes("link")) out.push("text-accent underline");
  if (l.includes("superscript")) out.push("align-super text-[0.75em]");
  if (l.includes("subscript")) out.push("align-sub text-[0.75em]");
  if (!out.length) out.push("underline decoration-dotted decoration-muted underline-offset-2");
  return out.join(" ");
}

/**
 * Text with inline codes.
 * - mode "read": formatting shown as formatting (bold, italic, links), placeholders as small symbols.
 * - mode "tags": numbered tag pills, as translators know them from CAT tools (the grid's source column).
 */
export function CodeText({
  text,
  labels,
  mode = "read",
  renderText = (t) => t,
}: {
  text: string;
  labels?: Record<string, string>;
  mode?: "read" | "tags";
  renderText?: (text: string, key: string) => React.ReactNode;
}) {
  const render = (nodes: CodeNode[], path: string): React.ReactNode[] =>
    nodes.map((n, i) => {
      const key = `${path}.${i}`;
      if (n.kind === "text") return <span key={key}>{renderText(n.text, key)}</span>;
      const label = labels?.[n.id] ?? (n.kind === "g" ? "format" : "placeholder");
      if (n.kind === "x") {
        const symbol = PLACEHOLDER_SYMBOL[label] ?? "◆";
        return mode === "tags" ? (
          <span key={key} title={label} className="mx-px inline-flex items-center rounded bg-accent-soft px-1 align-baseline font-mono text-[10px] text-accent">
            {n.id}
            {symbol}
          </span>
        ) : (
          <span key={key} title={label} className="mx-0.5 text-[0.8em] text-muted">
            {label === "line break" ? <br /> : symbol}
          </span>
        );
      }
      return mode === "tags" ? (
        <span key={key} title={label}>
          <span className="mr-px rounded-l bg-accent-soft px-0.5 font-mono text-[10px] text-accent">{n.id}</span>
          <span className={spanClass(label)}>{render(n.children, key)}</span>
          <span className="ml-px rounded-r bg-accent-soft px-0.5 font-mono text-[10px] text-accent">{n.id}</span>
        </span>
      ) : (
        <span key={key} title={label} className={spanClass(label)}>
          {render(n.children, key)}
        </span>
      );
    });
  return <>{render(parseCodes(text), "c")}</>;
}

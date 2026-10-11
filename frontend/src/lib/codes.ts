/** Inline codes in Office/XLIFF segment text: `<g id="1">words</g>` spans and `<x id="2"/>` placeholders. */

export type CodeNode =
  | { kind: "text"; text: string }
  | { kind: "x"; id: string }
  | { kind: "g"; id: string; children: CodeNode[] };

const TOKEN = /<g\s+id\s*=\s*["']([^"']+)["']\s*>|<\/g\s*>|<x\s+id\s*=\s*["']([^"']+)["']\s*\/>/gi;

export const hasCodes = (text: string | null | undefined) => !!text && new RegExp(TOKEN.source, "i").test(text);

export function parseCodes(text: string): CodeNode[] {
  const root: { children: CodeNode[] } = { children: [] };
  const stack: { children: CodeNode[] }[] = [root];
  let pos = 0;
  for (const m of text.matchAll(TOKEN)) {
    const top = stack[stack.length - 1];
    if (m.index > pos) top.children.push({ kind: "text", text: text.slice(pos, m.index) });
    pos = m.index + m[0].length;
    if (m[1] !== undefined) {
      const g: CodeNode = { kind: "g", id: m[1], children: [] };
      top.children.push(g);
      stack.push(g);
    } else if (m[2] !== undefined) {
      top.children.push({ kind: "x", id: m[2] });
    } else if (stack.length > 1) {
      stack.pop();
    }
  }
  if (pos < text.length) stack[stack.length - 1].children.push({ kind: "text", text: text.slice(pos) });
  return root.children;
}

export const stripCodes = (text: string | null | undefined) => (text ?? "").replace(TOKEN, "");

/** Codes in the order they appear: [{id, kind}] — for the insert buttons. */
export function codeList(text: string): { id: string; kind: "g" | "x" }[] {
  const out: { id: string; kind: "g" | "x" }[] = [];
  for (const m of text.matchAll(TOKEN)) {
    if (m[1] !== undefined) out.push({ id: m[1], kind: "g" });
    else if (m[2] !== undefined) out.push({ id: m[2], kind: "x" });
  }
  return out;
}

export const PLACEHOLDER_SYMBOL: Record<string, string> = {
  tab: "⇥",
  "line break": "↵",
  "page break": "⤓",
  image: "▣",
  object: "◆",
  field: "ƒ",
  "field end": "ƒ",
  equation: "∑",
  "footnote mark": "¹",
  "footnote number": "¹",
  "endnote mark": "ⁱ",
  "endnote number": "ⁱ",
  symbol: "Ω",
  comment: "✎",
};

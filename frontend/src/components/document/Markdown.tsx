import { findAndReplace } from "mdast-util-find-and-replace";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Root } from "mdast";

const OBJECT = /\[\^(\d+)\]/g; // Word / PowerPoint: a footnote mark, a picture or a field in the sentence
const CHIP = "⦿"; // marks the inline code that stands for one of them

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Wrap each occurrence of the terms in <mark> (a remark plugin: text only, never inside code or link targets). */
function remarkHighlight(terms: string[]) {
  const clean = [...new Set(terms.map((t) => t.trim()).filter((t) => t.length > 0))].sort((a, b) => b.length - a.length);
  return () => (tree: Root) => {
    if (!clean.length) return;
    // Latin terms match whole words (any case); CJK terms anywhere.
    const rx = new RegExp(clean.map((t) => (/^[\p{Script=Latin}\d\s'’-]+$/u.test(t) ? `\\b${escape(t)}\\b` : escape(t))).join("|"), "giu");
    findAndReplace(tree, [rx, (value: string) => ({ type: "emphasis", data: { hName: "mark" }, children: [{ type: "text", value }] })]);
  };
}

/** Inline code; the `[^n]` objects of Word and PowerPoint text as small chips. */
export const markdownCode: Components["code"] = ({ children, ...props }) => {
  const content = String(children);
  if (content.startsWith(CHIP)) {
    return (
      <span
        className="mx-0.5 inline-block rounded bg-muted px-1 align-baseline font-mono text-[10px] text-muted-foreground"
        title="A footnote mark, picture or field in the original sentence: it stays where the translation puts it"
      >
        {content.slice(1)}
      </span>
    );
  }
  return <code {...props}>{children}</code>;
};

// Inline: blocks flattened into one run of text — headings and paragraphs become spans, list items get a bullet,
// table cells are joined with " · " and rows with " / " (for one-line context: question cards, proposals, lookups).
const INLINE: Components = {
  code: markdownCode,
  h1: ({ children }) => <strong>{children} </strong>,
  h2: ({ children }) => <strong>{children} </strong>,
  h3: ({ children }) => <strong>{children} </strong>,
  h4: ({ children }) => <strong>{children} </strong>,
  h5: ({ children }) => <strong>{children} </strong>,
  h6: ({ children }) => <strong>{children} </strong>,
  p: ({ children }) => <span>{children} </span>,
  ul: ({ children }) => <span>{children}</span>,
  ol: ({ children }) => <span>{children}</span>,
  li: ({ children }) => <span>• {children} </span>,
  blockquote: ({ children }) => <span>{children}</span>,
  table: ({ children }) => <span>{children}</span>,
  thead: ({ children }) => <span>{children}</span>,
  tbody: ({ children }) => <span>{children}</span>,
  tr: ({ children }) => <span className="[&:not(:last-child)]:after:content-['_/_']">{children}</span>,
  th: ({ children }) => <span className="font-medium [&:not(:last-child)]:after:content-['_·_']">{children}</span>,
  td: ({ children }) => <span className="[&:not(:last-child)]:after:content-['_·_']">{children}</span>,
  hr: () => <span> — </span>,
  img: ({ alt }) => <span>[{alt || "image"}]</span>,
  pre: ({ children }) => <span>{children}</span>,
};

/** Segment text for reading: PDFs and images are OCR'd into markdown, and text files are read as markdown. In Word
 * and PowerPoint text, [^n] (a footnote mark, a picture or a field the sentence holds) is shown as a small chip.
 * `inline`: one run of text (for context lines); `highlight`: terms to mark. */
export function Markdown({
  text,
  className = "",
  inline = false,
  highlight,
}: {
  text: string;
  className?: string;
  inline?: boolean;
  highlight?: string[];
}) {
  const plugins = highlight?.length ? [remarkGfm, remarkHighlight(highlight)] : [remarkGfm];
  const body = (
    <ReactMarkdown remarkPlugins={plugins} components={inline ? INLINE : { code: markdownCode }}>
      {text.replace(OBJECT, (_m, n) => `\`${CHIP}${n}\``)}
    </ReactMarkdown>
  );
  return inline ? <span className={`prose-doc prose-inline ${className}`}>{body}</span> : <div className={`prose-doc ${className}`}>{body}</div>;
}

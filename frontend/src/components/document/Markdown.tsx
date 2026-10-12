import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Segment text for reading: PDFs and images are OCR'd into markdown, and text files are read as markdown. */
export function Markdown({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div className={`prose-doc ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

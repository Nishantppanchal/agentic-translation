import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { hasCodes } from "@/lib/codes";
import { CodeText } from "./CodeText";

/**
 * Segment text for reading. PDFs and images are OCR'd into markdown; Word, PowerPoint, Excel and XLIFF
 * documents are plain text with inline formatting codes (`plain`), which must not be read as markdown.
 */
export function Markdown({
  text,
  className = "",
  plain = false,
  labels,
  heading = false,
}: {
  text: string;
  className?: string;
  plain?: boolean;
  labels?: Record<string, string>;
  heading?: boolean;
}) {
  if (plain || hasCodes(text)) {
    return (
      <div className={`prose-doc ${className}`}>
        <p className={`whitespace-pre-wrap ${heading ? "text-lg font-semibold" : ""}`}>
          <CodeText text={text} labels={labels} />
        </p>
      </div>
    );
  }
  return (
    <div className={`prose-doc ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

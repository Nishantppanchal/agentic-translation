export type DocStatus =
  | "uploaded"
  | "ocr"
  | "ocr_check"
  | "translating"
  | "awaiting_answers"
  | "awaiting_source_check" // read; waiting for the person to check the source before translating
  | "reviewing"
  | "ready"
  | "error";

export interface Progress {
  stage: string;
  current: number;
  total: number;
  message: string;
}

export interface SessionSummary {
  id: string;
  filename: string;
  source_lang: string;
  target_lang: string;
  status: DocStatus;
  pages: number;
  updated_at: number;
  progress: Progress | null;
  open_questions: number;
  running: boolean;
  counts?: StatusCounts;
  project_id?: string | null;
  project_name?: string | null;
  format?: DocFormat | null;
}

/** How the document was read: OCR (pdf, image) or as plain text / Markdown. */
export type DocFormat = "pdf" | "image" | "text";

export interface Project {
  id: string;
  name: string;
  source_lang: string; // the target is always English
  instructions: string; // style guide, added to the translator, reviewer and editor prompts
  auto_confirm_context: boolean; // 101% TM matches start as confirmed
  lqa_threshold: number; // LQA pass mark (100 − penalty points per 1000 source words)
  created_at: number;
  documents: number;
  terms: number;
  tm_units: number;
}

export interface Term {
  id: number;
  source: string;
  target: string;
  note: string;
  forbidden: string[]; // translations that must not be used
  case_sensitive: boolean;
  status: "approved" | "proposed" | "note"; // note = an explanation only (e.g. from a clarification)
  updated_at: number;
}

export interface TmUnit {
  id: number;
  source: string;
  target: string;
  origin: string;
  updated_at: number;
}

export interface TmMatch {
  id: number;
  score: number; // 101 = same source and same previous segment · 100 = exact · 75-99 fuzzy
  source: string;
  target: string;
  origin: string;
}

export interface TmStats {
  context: number;
  exact: number;
  fuzzy: number;
  words: number;
}

// Statuses record human work only: confirmed by the translator, reviewed by a second (human) linguist.
export type SegmentStatus = "new" | "draft" | "confirmed" | "reviewed";
export type Role = "translator" | "reviewer";

export interface StatusCounts {
  new: number;
  draft: number;
  confirmed: number;
  reviewed: number;
  total: number;
}

export interface UsageRow {
  step: string;
  model: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  tokens: number;
}

export interface Usage {
  total: { calls: number; prompt_tokens: number; completion_tokens: number; tokens: number };
  rows: UsageRow[];
}

export interface Segment {
  id: string;
  page: number;
  kind: "heading" | "paragraph" | "list" | "table" | "code" | "figure" | "header" | "footer";
  source: string;
  target: string | null;
  translatable: boolean;
  image?: string; // figure segments: cropped image (artifact name)
  figure?: number;
  flags?: string[]; // "untranslated" | "merged" — forced through review; shown until fixed
  pages?: number[]; // paragraph that runs across a page break
  status: SegmentStatus;
  ai_check?: "passed" | "issues" | null; // the AI reviewer's verdict — not a human status
  locked: boolean;
  origin: "mt" | "agent" | "human" | "copy" | "tm_exact" | "tm_fuzzy" | null;
  match?: number | null; // translation-memory match % the segment started from
  qe?: number | null; // AI quality estimate 0-100 from the last review or LQA of this text
  updated_at: number | null;
  comments?: SegmentComment[];
}

/** An English translation the person can pick for a term, with when it is right. */
export interface TermOption {
  target: string;
  note: string;
}

/** A term the agents want a person to decide — explained for someone who doesn't read the source language. */
/** An entry from the dictionary service (DICTIONARY_URL). */
export interface DictionaryEntry {
  term?: string; // the dictionary's headword (may be the base form of an inflected term)
  translation?: string;
  definition?: string;
  domain?: string;
  source?: string;
  url?: string;
}

export interface Question {
  id: string;
  term: string;
  guess: string; // the recommended translation
  options?: TermOption[]; // English choices; options[recommended] is the agents' pick
  recommended?: number | null;
  meaning?: string; // what the term refers to, in plain English
  gist?: string; // an English gist of a sentence using it
  segment_ids: string[];
  reason: string; // why the choice matters
  dictionary?: DictionaryEntry[]; // what the dictionary service says, if one is set up
  origin?: "analysis" | "translator" | "reviewer" | "editor";
  status: "open" | "resolved" | "dismissed";
  answer: string | null;
  answer_target?: string;
}

/** A person's answer: the English term to use and/or a note explaining the meaning. */
export interface Answer {
  target?: string;
  note?: string;
  recommended?: boolean; // the agents' recommendation taken as it was → saved as a "proposed" project term
}

/** A key term the analysis fixed before translating. */
export interface KeyTerm {
  term: string;
  target: string;
  meaning: string;
  asked: boolean;
  dictionary?: DictionaryEntry[]; // what the dictionary service says, if one is set up
}

export interface Version {
  version: number;
  note: string;
  created_at: number;
  changed: string[];
}

export interface OcrPageReport {
  page: number;
  ok: boolean;
  issues: string[];
  used_text_layer: boolean;
  figures?: number;
  figure_source?: string; // "pdf" (embedded in the PDF), "layout" (found by PP-DocLayoutV3), or "pdf+layout"
  suggestions?: string[]; // the OCR check's possible misreadings that were NOT applied (for a person to check)
}

export type Severity = "minor" | "major" | "critical";
export type MqmCategory = "accuracy" | "fluency" | "terminology" | "style" | "locale" | "markup" | "other";

export interface ReviewIssue {
  segment_id: string;
  severity: Severity;
  category?: MqmCategory | null;
  note: string;
  auto?: boolean; // from the automatic QA checks
}

export interface QaIssue {
  id: string; // fingerprint: stays ignored until the segment's text changes
  check: string;
  label: string;
  category: MqmCategory;
  severity: "error" | "warning";
  segment_id: string;
  message: string;
  ignored: boolean;
}

export interface QaReport {
  issues: QaIssue[];
  summary: { errors: number; warnings: number; ignored: number; by_check: Record<string, number> };
  checks: { id: string; label: string }[];
}

export interface LqaError {
  segment_id: string;
  category: MqmCategory | null;
  severity: Severity;
  span: string;
  note: string;
}

export interface LqaResult {
  version: number | null;
  model: string;
  at: number;
  errors: LqaError[];
  scores: Record<string, number>;
  words: number;
  penalty: number;
  score: number;
  threshold: number;
  passed: boolean;
  counts: Record<Severity, number>;
  matrix: Record<string, Record<Severity, number>>;
}

export interface ReplaceOptions {
  find: string;
  replace: string;
  regex: boolean;
  case: boolean;
  whole_word: boolean;
  scope: "all" | "unconfirmed";
  ids?: string[];
}

export interface ReplaceMatch {
  segment_id: string;
  source: string;
  before: string;
  after: string;
  count: number;
}

export interface ReviewEntry {
  batch: number;
  round: number;
  issues: ReviewIssue[];
}

export interface GlossaryEntry {
  target: string;
  note?: string;
}

export interface ProposalChange {
  segment_id: string;
  field: "target" | "source";
  before: string;
  after: string;
  alternatives?: { text: string; note: string }[]; // pick one when accepting (default: the first)
}

export interface SegmentComment {
  id: string;
  role: "translator" | "reviewer" | "agent";
  text: string;
  at: number;
  resolved: boolean;
}

export type TaskKind = "alternatives" | "retranslate" | "consistency" | "lqa";

export interface Proposal {
  id: string;
  notes: string[];
  changes: ProposalChange[];
  glossary: Record<string, GlossaryEntry>;
  created_at: number;
}

/** A page fix the chat proposed during the source check: the page's source as OCR markdown, before and after. */
export interface SourceFix {
  id: string;
  page: number;
  before: string;
  after: string;
  reason: string;
  origin: "editor" | "reread";
  word_changes: string[]; // words the fix adds or removes (none for a pure structure fix)
  moved?: string[]; // passages that change place (quoted): a word count can't show a wrong reading order
}

export interface DocumentState {
  segments: Segment[];
  human_dirty: string[]; // segments edited by hand since the last saved version
  glossary: Record<string, GlossaryEntry>;
  termbase: Record<string, string>;
  brief: string;
  key_terms: KeyTerm[]; // fixed by the whole-document analysis before translating
  terms: Term[]; // project terms that occur in this document
  tm_stats: TmStats | null;
  lqa: LqaResult | null;
  format: DocFormat | null;
  proposal: Proposal | null;
  questions: Question[];
  versions: Version[];
  ocr_report: OcrPageReport[];
  source_fixes?: Record<string, SourceFix>; // page → pending fix
  review_report: ReviewEntry[];
}

export type TimelineItem =
  | { kind: "user"; id: string; text: string; ts: number }
  | { kind: "assistant"; id: string; author: string; text: string; ts: number; partial?: boolean }
  | { kind: "activity"; id: string; author: string; text: string; ts: number }
  | {
      kind: "tool";
      id: string;
      author: string;
      name: string;
      args: Record<string, unknown>;
      result?: unknown;
      ts: number;
    }
  | { kind: "version"; id: string; version: number; note: string; changed: string[]; ts: number }
  | { kind: "error"; id: string; text: string; ts: number };

export interface SessionDetail {
  summary: SessionSummary;
  document: DocumentState;
  timeline: TimelineItem[];
}

export type StreamEvent =
  | { type: "timeline"; item: TimelineItem }
  | { type: "progress"; progress: Progress; status: DocStatus | null }
  | { type: "state"; keys: string[] }
  | { type: "done" }
  | { type: "idle" }
  | { type: "error"; message: string };

export interface ExportFormat {
  id: "docx" | "md";
  label: string;
  group: string;
  ext: string;
  available: boolean;
  note?: string; // a caveat shown under the format
}

export interface AppConfig {
  models: Record<string, string>;
  languages: string[]; // source languages
  target_lang: string; // always English
  dictionary?: boolean; // a dictionary service is set up (DICTIONARY_URL)
}

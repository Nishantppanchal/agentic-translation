export type DocStatus =
  | "uploaded"
  | "reading" // a Word / PowerPoint / Excel file: its text is read from the file
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
  title?: string | null; // an English title the analysis gave the document
  abstract?: string | null; // and a two-line summary of what it says
}

/** How the document was read: OCR (pdf, image) or as plain text / Markdown. */
export type DocFormat = "pdf" | "image" | "text" | "docx" | "pptx" | "xlsx";
export const OFFICE_FORMATS: DocFormat[] = ["docx", "pptx", "xlsx"];

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

/** How a TM unit was approved: one by one (segment), by a reviewer, an agent's change accepted with Confirm, a
 * bulk click (never confirms a later segment by itself) or an import. */
export type TmApproval = "segment" | "review" | "proposal" | "bulk" | "import";

export interface TmUnit {
  id: number;
  source: string;
  target: string;
  ref: string; // where it comes from: "file.pdf#p1.2", "import"
  approval: TmApproval;
  updated_at: number;
}

export interface TmMatch {
  id: number;
  score: number; // 101 = same source and same previous segment · 100 = exact · 75-99 fuzzy
  source: string;
  target: string;
  ref: string;
  approval: TmApproval;
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
  model: string; // the models.yaml id that answered (older documents: the server's model name)
  effort?: Effort | null; // reasoning level sent
  reasoning_tokens?: number; // of the completion tokens, those spent thinking
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
  kind: "heading" | "paragraph" | "list" | "table" | "code" | "figure" | "header" | "footer" | "cell" | "note" | "alt"; // alt: a picture's alt text (Office)
  where?: string; // Word / PowerPoint / Excel: where in the file ("Slide 3 · Title", "Sheet1!B4 · column …")
  loc?: string; // Word / PowerPoint / Excel: the paragraph or cell in the file (for writing back)
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
  origin: "mt" | "agent" | "human" | "copy" | "tm" | null; // how the current text was made (tm: reused from the TM)
  match?: number | null; // the TM match behind the current text: 101/100 for "tm", the fuzzy score an "mt" text adapted
  tm_saved?: boolean; // this text is in the project's translation memory (a person confirmed it)
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
  tm?: { source: string; target: string; ref: string }[]; // translation-memory units that use the term
  // how the target was decided: as in the TM, the dictionary agrees, asked you, AI's guess (conflict: the
  // dictionary disagreed and there was no room to ask)
  decision?: "tm" | "dictionary" | "asked" | "ai" | "conflict";
  note?: string;
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
  readers?: 1 | 2; // two: a second model read the page too, and the OCR check settled where they differ
  disagreements?: number; // places where the two readings differ
  settled?: number; // …of which the OCR check settled
  hard?: boolean; // so many differences that the page is hard to read: nothing was changed, check all of it
  enlarged?: boolean; // the page image was small: the readers got it enlarged
  // regions the layout model took for pictures that were read as text instead (size / layout-text / text-layer / vision)
  figures_as_text?: { label: string; reason: string }[];
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
  origin: "editor" | "reread" | "figure"; // figure: "this is text, not a picture"
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
  orphan_comments?: OrphanComment[]; // comments whose text has changed since (still readable and deletable)
  settings?: DocSettings;
  unit?: "part" | "slide" | "sheet" | null; // Word / PowerPoint / Excel: what a "page" is
  page_labels?: string[] | null; // "Part 1", "Slide 3", a sheet's name — by page number
  office?: OfficeInfo | null;
  client_notes?: ClientNotesState | null; // the translation summary, once written
}

/** The translation summary for the client (Markdown), the version they were written for, and when. */
export interface ClientNotesState {
  text: string;
  version: number | null;
  at: number;
}

/** What reading a Word / PowerPoint / Excel file left out. */
export interface OfficeInfo {
  format: "docx" | "pptx" | "xlsx";
  tracked_changes?: number;
  not_translated?: Record<string, number>;
}

/** What writing the translation back into the file did. */
export interface OfficeWriteReport {
  written: number;
  unchanged: number;
  mismatch: string[]; // segments the file no longer matches (left as they were)
  formatting_simplified: string[];
  anchors_moved: string[]; // a footnote mark / picture the translation lost: put back near the end
  autofit: { where: string; scale: number }[];
  formulas_updated: number;
}

export interface SheetCell {
  v: string;
  seg?: string; // the segment whose text the cell shows
  b?: boolean;
  i?: boolean;
  color?: string;
  fill?: string;
  align?: "center" | "right";
  wrap?: boolean;
  border?: boolean;
}

export interface SheetGrid {
  sheets: { name: string; rows: SheetCell[][]; widths: number[]; heights: Record<string, number>; merges: string[];
    objects: { kind: string; anchor: string }[]; truncated: boolean }[];
  charts: number;
}

export interface OrphanComment extends SegmentComment {
  seg_id: string;
  anchor: string; // the source text the comment was made on
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
  | LookupItem
  | { kind: "error"; id: string; text: string; ts: number };

/** One entry a lookup found: a dictionary sense, a TM unit (source → target) or a termbase entry. */
export interface LookupEntry {
  target: string;
  source_text?: string;
  score?: number | null; // TM match %
  detail?: string; // definition, domain, note
  ref?: string; // dictionary name, or where a TM unit comes from
  badge?: string; // e.g. "bulk", "project · approved", "your answer"
  forbidden?: string[];
}

/** A dictionary, TM or termbase lookup — by the pipeline (the analysis, the TM pass) or by the chat (a tool). */
export interface LookupItem {
  kind: "lookup";
  id: string;
  author: string;
  ts: number;
  source: "dictionary" | "tm" | "termbase";
  via: "pipeline" | "tool";
  status: "pending" | "done" | "off" | "unavailable" | "limit" | "error";
  purpose: string;
  queries: number;
  hits: number;
  results: { query: string; entries: LookupEntry[]; outcome?: string }[];
  note?: string;
  text?: string; // the pipeline's one-line summary
}

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
  id: "docx" | "md" | "office" | "notes"; // notes: the translation summary (once written)
  label: string;
  group: string;
  ext: string;
  available: boolean;
  note?: string; // a caveat shown under the format
}

/** How hard a model with `thinking: true` reasons (sent as reasoning_effort; instant = no thinking). */
export type Effort = "instant" | "low" | "medium" | "high";
export type StepId =
  | "ocr"
  | "ocr_second"
  | "ocr_check"
  | "analyse"
  | "translate"
  | "review"
  | "refine"
  | "polish"
  | "rewrite"
  | "editor"
  | "lqa"
  | "suggest"
  | "complete"
  | "notes";

/** A model from config/models.yaml (never its URL, host, key or headers). */
export interface ModelInfo {
  id: string;
  model_name: string;
  label: string; // the name people see
  vendor: string | null; // whose model (for its logo): anthropic, qwen, openai, …
  server: "openrouter" | "ollama" | "custom";
  where: string; // "OpenRouter", "Ollama", "this computer", "own server"
  vision: boolean; // reads images: required for the steps that look at pages
  thinking: boolean; // offers reasoning levels
  structured_output: boolean;
  default_effort: Effort | null; // its own default level (models.yaml, else medium)
}

export interface StepChoice {
  model: string;
  effort: Effort | null; // null: the default level (see AppSettingsView.defaults), or a model that doesn't think
}
export type ModelChoices = Record<StepId, StepChoice>;

export interface DictionaryStatus {
  available: boolean; // a dictionary service is set up (DICTIONARY_URL)
  enabled: boolean;
  reason: string | null; // why it's unavailable
}

/** A second reading of scanned pages and pictures by another model (OCR_SECOND on the server). */
export interface SecondReaderStatus {
  available: boolean; // not turned off on the server
  enabled: boolean;
  reason: string | null; // why it's unavailable
  warnings: string[]; // e.g. the same model reads twice, or the OCR check is one of the readers
}

export interface StepGroup {
  id: string;
  label: string;
  help: string;
  steps: StepId[];
  vision: boolean; // every step in it looks at pages
  distinct?: boolean; // its steps are meant to be different models (Reading): no "Set all"
}

/** GET /api/settings: the defaults for new documents. */
export interface AppSettingsView {
  models: ModelChoices;
  configured: ModelChoices; // pipeline.yaml's (what "reset" goes back to)
  overridden: StepId[];
  dictionary: DictionaryStatus;
  second_reader: SecondReaderStatus;
  steps: { step: StepId; label: string; help: string; group: string; vision: boolean }[];
  groups: StepGroup[];
  efforts: Effort[];
  // What "Default" stands for: per step, per thinking model, the level and where it comes from.
  defaults: Partial<Record<StepId, Record<string, { effort: Effort; from: "pipeline.yaml" | "models.yaml" | "built-in" }>>>;
  flow: PipelineFlowSpec;
  assist?: boolean; // suggested prompts and Tab completions in the chat
}

/** The pipeline as a diagram (GET /api/settings → flow). */
export interface PipelineFlowSpec {
  rows: string[];
  // span: the rows a box covers, centred (the two readings run side by side into the check); a row named "" is the
  // one above's too
  nodes: { id: string; kind: "step" | "you" | "context"; step?: StepId; label: string; row: number; col: number; span?: number }[];
  edges: [string, string, string?][]; // from, to, and when that way is taken ("issues found")
}

/** One document's models and dictionary (from its next run). */
export interface DocSettings {
  models: ModelChoices;
  dictionary: DictionaryStatus;
  second_reader: SecondReaderStatus;
}

export interface AppConfig {
  models: Record<string, string>;
  languages: string[]; // source languages
  target_lang: string; // always English
  dictionary?: boolean; // a dictionary service is set up (DICTIONARY_URL)
}

# Features

Everything the app does as of October 2026 (roadmap milestones M0–M9). Setup, architecture, the API, tests and the demo script are in the [README](../README.md).

**In one paragraph:** upload a document (PDF, scan, image, Word, PowerPoint, Excel, XLIFF or text) in any language into a project; everything is translated into **English**. A PDF or scan first stops after reading, so you can check the source against the page images and have the chat fix it before anything is translated. Agents then read the whole document and ask you about the terms that need a decision — explained in plain English with English options and a recommendation, so you can answer without knowing the source language. Then they translate page by page, using the project's style guide, termbase and translation memory, and review and polish their own work. You finish it in a CAT-style segment editor, or by asking for changes in the chat. Every agent change is a proposal you accept or reject, and every accepted change is a version you can diff. Download it in the original format and layout, reflowed, as a bilingual review table, or as XLIFF for other CAT tools.

**Contents**
1. [The workspace](#1-the-workspace)
2. [Projects: style guide, termbase, translation memory](#2-projects)
3. [Uploading documents](#3-uploading-documents)
4. [The translation pipeline](#4-the-translation-pipeline)
5. [Segment editor](#5-segment-editor)
6. [Chat editor and proposals](#6-chat-editor-and-proposals)
7. [Agentic tasks](#7-agentic-tasks)
8. [Quality: QA checks, find & replace, LQA](#8-quality)
9. [Office and XLIFF files](#9-office-and-xliff-files)
10. [Layout-preserving PDF](#10-layout-preserving-pdf)
11. [Exports and exchange formats](#11-exports-and-exchange-formats)
12. [Versions and reading views](#12-versions-and-reading-views)
13. [Models and settings](#13-models-and-settings)
14. [Samples and demo kit](#14-samples-and-demo-kit)

---

## 1. The workspace

| Area | What's there |
|---|---|
| **Sidebar** | **New translation**, then each **project** with its documents underneath (collapsible), then documents outside any project. Each document shows its status and open-question count. |
| **Chat** (middle) | The conversation with the agents for the open document. While the pipeline runs, a **step bar** shows Read → Analyse → Translate → Review → Ready (with **Check** after Read for PDFs and images), with the current page and the elapsed time; while it waits for you, the current step says so. Then the source-check card, the question cards, proposals with diffs, and links to each version's diff. When a run ends, a **Next steps** card offers the obvious actions: *Review N drafts*, *Fix N QA errors*, *Check quality score*, *Download*. **Shortcuts** above the input: *Fix QA errors*, *Apply termbase*, *Summarise* (what the document says, in plain English), *More formal*. Enter sends, Shift+Enter adds a new line. |
| **Document panel** (right) | Five tabs: **Segments**, **Document** (views: *Reading*, *Side by side*, *Original layout*), **Quality**, **History**, **Source & notes** (views: *Source* / *Page images & OCR*, and *Brief, terms & checks*). The header (one line) holds the file name and status, the version picker, the download menu and the token chip. Drag the divider between chat and document to resize; the width is remembered. |
| **Project page** | Opens from the sidebar. Tabs: **Documents**, **Style guide**, **Termbase**, **Translation memory**, **Settings**. |

Hovering a passage in the reading views shows a button that **references it in the chat** ("p3.2"), so you can say "make this more formal" without copying text. In the Segments grid, **explain** on a row asks the agent what the source says.

---

## 2. Projects

A project is one client or job: **one source language, translated into English**, shared by all its documents. Documents can also be translated without a project; they then have no style guide, termbase or TM.

### Style guide
Free-text instructions ("British spelling. Formal register. Keep LV position numbers unchanged.") added to the prompts of the analyst, translator, reviewer, refiner and chat editor.

### Termbase
- **Fields:** source, target, **forbidden variants** ("never use"), note, case sensitivity, status.
- **What the prompts get:** only the terms that occur on the page being translated, plus a `NEVER translate X as "Y"` line for each forbidden variant.
- **In the segment grid:** terms are underlined in the source. Hovering one shows a card with the target, the note and the forbidden variants.
- **QA:** a forbidden variant in a translation is an error. A missing approved target is a warning, and inflected forms still count as present.
- **Write-back:** your answers to the agents' questions are saved — **approved** when you chose the term, **proposed** when you just accepted the recommendation (see [§4](#analysis-and-questions-decided-before-translating)) — and accepted glossary changes go in too. They are merged, so a note never erases an approved target.
- **Statuses:** *approved* terms are rules (prompts, QA, consistency fixer); *proposed* terms are suggestions only, with an **Approve** button; *note* entries explain a meaning without a fixed translation.
- **Import and export:** TBX (v2 `martif` and v3; deprecated terms become forbidden variants) and CSV import. CSV import detects header rows in several languages, accepts `;` `,` or tab delimiters, and reads UTF-8 or Windows-1252. Export as TBX-Basic v3, or as CSV with a BOM so Excel opens it correctly.
- **Editing:** terms can be filtered, edited inline, added and deleted.

### Translation memory
- **What's stored:** only segments a **person confirmed one by one** (Ctrl+Enter, or saving an edit as confirmed), each with the previous source segment as context, and confirmed work from an imported XLIFF. Bulk actions (**Confirm AI-checked**, **Mark confirmed as reviewed**) don't write to the TM: a click over many segments isn't a person checking each sentence, and the TM reuses its units as approved wording.
- **Match levels:**

  | Match | Meaning | What happens before translation |
  |---|---|---|
  | **101%** (context) | Same source, same previous segment | Filled in with no model call. Starts **confirmed** if the project's *Auto-confirm 101% matches* setting is on (the default, as in Trados and memoQ); otherwise draft. |
  | **100%** (exact) | Same source | Filled in with no model call, as **draft**. |
  | **75–99%** (fuzzy) | Scored per word, or per character for CJK | Passed to the translator as a reference to adapt. |

  An exact match whose formatting codes differ from the source is downgraded to a 99% fuzzy match, so the codes get fixed.
- **TM panel in the grid:** the active segment shows its top matches, with a diff between the stored source and this segment. **Alt+1–3** inserts a match.
- **Concordance search** on the project's Translation memory tab. Units can be deleted there.
- **Words saved:** shown in the chat ("5 segments reused, 47 words, no model call") and on the Checks tab.
- **Import and export:** TMX 1.4b. Region codes match (`de-DE` = German), inline codes are skipped, and markdown is stripped on export.
- **Safety and reporting:** XML imports are parsed with entities and network access disabled. Every import reports what was added, updated and warned about.

### Settings
- **Languages:** the source language; the target is always English.
- **Auto-confirm 101% matches.** On by default.
- **LQA pass threshold.** Default 90.

Deleting a project removes its termbase and TM, but keeps its documents. Databases from the multilingual version are migrated when the backend starts: English terms and TM units are kept, other target languages dropped.

---

## 3. Uploading documents

**Translate a document into English** has these fields:
- **Project** (optional). Choosing one fixes the source language.
- **From:** the source language, or auto-detect. The target is always English.

| Input | How it's read | What you can download |
|---|---|---|
| **PDF with a text layer** | Vision LLM per page, cross-checked against the text layer; then the source check | Layout-preserving PDF, reflowed formats, review table, XLIFF |
| **Scanned PDF, image** (PNG, JPG, WebP) | Vision LLM, then the OCR check; then the source check | Reflowed formats, review table, XLIFF (no layout-preserving PDF: it needs a text layer) |
| **Word** (.docx) | Read directly, no OCR; formatting becomes inline codes | **Translated .docx in its original formatting**, plus all the formats above |
| **PowerPoint** (.pptx) | Read directly | Translated .pptx, plus the formats above |
| **Excel** (.xlsx) | Read directly | Translated .xlsx, plus the formats above |
| **XLIFF 2.0 / 1.2** (.xlf, .xliff) | Read directly; existing translations kept | The same XLIFF with targets filled in, plus the formats above |
| **Text, Markdown** (.txt, .md) | Read as text | Reflowed formats, review table, XLIFF |

---

## 4. The translation pipeline

The pipeline is a Google ADK `Workflow` graph, run once per upload:

```
upload ─► route_source
            ├─ PDF / image / text ─► ocr       vision LLM, then the OCR check, per page (2 at a time)
            │                         │        figures detected, cropped and kept
            │                         ▼
            │                        check_source   PDFs and images pause: you check the reading against the
            │                                       page images; the chat proposes page fixes; Continue
            └─ Word / PPT / Excel / XLIFF ─► extract   text read from the file, formatting → inline codes
                       │
                       ▼
                  analyse       reads the WHOLE document: brief + key terms up front;
                                terms whose options differ in meaning become questions
                       │
                       ▼
                  ask           pauses once: you decide those terms (plain-English help, a recommendation)
                       │
                       ▼
                  translate     1. TM pass over the whole document (no model call)
                                2. one translator call per page, in order, with your answers
                       │
                       ▼
                  clarify       pauses again only for terms the translator still couldn't resolve
                       │
                       ▼
                  review ⇄ refine   per page, up to 2 rounds (the reviewer can be a different model)
                       │
                       ▼
                  polish        repeated sentences unified, termbase applied
                       │
                       ▼
                  finalize      version saved; next-step buttons in the chat
```

### Reading the source
- **OCR with verification:**
  1. **Vision LLM:** each page is rendered to an image and transcribed into markdown by a vision model (the `OCR` role, e.g. Qwen3-VL), in any script. It was measured on 23 languages: see [samples/SAMPLES.md](../samples/SAMPLES.md#ocr-measured).
  2. **Pictures marked on the page:** the PDF's embedded images and the pictures, charts and seals PP-DocLayoutV3 finds (the layout server's `detect_layout` tool) are outlined in red and numbered on the page image, so the model writes `[[FIGURE n]]` in their place instead of transcribing them.
  3. **OCR check:** a vision model compares the page with the image, and with the PDF's text layer when there is one. Its corrections are applied only when they're small fixes inside a word (a misread letter) or when the text layer confirms them. Anything else (a different word, a changed number, added or dropped text, and on scans any change to Chinese, Japanese or Korean characters) is listed in the Source tab as a *possible misreading* to compare with the page image, and the reading is kept.
  4. **The check is skipped only when two independent readings agree exactly:** the transcription is the same text as the PDF's own text layer (ignoring markdown, spacing, line-end hyphens and character variants such as ligatures) on a page without pictures. A single misread word, digit or minus sign, a messy text layer, a scan or a page with figures all get the check as before (`OCR_CHECK=always` checks every page).
  5. The Source tab shows which pages were corrected, the possible misreadings to check, and which pages matched their text layer.
  6. **Cached per page:** if a run fails (a rate limit, a restart), **Retry** reuses the pages already read.
- **Figures:**
  - **Detection:** photos, diagrams, charts and seals: the pictures embedded in the PDF, plus the picture, chart and seal regions PP-DocLayoutV3 finds. Without the layout server (`LAYOUT_SERVER_DIR` blank), only the embedded pictures.
  - **Placement:** each figure is cropped and placed in the translation where it appears.
  - **Text inside a figure** is read from its crop by the vision model and translated as a legend underneath.
- **Whole document:** running headers, footers and page numbers become segments too; a bare page number is just copied. A paragraph that runs across a page break (past a footer and the next page's header) is joined into one segment.
- **Office and XLIFF files** skip OCR (see [§9](#9-office-and-xliff-files)).

### Source check: fixing the reading before translating
Every PDF and image **pauses after reading** (status *Check source*; the step bar shows Read → **Check** → Analyse). Nothing is translated yet, so a fix to the source loses nothing. Office, XLIFF and text files don't pause.
- **The card** in the chat: *Check the source before translating*, with a **Continue to translation** button.
- **Checking:** compare the reading with the page images (**Source & notes → Page images & OCR**) and describe what's wrong in the chat, in plain words: two columns read straight across, a paragraph split at the column break, a stamp's text missing or inside a sentence, a heading or running header not marked.
- **Page fixes:** the chat editor proposes a fix for the whole page: the page's source as OCR markdown, before and after (a word-level diff), with a list of the words the fix adds or removes, and pictures dropped or added. A structure-only fix (join, split, reorder, mark a header, footer or heading) changes no words — but the word list can't tell a right reading order from a wrong one (two columns stitched the wrong way round keep every word), so each passage the fix **moves** is quoted separately (*Text moves*). The green *Only the structure changes* line means the same words in the same order. Two editor tools make them:
  - `propose_page_source`: the editor rewrites the page's structure itself;
  - `reread_page`: the vision model reads the page image again, with an instruction taken from what you said ("two columns: read the left column to the end, then the right; the red stamp is not part of the text").

  `get_page_source` shows a page's current source.
- **Accept** or **Reject** each page fix. Check the word list and any moved passages against the page image first. Accepting splits the page into segments again.
- **Continue to translation** goes on to the analysis; page fixes you haven't decided are dropped.
- **Afterwards:** page fixes are only possible during the source check; later, `fix_source_segment` corrects one segment.

### Translating: page by page, with the document carried along
Each **page** is one translator call, and pages are translated **in order**. A segment is a paragraph, heading, list item or table cell. What counts as a page depends on the format:

| Format | One "page" is |
|---|---|
| PDF, image | A real page |
| Word | A part of about 2,500 characters of body text, split at a heading where possible. Headers and footers are in part 1; footnotes and endnotes come after the body. |
| PowerPoint | A slide, with its notes |
| Excel | A sheet |
| XLIFF | A `<file>` |

A page over 6,000 characters (`PAGE_MAX_CHARS`) is split into parts that still run in order.

Each call sees:
- the page's segments;
- the **document brief**, written by the analysis before translating (so it already knows abbreviations defined later), and kept up to date page by page;
- the **previous text**: about 1,500 characters of source and translation (`CARRY_CONTEXT_CHARS`);
- the **running termbase**: the key terms the analysis fixed for the whole document, plus term choices made on earlier pages;
- the **glossary**: your answers to the questions;
- the project's **termbase entries** that occur on this page, its **forbidden variants**, and the **style guide**;
- **fuzzy TM matches** for these segments, to adapt.

The translator replies in JSON that follows a schema built for that call, so the segment ids can only be this page's ids. Models without structured output fall back to a tag format (`STRUCTURED_OUTPUT=auto|on|off`). The result is saved as **v1 "Draft translation"**.

Because the analysis has read the whole document first, a term explained on page 4 is already known while page 1 is translated.

### Analysis and questions: decided before translating
- **The analysis** (one model call per 40,000 characters, `ANALYSIS_CHUNK_CHARS`) reads the whole document and writes:
  - the **brief**: document type and domain, parties, every abbreviation and defined term with its meaning (wherever it is defined), register;
  - up to 25 **key terms** (`ANALYSIS_MAX_TERMS`): domain terms, defined terms, abbreviations, names and recurring phrases, each with a **plain-English meaning** and 1–3 **English options**. Terms already in the glossary or project termbase are skipped.
- **Abbreviations** of the source language are key terms too and are rendered for an English reader: German *AG* / *AN* in a contract become *the Client* / *the Contractor* from page 1, even though they are only defined in an annex; abbreviations English readers know (UPS, kV, VOB/B) stay.
- **Clear terms** (one option is clearly right, or a standard translation exists) go straight into the running termbase.
- **Ambiguous terms** — where the options differ in meaning and the document doesn't settle it — become **questions** (at most 6, `MAX_QUESTIONS`). The pipeline pauses once, **before translating**.
- **Each question is answerable without knowing the source language:**
  - the term and what it means, in plain English;
  - why the choice matters;
  - the sentence it appears in, in the source and as an English gist (click to show it in the document);
  - the English options, each with a note on when it is right, and the agents' **recommendation preselected**;
  - your own English term, or an explanation of the meaning.

  **Accept all recommendations & continue** takes the preselected options; **Skip — let the AI decide** records nothing.
- **What happens to answers:** the first draft already uses them — no re-translation pass. In the project termbase:
  - a term **you chose** (another option, or your own term) becomes **approved**, with the meaning as its note: a rule for every later document, enforced by QA and never asked again;
  - a recommendation you **just accepted** becomes **proposed**: later documents get it as a suggestion ("suggested, not confirmed"), QA doesn't flag other renderings, the analysis may ask about it again where a document makes it ambiguous, and **Approve** in the Termbase tab (or editing it) makes it a rule. A proposed term never overrides an approved one;
  - a **skipped** question keeps the recommendation for this document only.
- **Late questions:** if the translator still flags a term it can't resolve (at most 3 per page), the pipeline pauses once more after the draft and re-translates the affected segments. Terms the analysis decided are never asked twice.
- **Questions after the run:** terms the reviewer or the chat editor finds unclear appear as non-blocking cards in the same format, with **Apply** (the editor proposes the edits) and **Keep current**.
- The Source & notes tab lists the brief and the key terms with their meanings, a glossary for someone who doesn't read the source language. Pauses survive a server restart.

### Review ⇄ refine
- **Review:** a reviewer agent checks each page against the source, the brief, the glossary, the termbase and the style guide. It uses `REVIEW_MODEL`, which should be a different model than the translator's, so the work gets a second opinion (the current setup: Qwen reviews Claude Haiku's translation). Qwen is a reasoning model: uncapped it thinks for about 4.5 minutes per page, so its hidden reasoning is capped at `REVIEW_REASONING_TOKENS` (2,000; about 35 s per page). In a benchmark the capped Qwen still caught a meaning error ("spätestens" → "at least") that Haiku, reviewing its own translation, missed.
  - **What it reports:** issues with an MQM category (accuracy, fluency, terminology, style, locale, markup), a severity (minor, major, critical) and a **QE score** (0–100) per segment.
  - **Forced issues:** deterministic QA errors (a missing number, a forbidden term, a broken code) and flags are always added as must-fix issues, whatever the reviewer says.
- **Refine:** a refiner agent fixes the reported issues. Round 1 fixes everything raised. Round 2 re-reviews only what changed and chases only major issues. The loop stops early when nothing changes.
- **100% TM matches are protected:** they are a person's approved wording for the same sentence, so the refiner only changes them for a major or critical issue, never for style.
- **Reviewer questions** only appear when the reviewer recommends something different from the current translation; if the refiner applies the recommendation anyway, the question is closed ("applied in review").
- **AI verdict:** each segment gets an **AI ✓** (passed) or issues badge. This is never a human status.

### Polish
Before the document is handed over, the consistency fixer runs on the AI draft: repeated sentences get one translation (a person's confirmed translation wins, with no model call) and termbase rules are applied (forbidden variants, missing approved terms). These fixes are applied directly, since nothing is human work yet; on a finished document the same fixer only proposes them.

### Guards against bad model output
- **Untranslated:** a segment the model dropped, or left in the source language, gets one targeted retry and is then flagged `untranslated`.
- **Merged:** text that shifted between neighbouring segments gets one retry with just those segments, then is flagged `merged`.
- **What flags do:** a flag becomes a forced major issue in review, and anything still flagged at the end is listed in the chat and badged in the UI.
- **Invented terms:** "terms" the model reports that don't occur in the source are discarded.
- **Escaped codes:** formatting codes the model escaped or respelled are normalised.

### Runs
- **Queue:** at most `MAX_PARALLEL_RUNS` (default 2) pipelines or tasks run at once across all documents; the rest show **Queued**. Chat turns never wait.
- **Reconnecting:** progress streams to the browser and replays when you reconnect or reload.
- **Step bar:** Read → Analyse → Translate → Review → Ready (Read → Check → Analyse … for PDFs and images), with the current page, a progress bar and the elapsed time.
- **Rate limits and stalls:** every model call retries with exponential backoff on rate limits and API errors (`MODEL_RETRIES`, default 5), and times out after `MODEL_TIMEOUT` (180 s) instead of hanging on a stalled provider connection, then retries.
- **Interrupted runs:** a run stopped by an error or a server restart shows a **Retry** button; pages already read are reused.

---

## 5. Segment editor

The **Segments** tab is a CAT-style grid: id | source | target | status, with QE, match % and flags.

### Statuses record human work only
| Status | Set by |
|---|---|
| `new` | OCR'd or extracted, not translated yet |
| `draft` | Machine translation, TM 100%, accepted proposals, human edits |
| `confirmed` | The translator (Ctrl+Enter), or a 101% TM match with auto-confirm on |
| `reviewed` | A second, human linguist (the ISO 17100 revision step) |

The AI reviewer's verdict is a separate **AI ✓** badge with a QE score; it never changes the status. Each segment also records its **origin** (`tm_context`, `tm_exact`, `tm_fuzzy`, `mt`, `agent`, `human`, `copy`) and its TM match %.

### Keyboard
| Keys | Action |
|---|---|
| ⌘/Ctrl+Enter | Confirm & next (Translator role) or mark reviewed & next (Reviewer role) |
| Alt+↑ / Alt+↓ | Previous / next segment |
| Esc | Revert unsaved changes in this segment |
| Alt+S (or Ctrl+Shift+Insert) | Copy the source into the target |
| Alt+1–3 (or Ctrl+1–3) | Insert TM match 1–3 |
| Shift+click on the tick box | Select a range of segments |

Edits save when you leave a segment.

### Toolbar
- **Progress bar:** done, reviewed, confirmed, draft and new counts.
- **Translator / Reviewer switch:** decides what Ctrl+Enter does and which bulk action is offered:
  - **Confirm AI-checked (n):** confirms every draft that passed the AI review (translator).
  - **Mark confirmed as reviewed (n):** signs off every confirmed segment (reviewer).
- **Filters:** All, **To do** (depends on the role), **QA issues**, **Comments** (open ones), **Confirmed**, and **Proposed** while the agents have pending changes. **Lowest score first** sorts by QE, which gives the review queue. A text filter searches source and target.
- **Replace:** find & replace (see [§8](#find--replace)).
- **Save version (n):** saves your edits as one version. This also happens automatically before agent runs, proposal accepts and exports.
- **Proposed changes banner:** while the agents have a pending proposal, a banner offers **Apply all** (or **Apply N selected**) and **Reject all**.

### In each row
- **Source:** project terms are underlined with a hover card. Formatting codes appear as numbered tags.
- **Target:** clickable code chips insert a code; a paired code wraps the selected words. A broken code is refused with a hint.
- **QA issues:** shown under the row whenever it has any (severity, check and what's wrong, e.g. *Date 12.01.2026 from the source is missing*), refreshed live. **Fix** asks the agent to correct it (the change comes back as a proposal); **Ignore** hides it until the text changes.
- **Proposed change:** an agent's pending change shows under the segment as a diff, with a tick box (and the alternatives to pick from, if any). It's the same selection as the proposal card in the chat.
- **explain:** asks the agent what the source says in plain English and whether the translation carries it — an answer in the chat, no edits.
- **Lock:** a locked segment can't be edited by people or agents.
- **Comments:** add, resolve, reopen and delete, tagged with the current role. Comments never change the text. They appear in the bilingual review table and in XLIFF notes, and the chat editor sees them.

Editing is read-only while agents run. A save fails with a conflict if the segment changed underneath you.

---

## 6. Chat editor and proposals

Ask for changes in plain language: "use a more formal tone in section 2", "translate Abnahme as acceptance everywhere", "please fix the remaining QA errors". An editor agent works through tools, and **its edits are staged as a proposal; nothing is applied until you accept.**

Ask questions too: "explain p1.4" or **Summarise** (a shortcut above the input) get an answer in plain English — what the source says, nuances the translation can't carry, and whether it renders it faithfully — without changing anything. That's how to check a translation from a language you don't read.

| Tool | What it does |
|---|---|
| `search_segments`, `get_segments` | Find and read segments (showing the proposed text when a proposal is pending) |
| `update_segment` | Propose a new translation for a segment (codes validated) |
| `replace_in_translation` | Propose a find/replace across segments, case-preserving |
| `propose_alternatives` | Offer several options for a segment, each with a note |
| `set_glossary_term` | Propose a glossary entry, which also goes into the project termbase |
| `run_qa_checks` | Run the automatic QA, for example "fix the QA errors" |
| `add_comment` | Leave a comment on a segment |
| `ask_user_about_term`, `resolve_question` | Ask you about a term (with its meaning and English options), or apply your answer to a question card |
| `get_page_source`, `propose_page_source`, `reread_page` | During the source check: show a page's source, propose a page fix (the editor rewrites the page's structure), or have the vision model read the page again with an instruction (see [§4](#source-check-fixing-the-reading-before-translating)) |
| `fix_source_segment` | Correct an OCR mistake in one source segment, after the source check (not for Word, PowerPoint, Excel or XLIFF, whose source is exact) |
| `inspect_page_layout` | Run PP-DocLayoutV3 on a source page and compare it with that page's segments |

**Proposal card**
- Each change is shown as a word-level diff and can be unticked individually, here or under the segment in the grid.
- With alternatives, you pick one option per segment.
- **Accept** applies the ticked changes as a new version; **Reject** discards the proposal.
- Follow-up messages can refine a pending proposal before you accept it.

---

## 7. Agentic tasks

Tasks run through a dedicated workflow, and their results come back as proposals.

- **Rewrite a selection:** tick segments in the grid, then choose **More formal**, **Simpler**, **Shorter**, **3 alternatives**, or type your own instruction. With alternatives you pick one per segment in the proposal. Options that break formatting codes are dropped, and locked segments are skipped.
- **Fix consistency** (Quality tab):
  - **Finding the groups:** done without a model. A group is either the same source translated differently, or a set of segments breaking a termbase rule (a forbidden variant used, or the approved term missing).
  - **Fixing them:**
    - If a person already confirmed one translation of a repeated sentence, that translation is used for the others with no model call.
    - Otherwise each group gets one model call.
    - Confirmed and locked segments are never changed.
- **LQA:** see [§8](#quality-score-lqa).

---

## 8. Quality

### Automatic QA
Deterministic checks run on every change; the **Quality** tab lists the issues, and the grid shows them per row.

| Check | Severity | Catches |
|---|---|---|
| **Untranslated** | error | Empty, or still in the source language |
| **Merged segments** | error | Text moved into or out of a neighbouring segment |
| **Numbers & dates** | error if missing, warning if extra | Locale-aware: `30.04.2026` = `30 April 2026` = `04/30/2026` = `2026年4月30日`; `1.500,50` = `1,500.50`; `14:30` = `2:30 pm`; `4.2.7` stays an identifier |
| **Terminology** | error (forbidden variant) / warning (approved term missing) | Termbase rules for this language; inflected forms count |
| **Markup & tags** | error (heading level, table shape, inline codes) / warning (list items, bold) | Structure and formatting that differ from the source |
| **Punctuation** | warning | A different final punctuation mark, with CJK equivalents |
| **Spaces** | warning | Double spaces, a space before punctuation (French spacing allowed) |
| **Consistency** | warning | The same source translated differently across the document |
| **Length** | warning | A translation far longer or shorter than the document's usual ratio |

- **Errors** go to the AI reviewer as must-fix issues; **warnings** appear only in the panel.
- **Ignore** hides an issue until its text changes, because issues are fingerprinted. **Show ignored** brings hidden ones back.
- The chat editor can run the checks and propose fixes.

### Find & replace
- **Options:** match case (otherwise the found text's case is kept), whole word (CJK-aware), regex with `$1` or `\1`, and a scope of all segments or only those not yet confirmed.
- **Preview:** a diff of every change, where you can untick segments.
- **Applying:** saves the changes as your edits in one version. Locked segments are skipped and reported. Your replacement wins over a pending agent proposal for the same segment.

### Quality score (LQA)
- **What it is:** **Run LQA** sends an independent assessor over the current version. It annotates errors by MQM category and severity without changing anything. It uses `LQA_MODEL`, which defaults to the review model; set it to a different model for a second opinion.
- **Score:** 100 − penalty points per 1,000 source words, with minor = 1, major = 5 and critical = 25 points. CJK characters count as half a word each.
- **Pass or fail:** compared with the project's threshold (default 90).
- **Scorecard:** category × severity counts with their points. It is marked stale once the translation changes.
- **Review queue:** the lowest-scoring segments first, in the Quality tab and through "Lowest score first" in the grid.

---

## 9. Office and XLIFF files

Word, PowerPoint, Excel and XLIFF files are read straight from the file (no OCR) and come back in their own format with the translation in place.

### Inline codes
- **Representation:** formatting is kept as XLIFF-style codes in the segment text:
  - **paired codes** `<g id="1">…</g>` for bold, italic, links and content controls;
  - **placeholders** `<x id="2"/>` for tabs, line breaks, images, footnote marks and fields.
- **Preparation:** runs are cleaned up first (spell-check marks, revision ids), and the paragraph's base formatting is whichever needs the fewest codes.
- **Rules:** the translator must keep every code, but may move a span to wherever its words end up in the target sentence.
- **Enforcement:** codes are checked in QA, in human edits, in find & replace, in the chat editor and in imports. They are repaired on export: extra codes are dropped and missing placeholders appended.

### By format
- **Word:**
  - **What's translated:** the body with nested tables, text boxes (both stored copies), headers and footers, footnotes and endnotes.
  - **Fields** (`TOC`, `PAGE`, `REF`, `HYPERLINK`, legacy form fields) keep their instruction while their visible result is translated, so a table of contents comes out translated and can still be updated.
  - **Content controls** keep their box.
  - **Tracked changes** are translated as if accepted, and the chat warns you as soon as the file is read.
  - The document language is set to English.
- **PowerPoint:** slides in order (shapes, groups, tables) and speaker notes. Text that grew gets shrink-on-overflow, and new runs are marked English.
- **Excel:**
  - **What's translated:** shared strings, in first-use order and once even when used in many cells, plus inline strings.
  - **What's untouched:** formulas, numbers and sheet names.
  - **Formulas that compare against a cell text** (`=COUNTIF(F:F,"未整改")`) are updated to that text's translation in the translated file (`"Not rectified"`), case-insensitively and keeping a comparison prefix like `"<>…"`, so their results stay right instead of dropping to 0. The download menu notes it, and the Sheets view shows each formula as it is in the translated file (on hover).
- **Where a segment lives:** the grid shows it, for example "Table 2", "Slide 3 · Title" or "Prices!B4".

### XLIFF 2.0
- **Export:** one unit per segment; `<pc>`/`<ph>` for codes; location, comments and QA notes as notes.
  - **States:** draft = translated, confirmed = reviewed, reviewed = final.
  - The exact status is kept in `subState`, and locked segments are flagged.
- **As an input:** existing translations are kept, only empty segments are translated, and the original file comes back with its own code attributes.

### XLIFF 1.2 (memoQ, older Trados)
- **Export, import and input**, like 2.0.
- **Codes:** `<g>`/`<x>`. Native `<bpt>`/`<ept>`/`<ph>`/`<bx>`/`<ex>`/`<it>` codes are copied back whole.
- **Segmentation:** `<seg-source>` segmentation gives one segment per `<mrk mtype="seg">`, and the markers survive the write-back.
- **States:** draft = needs-review-translation; confirmed = translated with `approved="yes"`; reviewed = signed-off.

### Importing a returned XLIFF (vendor or reviewer round trip)
Use the download menu → **Import a returned XLIFF…**, with a 2.0 or 1.2 file.
- **The result is a proposal**, which you accept or reject in the chat.
- **Checked first:**
  - The languages must match.
  - These units are reported and not applied:
    - unknown units;
    - units whose source changed;
    - locked segments;
    - units whose codes don't match.
- **Confirmed segments:** a segment someone confirmed here is only replaced by a `final` unit. Confirmed work from the other tool goes into the project TM.

---

## 10. Layout-preserving PDF

**Translated PDF — original layout**: the translation is set into the original pages. Only PDFs with a text layer get one; scans and page images get the reflowed formats instead.

- **What's removed:** only the text. Images, vector graphics, shading and table rules stay.
- **Typesetting:** each block is re-set in place with the original size, weight and colour, in Noto Sans with a CJK fallback.
- **Alignment:** segments are matched to the PDF's lines, tolerating hyphenation, spacing and markdown differences, and following paragraphs across page breaks.
  - **Headers and footers** are matched first, on their own page, so a paragraph continuing across the break doesn't swallow them.
  - **Own page first:** a segment is looked for on its own page(s) first, and lines another segment already took are skipped — a sentence printed on two pages goes to each page's own segment.
  - **Table cells** are matched individually, down to word level when two cells share a line.
- **Fit:** each block grows into free space (right up to the next column or object, down to the next block) and shrinks if needed.
  - **Never silently lost:** a block that still can't fit keeps its source text and is reported.
  - **Headers and footers** are translated in place on every page.
- **Output size:** fonts are subset, so a 2-page document is about 50 KB. Renders are cached per version.
- **Layout tab:** original and translated pages side by side. Each segment's box is coloured *fit*, *shrunk to fit* or *didn't fit — original kept*. Clicking a box highlights the segment.

---

## 11. Exports and exchange formats

Any saved version can be downloaded from the menu in the document header.

| Group | Format | Notes |
|---|---|---|
| Original layout | **Translated file, original format** | Word, PowerPoint, Excel or XLIFF in, the same format out |
| Original layout | **Translated PDF, original layout** | PDFs with a text layer only |
| Reflowed | **Word document** | Real headings, lists, tables, figures with captions. Header and footer as the document's own, with live `PAGE`/`NUMPAGES` fields. Document language set, East Asian font for CJK targets. |
| Reflowed | **Web page (HTML)** | Self-contained; running headers and footers are left out |
| Reflowed | **Markdown (+ figures)** | A zip when the document has figures |
| Review | **Bilingual review table (DOCX)** | Landscape table: id, source, target, status, notes (AI review issues, flags, comments). Rows are shaded by status and the header repeats on every page. |
| Exchange | **XLIFF 2.0** / **XLIFF 1.2** | For other CAT tools, and for round trips |

Project-level exchange (project page): **TMX** for the TM; **TBX** and **CSV** for the termbase.

Downloads with non-ASCII names keep them.

---

## 12. Versions and reading views

- **Versions:** saved after the draft, after clarifications, after AI review fixes, after each accepted proposal, after find & replace, and for saved human edits. Each version keeps a full snapshot.
- **History:** compare any two versions as a diff. Each version note in the chat opens its diff inline.
- **Document → Reading:** the translation as a formatted document, with figures and their legends. Flags are badged, and a paragraph that continues onto the next page says so.
- **Document → Sheets** (Excel): each sheet as a grid — sheet tabs, row and column headers, merged cells, fills, bold, column widths; the translated text in every cell that uses it, numbers, dates and formula results (marked *fx*, the formula on hover) as in the file. Original/Translation toggle; click a cell to open its segment.
- **Document → Slides** (PowerPoint): each slide as a canvas with its text boxes, tables and pictures where they sit, text shrunk to fit like the downloaded file, speaker notes underneath. Translation / Original / Side by side; click a text to open its segment. (Not a renderer: charts, themes and backgrounds aren't drawn.)
- **Document → Side by side:** source and translation in parallel.
- **Document → Original layout** (PDFs with a text layer): see [§10](#10-layout-preserving-pdf).
- **Source & notes → Source / Page images & OCR:** the page images next to the transcription, plus the OCR check results. For Office and XLIFF files: the extracted source with its formatting.
- **Source & notes → Brief, terms & checks:**
  - the OCR report;
  - TM leverage;
  - the **document brief**;
  - the **key terms** from the analysis, with their meanings;
  - the **terminology memory** (each term has a **Change** action that drafts the chat request to fix it everywhere);
  - the glossary;
  - the AI review report.

---

## 13. Models and settings

- **Token chip** (document header): tokens per pipeline step and model, computed from the run's saved events (no prices: the models run on your own servers).
- **Models:** every role calls a vLLM server directly (no router). An endpoint is a URL, the served model name, an API key, extra HTTP headers and extra request fields; each role can use its own:

  | Role | Needs | Setting |
  |---|---|---|
  | OCR | vision; reads whole pages, the text inside pictures, and pages again for the source check | `OCR_MODEL` |
  | OCR check | vision | `OCR_CHECK_MODEL` |
  | Analyse, translate, refine | text | `TRANSLATE_MODEL` |
  | Review | text; ideally a different model than the translator's | `REVIEW_MODEL` |
  | Chat editor | tool calling (`--enable-auto-tool-choice --tool-call-parser …`); also makes the source check's page fixes | `EDITOR_MODEL` |
  | LQA | text | `LQA_MODEL` (defaults to the review endpoint) |

  Each role has `<ROLE>_MODEL`, `_API_BASE`, `_API_KEY`, `_HEADERS` and `_EXTRA_BODY`; anything left unset comes from `MODEL`, `MODEL_API_BASE`, `MODEL_API_KEY`, `MODEL_HEADERS` and `MODEL_EXTRA_BODY`. Headers and extra body are JSON objects; a role's own replaces the default, and `{}` sends none. Any OpenAI-compatible endpoint works, e.g. OpenRouter: `<ROLE>_API_BASE=https://openrouter.ai/api/v1`, `<ROLE>_MODEL=<model id>`, `<ROLE>_API_KEY=…`.
- **Errors:** every failed call is logged as `vLLM error — <role> model <name> at <url>: HTTP <status> <type>: <server message>`, and a run that stops shows the same text. If the analysis or the final consistency pass fails, translation goes on and the chat says so with the error. Keys, header values and URL credentials are never printed.
- **Other settings** (`backend/.env`):

  | Setting | Default | Effect |
  |---|---|---|
  | `PAGE_MAX_CHARS` | 6000 | Longer pages are translated in parts |
  | `CARRY_CONTEXT_CHARS` | 1500 | Previous text carried into each page |
  | `REVIEW_MAX_ROUNDS` | 2 | Review ⇄ refine rounds |
  | `ANALYSIS_ENABLED` | true | Read the whole document before translating |
  | `ANALYSIS_MAX_TERMS` | 25 | Key terms the analysis fixes |
  | `MAX_QUESTIONS` | 6 | Questions asked before translating |
  | `ANALYSIS_CHUNK_CHARS` | 40000 | Longer documents are analysed in parts |
  | `MAX_QUESTIONS_PER_BATCH` | 3 | Late questions per page from the translator |
  | `MAX_CONCURRENCY` | 2 | Model calls at once within one run (OCR, review) |
  | `MAX_PARALLEL_RUNS` | 2 | Pipelines/tasks at once across documents |
  | `STRUCTURED_OUTPUT` | auto | JSON schema output (vLLM guided decoding), or `off` for the tag format |
  | `OCR_CHECK_ENABLED` | true | Second-pass OCR verification |
  | `OCR_CHECK` | auto | `auto` skips the check when the transcription equals the text layer (page without pictures); `always` |
  | `MODEL_RETRIES` | 5 | Retries per model call on rate limits (exponential backoff) and server errors |
  | `MODEL_TIMEOUT` | 180 | Seconds per model call before it is retried |
  | `REVIEW_REASONING_TOKENS` | 2000 | Cap on the reviewer's and LQA's hidden thinking (vLLM `thinking_token_budget`; needs `--reasoning-parser`, else the call is retried uncapped); 0 = no cap |
  | `OCR_DPI` | 150 | Page render resolution for OCR |
  | `FIGURE_DETECTION` | auto | `auto` (the PDF's embedded pictures + the pictures PP-DocLayoutV3 finds) or `off` |
  | `FIGURE_TEXT` | true | Read text inside figures as legends |
  | `LAYOUT_SERVER_DIR` | ../layout-server | The layout MCP server, which finds the pictures on pages. Blank = the PDF's embedded pictures only |
  | `LAYOUT_MODEL` | PP-DocLayoutV3 | `detect_layout`'s model |
  | `LAYOUT_MODEL_DIR` | (blank) | Where the PP-DocLayoutV3 model files are: a folder of model folders by name (like `~/.paddlex/official_models`) or the model's own folder. Blank = download to PaddleX's cache |

---

## 14. Samples and demo kit

- **Sample files** (`samples/`, catalogued with what each one tests in [samples/SAMPLES.md](../samples/SAMPLES.md)):
  - **German:** acceptance and maintenance reports and a follow-up report (PDF and scanned copies), a contract excerpt whose abbreviations are only defined on page 2, a Word report, a PowerPoint training deck and an Excel defect list.
  - **Chinese:** an acceptance report and a follow-up inspection (PDF and scanned copies, repeating paragraphs for TM leverage), a Word test report with tracked changes, a PowerPoint safety training and an Excel defect list with formulas — with utility terms that genuinely need a decision (两票三制, 五防, 三措一案…).
  - **Source check:** two two-column scans in `samples/review/`, German and Chinese, each with a paragraph running across the column break and a red stamp or seal over the text.
  - **English references** in `samples/reference/`, so a non-speaker can judge the output.
  - All generated by `scripts/make_samples.py` (run in `backend/`); the source-check scans by `scripts/make_review_samples.py`.
- **`scripts/seed_demo.py --reset --upload`** creates two projects — German → English and Chinese → English — each with a style guide, a termbase with forbidden variants and a translation memory, and uploads two documents into each (`--only de|zh` for one).
- **Vendor files:** `samples/demo/pruefbericht.vendor.en.xlf` and `samples/demo/zh/jiance-baogao.vendor.en.xlf`, with planted errors for the QA, LQA and consistency demo.
- **Hands-on test script:** [docs/TESTING.md](TESTING.md). A shorter walkthrough is the README's [Demo](../README.md#demo).

For what isn't supported yet, see [Known limitations](../README.md#known-limitations--next-steps).

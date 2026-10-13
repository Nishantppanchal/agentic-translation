# Features

Everything the app does as of October 2026 (roadmap milestones M0–M9). Setup, architecture, the API, tests and the demo script are in the [README](../README.md).

**In one paragraph:** upload a document (PDF, scan, image or text) in any language into a project; everything is translated into **English**. A PDF or scan first stops after reading, so you can check the source against the page images and have the chat fix it before anything is translated. Agents then read the whole document and ask you about the terms that need a decision — explained in plain English with English options and a recommendation, so you can answer without knowing the source language. Then they translate page by page, using the project's style guide, termbase and translation memory, and review and polish their own work. You finish it in a CAT-style segment editor, or by asking for changes in the chat. Every agent change is a proposal you accept or reject, and every accepted change is a version you can diff. Download it as a Word document or as Markdown.

**Contents**
1. [The workspace](#1-the-workspace)
2. [Projects: style guide, termbase, translation memory](#2-projects)
3. [Uploading documents](#3-uploading-documents)
4. [The translation pipeline](#4-the-translation-pipeline)
5. [Segment editor](#5-segment-editor)
6. [Chat editor and proposals](#6-chat-editor-and-proposals)
7. [Agentic tasks](#7-agentic-tasks)
8. [Quality: QA checks, find & replace, LQA](#8-quality)
9. [Downloads](#9-downloads)
10. [Versions and reading views](#10-versions-and-reading-views)
11. [Models and settings](#11-models-and-settings)
12. [Samples and demo kit](#12-samples-and-demo-kit)

---

## 1. The workspace

| Area | What's there |
|---|---|
| **Sidebar** | **New translation**, then each **project** with its documents underneath (collapsible), then documents outside any project. Each document shows its status and open-question count. |
| **Chat** (middle) | The conversation with the agents for the open document. While the pipeline runs, a **step bar** shows Read → Analyse → Translate → Review → Ready (with **Check** after Read for PDFs and images), with the current page and the elapsed time; while it waits for you, the current step says so. Then the source-check card, the question cards, proposals with diffs, and links to each version's diff. When a run ends, a **Next steps** card offers the obvious actions: *Review N drafts*, *Fix N QA errors*, *Check quality score*, *Download*. **Shortcuts** above the input: *Fix QA errors*, *Apply termbase*, *Summarise* (what the document says, in plain English), *More formal*. Enter sends, Shift+Enter adds a new line. |
| **Document panel** (right) | Five tabs: **Segments**, **Document** (views: *Reading*, *Side by side*), **Quality**, **History**, **Source & notes** (views: *Page images & OCR*, and *Brief, terms & checks*). The header (one line) holds the file name and status, the version picker, the download menu and the token chip. Drag the divider between chat and document to resize; the width is remembered. |
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
- **Editing:** terms can be filtered, edited inline, added and deleted. There is no file import; the demo seeder adds the rows of its `termbase.csv` through the terms API (`POST /api/projects/{pid}/terms`).

### Translation memory
- **What's stored:** only segments a **person confirmed one by one** (Ctrl+Enter, or saving an edit as confirmed), each with the previous source segment as context. Bulk actions (**Confirm AI-checked**, **Mark confirmed as reviewed**) don't write to the TM: a click over many segments isn't a person checking each sentence, and the TM reuses its units as approved wording.
- **Match levels:**

  | Match | Meaning | What happens before translation |
  |---|---|---|
  | **101%** (context) | Same source, same previous segment | Filled in with no model call. Starts **confirmed** if the project's *Auto-confirm 101% matches* setting is on (the default, as in Trados and memoQ); otherwise draft. |
  | **100%** (exact) | Same source | Filled in with no model call, as **draft**. |
  | **75–99%** (fuzzy) | Scored per word, or per character for CJK | Passed to the translator as a reference to adapt. |

- **TM panel in the grid:** the active segment shows its top matches, with a diff between the stored source and this segment. **Alt+1–3** inserts a match.
- **Concordance search** on the project's Translation memory tab. Units can be deleted there.
- **Words saved:** shown in the chat ("5 segments reused, 47 words, no model call") and on the Checks tab.
- **Adding units in bulk:** `POST /api/projects/{pid}/tm` with a JSON list `[{source, target, origin?}]` adds units; a unit with the same source is updated. The demo seeder loads its `memory.json` this way; it is also the integration point for other tools.

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
| **PDF with a text layer** | Vision LLM per page, cross-checked against the text layer; then the source check | Word document, Markdown |
| **Scanned PDF, image** (PNG, JPG, WebP) | Vision LLM, then the OCR check; then the source check | Word document, Markdown |
| **Text, Markdown** (.txt, .md) | Read as text | Word document, Markdown |

---

## 4. The translation pipeline

The pipeline is a Google ADK `Workflow` graph, run once per upload:

```
upload ─►         ocr           vision LLM, then the OCR check, per page (2 at a time);
                                figures detected, cropped and kept; text files read as they are
                       │
                       ▼
                  check_source  PDFs and images pause: you check the reading against the
                                page images; the chat proposes page fixes; Continue
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
  1. **Vision LLM:** each page is rendered to an image and transcribed into markdown by a vision model (the `ocr` step, see [§11](#11-models-and-settings)), in any script. It was measured on 23 languages: see [samples/SAMPLES.md](../samples/SAMPLES.md#ocr-measured).
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
- **Text files** (.txt, .md) skip OCR: they are read as they are.

### Source check: fixing the reading before translating
Every PDF and image **pauses after reading** (status *Check source*; the step bar shows Read → **Check** → Analyse). Nothing is translated yet, so a fix to the source loses nothing. Text files don't pause.
- **The card** in the chat: *Check the source before translating*, with a **Continue to translation** button. The message above it says **where to look first**, page by page, from what the reading itself recorded: possible misreadings the OCR check listed, corrections it made, seals or stamps the layout model found (text under them is easy to misread), and pages read from a scan (no text layer to compare with) — or that nothing stands out.
- **Checking:** compare the reading with the page images (**Source & notes → Page images & OCR**) and describe what's wrong in the chat — or, if you don't read the language, press **Check the pages for me**: the chat looks at each page next to its reading (the flagged ones first), says in plain English what looks wrong, and proposes fixes or has pages read again. In your own words you can point at things like: two columns read straight across, a paragraph split at the column break, a stamp's text missing or inside a sentence, a heading or running header not marked.
- **Page fixes:** the chat editor proposes a fix for the whole page: the page's source as OCR markdown, before and after (a word-level diff), with a list of the words the fix adds or removes, and pictures dropped or added. A structure-only fix (join, split, reorder, mark a header, footer or heading) changes no words — but the word list can't tell a right reading order from a wrong one (two columns stitched the wrong way round keep every word), so each passage the fix **moves** is quoted separately (*Text moves*). The green *Only the structure changes* line means the same words in the same order. Two editor tools make them:
  - `propose_page_source`: the editor rewrites the page's structure itself;
  - `reread_page`: the vision model reads the page image again, with an instruction taken from what you said ("two columns: read the left column to the end, then the right; the red stamp is not part of the text").

  `get_page_source` shows a page's current source, and `look_at_page` shows the editor the page image itself: it uses it to judge what's wrong (missing, out of order, inside a stamp, colours), not to transcribe — a general model reading small, stamped or curved text makes up plausible words (in a test it named a real company on a seal that says something else).
- **Only read text goes into the source:** a page fix (or a segment's source fix) may only add words that are already in the document as read, or that you wrote in the chat. Anything else is refused, and the editor has the OCR model read the page again (`reread_page`). Moving, joining and dropping text is always allowed.
- **Accept** or **Reject** each page fix. Check the word list and any moved passages against the page image first. Accepting splits the page into segments again.
- **Continue to translation** goes on to the analysis; page fixes you haven't decided are dropped.
- **Afterwards:** page fixes are only possible during the source check (they split the page into segments again, which would drop its translations). Later, a misread word is still fixed from the page, not from anyone's guess: `reread_page` has the OCR model read the page again and gives the editor the reading (nothing changes yet), then `fix_source_segment` corrects the segment with the text as read and `update_segment` proposes its new translation. You never need to type the source language yourself.

### Translating: page by page, with the document carried along
Each **page** is one translator call, and pages are translated **in order**. A segment is a paragraph, heading, list item or table cell. A page is a real page of the PDF or image; a text file is one page.

A page over 6,000 characters (`PAGE_MAX_CHARS`) is split into parts that still run in order.

Each call sees:
- the page's segments;
- the **document brief**, written by the analysis before translating (so it already knows abbreviations defined later), and kept up to date page by page;
- the **previous text**: about 1,500 characters of source and translation (`CARRY_CONTEXT_CHARS`);
- the **running termbase**: the key terms the analysis fixed for the whole document, plus term choices made on earlier pages;
- the **glossary**: your answers to the questions;
- the project's **termbase entries** that occur on this page, its **forbidden variants**, and the **style guide**;
- **fuzzy TM matches** for these segments, to adapt.

The translator replies in JSON that follows a schema built for that call, so the segment ids can only be this page's ids. Models without structured output fall back to a tag format (`structured_output: false` on the model in `models.yaml`). The result is saved as **v1 "Draft translation"**.

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
- **Review:** a reviewer agent checks each page against the source, the brief, the glossary, the termbase and the style guide. It uses the `review` step's model, which should be a different model than the translator's, so the work gets a second opinion (the current `pipeline.yaml`: Qwen reviews Claude Haiku's translation). A reasoning model can think for minutes per page: uncapped, Qwen took about 4.5 minutes per page, and with its hidden reasoning capped at 2,000 tokens (`extra_body: {thinking_token_budget: 2000}` on the step, see [§11](#11-models-and-settings)) about 35 s. In a benchmark the capped Qwen still caught a meaning error ("spätestens" → "at least") that Haiku, reviewing its own translation, missed.
  - **What it reports:** issues with an MQM category (accuracy, fluency, terminology, style, locale, markup), a severity (minor, major, critical) and a **QE score** (0–100) per segment.
  - **Forced issues:** deterministic QA errors (a missing number, a forbidden term) and flags are always added as must-fix issues, whatever the reviewer says.
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

### Runs
- **Queue:** at most `MAX_PARALLEL_RUNS` (default 2) pipelines or tasks run at once across all documents; the rest show **Queued**. Chat turns never wait.
- **Reconnecting:** progress streams to the browser and replays when you reconnect or reload.
- **Step bar:** Read → Analyse → Translate → Review → Ready (Read → Check → Analyse … for PDFs and images), with the current page, a progress bar and the elapsed time.
- **Rate limits and stalls:** every model call retries with exponential backoff on rate limits and API errors (`retries` in `models.yaml`, default 5), and times out after `timeout` (180 s) instead of hanging on a stalled provider connection, then retries.
- **Interrupted runs:** a run stopped by an error or a server restart shows a **Retry** button; pages already read are reused.

---

## 5. Segment editor

The **Segments** tab is a CAT-style grid: id | source | target | status, with QE, match % and flags.

### Statuses record human work only
| Status | Set by |
|---|---|
| `new` | Read (OCR or a text file), not translated yet |
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
- **Source:** project terms are underlined with a hover card.
- **QA issues:** shown under the row whenever it has any (severity, check and what's wrong, e.g. *Date 12.01.2026 from the source is missing*), refreshed live. **Fix** asks the agent to correct it (the change comes back as a proposal); **Ignore** hides it until the text changes.
- **Proposed change:** an agent's pending change shows under the segment as a diff, with a tick box (and the alternatives to pick from, if any). It's the same selection as the proposal card in the chat.
- **explain:** asks the agent what the source says in plain English and whether the translation carries it — an answer in the chat, no edits.
- **Lock:** a locked segment can't be edited by people or agents.
- **Comments:** add, resolve, reopen and delete, tagged with the current role. Comments never change the text. The chat editor sees them.

Editing is read-only while agents run. A save fails with a conflict if the segment changed underneath you.

---

## 6. Chat editor and proposals

Ask for changes in plain language: "use a more formal tone in section 2", "translate Abnahme as acceptance everywhere", "please fix the remaining QA errors". An editor agent works through tools, and **its edits are staged as a proposal; nothing is applied until you accept.**

Ask questions too: "explain p1.4" or **Summarise** (a shortcut above the input) get an answer in plain English — what the source says, nuances the translation can't carry, and whether it renders it faithfully — without changing anything. That's how to check a translation from a language you don't read.

| Tool | What it does |
|---|---|
| `search_segments`, `get_segments` | Find and read segments (showing the proposed text when a proposal is pending) |
| `update_segment` | Propose a new translation for a segment |
| `replace_in_translation` | Propose a find/replace across segments, case-preserving |
| `propose_alternatives` | Offer several options for a segment, each with a note |
| `set_glossary_term` | Propose a glossary entry, which also goes into the project termbase |
| `run_qa_checks` | Run the automatic QA, for example "fix the QA errors" |
| `add_comment` | Leave a comment on a segment |
| `ask_user_about_term`, `resolve_question` | Ask you about a term (with its meaning and English options), or apply your answer to a question card |
| `get_page_source`, `propose_page_source`, `reread_page` | During the source check: show a page's source, propose a page fix (the editor rewrites the page's structure), or have the vision model read the page again with an instruction (see [§4](#source-check-fixing-the-reading-before-translating)) |
| `look_at_page` | See a page image (the editor's model must be a vision model): to judge what's wrong, not to transcribe |
| `fix_source_segment` | Correct an OCR mistake in one source segment, after the source check (only with words from the document, from a reading of the page, or from you) |
| `inspect_page_layout` | Run PP-DocLayoutV3 on a source page and compare it with that page's segments |

**Proposal card**
- Each change is shown as a word-level diff and can be unticked individually, here or under the segment in the grid.
- With alternatives, you pick one option per segment.
- **Accept** applies the ticked changes as a new version; **Reject** discards the proposal.
- Follow-up messages can refine a pending proposal before you accept it.

---

## 7. Agentic tasks

Tasks run through a dedicated workflow, and their results come back as proposals.

- **Rewrite a selection:** tick segments in the grid, then choose **More formal**, **Simpler**, **Shorter**, **3 alternatives**, or type your own instruction. With alternatives you pick one per segment in the proposal. Locked segments are skipped.
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
| **Markup** | error (heading level, table shape) / warning (list items, bold) | Structure and formatting that differ from the source |
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
- **What it is:** **Run LQA** sends an independent assessor over the current version. It annotates errors by MQM category and severity without changing anything. It uses the `lqa` step's model; point it at a different model than the translator's for a second opinion.
- **Score:** 100 − penalty points per 1,000 source words, with minor = 1, major = 5 and critical = 25 points. CJK characters count as half a word each.
- **Pass or fail:** compared with the project's threshold (default 90).
- **Scorecard:** category × severity counts with their points. It is marked stale once the translation changes.
- **Review queue:** the lowest-scoring segments first, in the Quality tab and through "Lowest score first" in the grid.

---

## 9. Downloads

Any saved version can be downloaded from the menu in the document header.

| Format | Notes |
|---|---|
| **Word document** (DOCX) | Reflowed: real headings, lists, tables, figures with captions. Header and footer as the document's own, with live `PAGE`/`NUMPAGES` fields. Document language set, East Asian font for CJK targets. |
| **Markdown (+ figures)** | A zip when the document has figures |

Downloads with non-ASCII names keep them.

---

## 10. Versions and reading views

- **Versions:** saved after the draft, after clarifications, after AI review fixes, after each accepted proposal, after find & replace, and for saved human edits. Each version keeps a full snapshot.
- **History:** compare any two versions as a diff. Each version note in the chat opens its diff inline.
- **Document → Reading:** the translation as a formatted document, with figures and their legends. Flags are badged, and a paragraph that continues onto the next page says so.
- **Document → Side by side:** source and translation in parallel.
- **Source & notes → Page images & OCR:** the page images next to the transcription, plus the OCR check results.
- **Source & notes → Brief, terms & checks:**
  - the OCR report;
  - TM leverage;
  - the **document brief**;
  - the **key terms** from the analysis, with their meanings;
  - the **terminology memory** (each term has a **Change** action that drafts the chat request to fix it everywhere);
  - the glossary;
  - the AI review report.

---

## 11. Models and settings

- **Token chip** (document header): tokens per pipeline step and model, computed from the run's saved events (tokens only, no prices).
- **Models** are set in two YAML files in `backend/config/` (details and examples in the README's [Models](../README.md#models)):
  - **`models.yaml`** lists the models (copy it from `models.example.yaml`; it is git-ignored, so keys and internal server addresses are never committed). Each model has an `id`, the `model_name` the server knows it by, a `url` (any OpenAI-compatible server: vLLM, SGLang, OpenRouter, Ollama, LM Studio…) and an `api_key`, plus optional `headers`, `extra_body`, `timeout`, `retries`, `temperature` and `structured_output`. `defaults` apply to every model; a model's own values win.
  - **`pipeline.yaml`** says which model (by id) does each step: a `default`, plus `steps`. A step can also be `{model: <id>, extra_body: {...}, temperature: ...}`; its `extra_body` is added to the model's, e.g. `{thinking_token_budget: 2000}` to cap a reasoning model's thinking on vLLM (the server needs `--reasoning-parser`; one without it gets the call again without the budget).
  - **`${NAME}`** in either file is an environment variable from `backend/.env`, which holds the secrets (e.g. `OPENROUTER_API_KEY`).

  | Step | What it does | Needs |
  |---|---|---|
  | `ocr` | Reads each page image, the text inside pictures, and pages read again in the source check | vision |
  | `ocr_check` | Compares the reading with the page image | vision |
  | `analyse` | Brief, key terms and the questions before translating | |
  | `translate` | The translation, page by page | |
  | `review` | The AI review; ideally a different model than the translator's | |
  | `refine` | Fixes what the review found | |
  | `polish` | Consistency fixes before Ready, and the consistency task | |
  | `rewrite` | Tasks: rewrite with an instruction, alternatives | |
  | `editor` | The chat; also makes the source check's page fixes | tool calling (on vLLM: `--enable-auto-tool-choice --tool-call-parser …`) |
  | `lqa` | Independent quality scoring (MQM) | |
- **Headers:** every model request gets `defaults.headers`, the model's own `headers` and the run's headers (later ones win). `defaults.forward_headers` names headers of the API request that starts a run (e.g. `X-Request-Id`, `X-Tenant-Id`) to pass on to all its model calls; only those are forwarded, never the caller's other headers.
- **Mistakes in the files** are reported when the backend starts, with the file and what's wrong (an unknown model id, a step without a model and no default, a misspelt field, a `${NAME}` that isn't set, a missing `models.yaml`).
- **Errors:** every failed call is logged as `vLLM error — <step> model <name> at <url>: <server message>`, and a run that stops shows the same text. If the analysis or the final consistency pass fails, translation goes on and the chat says so with the error. Keys, header values and URL credentials are never printed.
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
  | `OCR_CHECK_ENABLED` | true | Second-pass OCR verification |
  | `OCR_CHECK` | auto | `auto` skips the check when the transcription equals the text layer (page without pictures); `always` |
  | `OCR_DPI` | 150 | Page render resolution for OCR |
  | `FIGURE_DETECTION` | auto | `auto` (the PDF's embedded pictures + the pictures PP-DocLayoutV3 finds) or `off` |
  | `FIGURE_TEXT` | true | Read text inside figures as legends |
  | `LAYOUT_SERVER_DIR` | ../layout-server | The layout MCP server, which finds the pictures on pages. Blank = the PDF's embedded pictures only |
  | `LAYOUT_MODEL` | PP-DocLayoutV3 | `detect_layout`'s model |
  | `LAYOUT_MODEL_DIR` | (blank) | Where the PP-DocLayoutV3 model files are: a folder of model folders by name (like `~/.paddlex/official_models`) or the model's own folder. Blank = download to PaddleX's cache |
  | `DATA_DIR` | data | Where documents and the project database are stored |
  | `MODELS_FILE` / `PIPELINE_FILE` | config/models.yaml / config/pipeline.yaml | Other places for the model files |

  The dictionary settings (`DICTIONARY_URL`, …) are in the README's [Dictionary service](../README.md#dictionary-service).

---

## 12. Samples and demo kit

- **Sample files** (`samples/`, catalogued with what each one tests in [samples/SAMPLES.md](../samples/SAMPLES.md)):
  - **German:** acceptance and maintenance reports and a follow-up report (PDF and scanned copies), and a contract excerpt whose abbreviations are only defined on page 2.
  - **Chinese:** an acceptance report and a follow-up inspection (PDF and scanned copies, repeating paragraphs for TM leverage), with utility terms that genuinely need a decision (消缺, 运维单位, 保电) and one defined only on page 2 (三措一案).
  - **Other languages:** the same one-page acceptance report in 21 more languages, in `samples/languages/`.
  - **Source check:** two two-column scans in `samples/review/`, German and Chinese, each with a paragraph running across the column break and a red stamp or seal over the text.
  - **English references** in `samples/reference/`, so a non-speaker can judge the output.
  - **Generators** (run in `backend/`): `scripts/make_samples.py` writes the Chinese follow-up inspection, the contract excerpt (with their scans), the Chinese termbase and TM, and the references of these and of `yanshou-baogao.pdf`; `scripts/make_review_samples.py` the source-check scans; `scripts/make_language_samples.py` the other languages.
- **`scripts/seed_demo.py --reset --upload`** creates two projects — German → English and Chinese → English — each with a style guide, a termbase with forbidden variants (`termbase.csv`, added through the terms API) and a translation memory (`memory.json`, added through `POST /api/projects/{pid}/tm`), from `samples/demo/` and `samples/demo/zh/`. It uploads `nachbegehung.pdf` (German) and `fucha-baogao.pdf` (Chinese) and lists more files to try, such as the source-check scans (`--only de|zh` for one project).
- **Hands-on test script:** [docs/TESTING.md](TESTING.md). A shorter walkthrough is the README's [Demo](../README.md#demo).

For what isn't supported yet, see [Known limitations](../README.md#known-limitations--next-steps).

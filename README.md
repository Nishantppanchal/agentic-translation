# Agentic Translator

Upload a document in any language, get a reviewed **English** translation as a versioned artifact, then keep refining it by chatting. Every change is diffable.

**The full feature reference is [docs/FEATURES.md](docs/FEATURES.md).** In short:
- **Formats:** PDF (text layer or scanned), images, Word, PowerPoint, Excel, XLIFF 2.0 / 1.2 and text. Office and XLIFF files come back in their own format, with formatting kept as inline codes.
- **Agentic pipeline:** OCR with verification → **whole-document analysis** (brief and key terms fixed up front) → **questions before translating**, explained in plain English with English options and a recommendation, so they can be answered without knowing the source language → translation page by page with carried context → review ⇄ refine by a second model → consistency polish.
- **Projects:** a style guide, a termbase with forbidden variants and a translation memory (101% / 100% / fuzzy). TMX, TBX and CSV exchange.
- **Segment editor:** a CAT-style grid with human-only statuses, keyboard shortcuts, a TM panel, term highlighting, comments, locks and versions.
- **Chat and tasks:** a chat editor (also explains source passages in plain English) and one-click tasks (rewrite, alternatives, consistency fixer). Agents only ever *propose*; you accept or reject, in the chat or right in the segment grid.
- **Quality:** automatic QA checks, find & replace, and MQM-based LQA scoring with a review queue.
- **Output:** a layout-preserving PDF (scans too), reflowed Word, HTML and Markdown, a bilingual review table, and XLIFF. A vendor's XLIFF can be imported back as a proposal.
- **Operations:** a step bar for runs, a run queue, retries on rate limits, a cost chip, and any model per role through LiteLLM.

Sample documents (German and Chinese, every format) are described in [samples/SAMPLES.md](samples/SAMPLES.md); a hands-on test script is in [docs/TESTING.md](docs/TESTING.md).

Built on **Google ADK 2.x** (`Workflow` graph + `LlmAgent`), FastAPI and Next.js. Layout detection uses **PP-DocLayout**, served as an **MCP tool**.

## Architecture

```
Next.js UI ── REST + SSE ──► FastAPI ──► ADK Runners ──► sessions (SQLite) + artifacts (disk)
 sidebar · project pages      │                         projects.db (projects, termbase, TM)
 chat · step bar · questions  │
 proposals · next steps       ├─ ingest Workflow (once per upload)
 document panel: segments,    │    START → route_source ─┬─► ocr ─────┬─► analyse → ask → translate → clarify → review ─┬─(refine)→ refine → review
   document, quality,         │                          └─► extract ─┘                                                └─(done)──→ polish → finalize
   history, source & notes    ├─ ops Workflow (tasks: rewrite, alternatives, consistency, LQA)
                              └─ editor LlmAgent (each chat turn; tools stage a proposal)
```

| Node / agent | What it does |
|---|---|
| `route_source` | PDFs, images and text go to `ocr`. Word, PowerPoint, Excel and XLIFF files go to `extract`, which reads segments with inline codes straight from the file, warns about tracked changes, and notes cell texts used in Excel formulas (the translated workbook updates those formulas to the translation). |
| `ocr` | Fans out over pages (`ctx.run_node`, concurrency-capped). For each page, `ocr_extractor` (vision) turns the page image into markdown. Then `ocr_checker` compares that text with the image (and the PDF text layer) and either approves it or returns corrected text. The check is skipped only when the transcription is the same text as the PDF's own text layer (after normalising markdown, spacing and line-end hyphens) on a page without pictures (`OCR_CHECK=auto`; `always` checks every page). Each page's result is cached as an artifact, so **Retry** after a failure doesn't read pages again. |
| `ocr` → figures | Before OCR, each page's figures are found. In PDFs with real text, embedded image positions give exact boxes. **PP-DocLayout** (the `detect_layout` MCP tool, see below) adds whatever those miss: figures on scans, vector charts, seals. If the layout server is unavailable, the vision model proposes boxes on scans instead, and invalid or full-page boxes are discarded. The figures are outlined and numbered on the page image ("set-of-marks"), so OCR writes `[[FIGURE n]]` where each one sits in reading order (a missing marker is appended at the end of the page). Each crop is saved as an artifact, and a focused vision call reads the text inside it, which becomes the figure's translatable legend. |
| `analyse` | Reads the **whole document** before translating (`analyst`, in parts of `ANALYSIS_CHUNK_CHARS`): writes the brief up front, including abbreviations and defined terms wherever they are defined, and lists up to `ANALYSIS_MAX_TERMS` key terms with a plain-English meaning and English options. Clear terms go straight into the running termbase; terms whose options differ in meaning (at most `MAX_QUESTIONS`) become questions. Terms already in the glossary or project termbase are skipped. If the analysis fails, translation goes ahead as before. |
| `ask` | **Human-in-the-loop, before translating:** if the analysis has questions, the workflow **pauses** once. Each question carries the meaning, the sentence (source and English gist), 2–3 English options with notes, and the recommendation (preselected). An answer is a glossary entry, so the first draft already uses it, and a project term: **approved** if the person chose it, **proposed** (a suggestion, not enforced) if they just accepted the recommendation. A skipped question keeps the recommendation for this document only. |
| `translate` | Runs the **TM pass** first: 101% and 100% matches are filled in with no model call, and fuzzy matches become references in the prompt. Then it translates **page by page, in order** (segment `p3.2` = page 3, block 2; for Office files a "page" is a Word part of about 2,500 characters, a slide or a sheet). A page over `PAGE_MAX_CHARS` is split into parts. Each call carries the document brief, the previous text (`CARRY_CONTEXT_CHARS` of source and translation), the running termbase, the project's matching terms and the style guide. `translator` returns the segments, term choices to keep (these go into the running termbase), terms it is unsure about and the updated brief, as schema JSON or tags. Saves **v1**. |
| `clarify` | Pauses again only for terms the translator still couldn't resolve (at most `MAX_QUESTIONS_PER_BATCH` per page; terms the analysis decided aren't asked twice). Answers go into the glossary, the affected segments are re-translated, and a version is saved. |
| `review` / `refine` | Flags and QA errors become forced issues. `reviewer` lists issues per page with an MQM category and severity (minor/major/critical) and a QE score per segment, sees the document brief, and also checks consistency with the termbase. It may challenge a termbase choice it thinks is wrong rather than enforce it. The `refine` route sends the flagged segments to `refiner`. The loop repeats up to `REVIEW_MAX_ROUNDS`, and stops early if a refine pass changes nothing. Set `REVIEW_MODEL` to a different model than the translator for a second opinion. 100% TM matches are only refined for major issues, never for style. Terms the reviewer finds unclear become non-blocking question cards — only when it recommends something different from the translation, and closed if the refiner applies it anyway. |
| `polish` | The consistency fixer on the AI draft: one translation per repeated sentence (a person's confirmed translation wins) and the termbase applied, directly (on a finished document the same fixer only proposes). |
| `finalize` | Saves the reviewed version and marks the document ready; the UI shows next-step buttons. |
| `ops` | Tasks started from the UI (`POST …/tasks`): `dispatch` routes to `rewrite` (an instruction, or n alternatives per segment), `consistency` (groups found without a model; a person's confirmed translation wins with no model call) or `assess` (LQA). Rewrites and fixes are staged as a proposal. |
| `editor` | Chat agent with tools: `search_segments`, `get_segments`, `update_segment`, `propose_alternatives`, `replace_in_translation` (case-insensitive and case-preserving), `set_glossary_term`, `run_qa_checks`, `add_comment`, `resolve_question`, `ask_user_about_term`, `fix_source_segment` (not for Office/XLIFF), `inspect_page_layout` (runs PP-DocLayout on a source page and compares the result with that page's segments). Edit tools **stage** changes in `doc:proposal` instead of applying them. Reads return the proposed text, so follow-up turns can refine a pending proposal. `POST …/proposal/accept` applies it as a new version; `…/reject` discards it. |

**Where things are stored:**
- **Project database** (`data/projects.db`, SQLite in WAL mode): projects, termbase and TM, shared across documents. ADK state is per-document and has no indexes, so it can't hold a TM. A document links to its project through `doc:project_id`; a deleted project leaves old documents working, without project data.
- **Session state:** the document. Each segment has its own key (`seg:<id>`), so an edit produces a small state delta. The glossary, termbase, pending proposal, questions, versions and OCR/review reports are stored there too.
- **Artifacts:** the uploaded source file and `translation.json`. Every version of `translation.json` is kept as an ADK artifact version.

**Glossary vs termbase.** The *glossary* is what you confirmed: clarify answers and accepted glossary proposals. It always wins. The *termbase* holds the translator's own choices from earlier pages, which keeps later pages consistent. Those choices are unverified, so a wrong early choice can repeat on later pages. Terms the translator flagged as uncertain are never added. A glossary entry for the same term replaces the termbase entry. Review the termbase in **Checks & glossary**; each row has a **Change** action that drafts the chat request to fix it everywhere.

The editor runs with `include_contents='none'`. Its instruction is built from the document, the glossary and a compact transcript of the chat, so the pipeline's bulky outputs never reach its context.

## Layout server (PP-DocLayout as an MCP tool)

`layout-server/` is a separate uv project, because PaddlePaddle is heavy (~800 MB). It exposes two MCP tools:
- `detect_layout(image_base64, threshold)` returns labelled regions (`doc_title`, `paragraph_title`, `text`, `table`, `image`, `chart`, `seal`, `header`, `footer`, …) as pixel boxes. Used for figures and, on scans, as obstacles.
- `ocr_lines(image_base64, script)` returns text lines with their recognised text and word boxes (PP-OCRv5 mobile models, a few MB, downloaded on first use; about 4 s per page on a laptop CPU). `script` is `latin`, `cjk`, `korean` or `cyrillic`, chosen from the source language. Used for layout-preserving PDFs of scans.

- **Startup:** the backend starts the server automatically over stdio through ADK's `McpToolset`. The first call loads the model (~16 s, plus a one-off download); after that it takes under a second per page on an Apple Silicon CPU.
- **Reuse:** any MCP client can use the same server, for example `uv run --project layout-server python layout-server/server.py`, or `tools=[layout_toolset()]` on an ADK agent.
- **Configuration:** `LAYOUT_MODEL` defaults to `PP-DocLayout_plus-L`; `PP-DocLayoutV3` returns regions in reading order but missed a table in testing. A blank `LAYOUT_SERVER_DIR` disables the server, and `FIGURE_DETECTION=auto|layout|vision|pdf|off` chooses the detectors.

```bash
cd layout-server && uv sync      # one-time install
```

## Running it

**Requirements:** [uv](https://docs.astral.sh/uv/), Node 20+, and a model. The default config expects [Ollama](https://ollama.com) with a vision- and tool-capable model such as Gemma 4 or Qwen2.5-VL.

```bash
# backend
cd backend
cp .env.example .env        # then set MODEL to your model, e.g. openai/<ollama-model-name>
uv sync
uv run uvicorn translator.api:app --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                 # http://localhost:3000
```

Sample PDFs in `samples/`, each with an image-only `-scanned.pdf` copy:
- German: `abnahmeprotokoll.pdf` (an acceptance report with a table) and `wartungsbericht.pdf` (a maintenance report with a labelled diagram).
- Office (German): `pruefbericht.docx` (bold and italic terms, a link, a table, a page-number footer, a footnote and two tracked changes), `unterweisung.pptx` (three slides with speaker notes) and `maengelliste.xlsx` (shared strings, rich text, and a `COUNTIF` formula that compares against a status text).
- Chinese: `yanshou-baogao.pdf` (an acceptance report with a table and a diagram labelled in Chinese).
- TM demo: `nachbegehung.pdf` is a follow-up inspection of the same substation, with a running header and a "Seite x von 2" footer. Several paragraphs repeat `abnahmeprotokoll.pdf` word for word, and one differs by a single word. Translate `abnahmeprotokoll.pdf` in a project, confirm it in the Segments tab, then translate `nachbegehung.pdf` in the same project: the exact matches are reused without a model call, and the fuzzy ones are offered to the translator.

Languages written without spaces (Chinese, Japanese, Thai, …) are handled throughout: find/replace matches inside sentences, Chinese text counts double toward the "has a text layer" check, and downloads with non-ASCII names use an RFC 5987 filename.

### Choosing models

The current `.env` uses budget models on OpenRouter: `openrouter/anthropic/claude-haiku-5.5` for analysis, translation and the editor, and `openrouter/qwen/qwen3.8-flash` for the OCR roles (vision) and for review and LQA (a second opinion from a different model than the translator). Model calls retry with exponential backoff on rate limits (`MODEL_RETRIES`, default 5) — OpenRouter's shared pools for budget models do throttle bursts — and time out after `MODEL_TIMEOUT` (180 s) instead of hanging on a stalled connection. Qwen is a reasoning model, so the reviewer's hidden reasoning is capped (`REVIEW_REASONING_TOKENS`, default 2000): about 35 s per page instead of about 4.5 minutes. Put your key in `OPENROUTER_API_KEY=` in `backend/.env`. `.env` is also loaded into the process environment, so provider keys there (`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, …) reach LiteLLM.

Every role (`OCR`, `OCR_CHECK`, `TRANSLATE`, `REVIEW`, `EDITOR`) uses `MODEL` / `MODEL_API_BASE` unless you set `<ROLE>_MODEL` / `<ROLE>_API_BASE`. `LQA_MODEL` falls back to the review model; set it to a different model for an independent quality score.

```bash
# All local (Ollama's OpenAI-compatible endpoint)
MODEL=openai/qwen2.5vl:7b
MODEL_API_BASE=http://localhost:11434/v1

# Hosted Gemini for OCR, local model for everything else
OCR_MODEL=gemini/gemini-2.5-flash
OCR_API_BASE=                 # empty = don't inherit the Ollama URL
OCR_CHECK_MODEL=gemini/gemini-2.5-flash
OCR_CHECK_API_BASE=
GEMINI_API_KEY=...

# Claude for translation and review
TRANSLATE_MODEL=anthropic/claude-sonnet-5-5
TRANSLATE_API_BASE=
REVIEW_MODEL=anthropic/claude-sonnet-5-5
REVIEW_API_BASE=
ANTHROPIC_API_KEY=...
```

Model requirements:
- OCR roles need **vision**.
- The editor needs **tool calling**.
- Pipeline agents reply in schema-constrained JSON when the model supports structured output, and otherwise in simple tag formats (`<seg id="…">`), which small local models handle reliably.

## Tests

```bash
cd backend && uv run pytest
```

`tests/test_analysis.py` covers the workflow upgrades: the whole-document analysis pausing for questions before any translation (options, meaning, gist; the answer shapes the first draft and becomes an approved project term), skipped questions keeping the recommendation, the translator and reviewer not re-asking decided terms, the OCR check skipped only for identical text (a changed digit, word or minus sign still checks), per-page OCR reused on retry, the consistency polish, and paused-run detection when interrupt ids repeat. `tests/test_scan_layout.py` covers scans: a rasterised page with faked OCR is translated in place with the sampled paper colour, a misread line is placed by position, page images work, and lines inside figures are skipped. An opt-in test runs the real PP-OCRv5 server on `samples/abnahmeprotokoll-scanned.pdf`. `tests/test_ops.py` covers alternatives in proposals (with a choice when accepting), the rewrite task (locked segments skipped, broken-code options dropped, JSON mode), the consistency task (confirmed translations win without a model call, same-source and termbase groups), comments, migrating a multilingual database to English only, the English-only project API, and the run queue. `tests/test_office.py` covers Word/PowerPoint/Excel: writing the source back reads the same; pseudo-translation keeps bold and italic, links, fields (instruction kept, result translated), content controls, both text-box copies, footnotes, notes, rich text, formulas and numbers; tracked changes accepted; code repair; stale paragraphs skipped; autofit; target language; formula-literal warnings. `tests/test_xliff.py` covers XLIFF export structure, an export → import no-op, the import rules, XLIFF as an input with write-back of the original code attributes, a Word file through the whole pipeline (escaped tags repaired, original-format and XLIFF exports, code-safe edits, an XLIFF proposal accepted), and TM matches whose codes differ. `tests/test_qa.py` has a table of cases for each QA check, plus ignore fingerprints, forced review issues and find & replace (preview, case, regex, CJK, locked segments, one version). `tests/test_lqa.py` covers MQM arithmetic, word counts, tolerant parsing, the LQA run in tag and JSON modes, and a pipeline run where a dropped date is forced through review and fixed. `tests/test_projects.py` covers the project store (TM scoring for 101/100/fuzzy and CJK, term matching, merging), the pipeline's TM pass against a seeded memory (exact matches skip the model, fuzzy ones reach the prompt), TM write-back on human confirmation, TMX/TBX/CSV round trips, XXE and entity-expansion safety, and the project API. `tests/test_chinese.py` covers Chinese segmentation, text layers, find/replace without spaces, download names, and a full Chinese → English run (figure placement, clarify, termbase). `tests/test_layout_integration.py` runs the real PP-DocLayout MCP server; it is opt-in (`RUN_LAYOUT_TESTS=1 uv run pytest`).

`tests/test_flow.py` runs the real workflow and editor against a scripted fake model. It covers:
- OCR fan-out with a checker correction
- language auto-detection
- the clarify pause and resume
- glossary re-translation
- the review → refine loop
- an editor tool call creating a new version
- rebuilding the timeline

It needs no network access and finishes in about 2 seconds.

## API

| Method | Path | |
|---|---|---|
| `GET` | `/api/config` | models per role, languages |
| `GET` / `POST` | `/api/sessions` | list / upload a document to translate into English: PDF, image, TXT/MD, DOCX, PPTX, XLSX or XLIFF 2.0/1.2 (multipart: `file`, `source_lang`, optional `project_id`, which sets the source language); upload starts the ingest workflow |
| `GET` / `DELETE` | `/api/sessions/{id}` | summary + document state + chat timeline |
| `GET` | `/api/sessions/{id}/stream` | SSE for the active run; replays its buffered events, so you can reconnect at any time |
| `POST` | `/api/sessions/{id}/clarifications` | `{answers: {q1: {"target": "cable tray", "note": ""}, q2: null}}`: resumes the paused workflow (`target` = the English term to use, `note` = an explanation; `null` = keep the recommendation) |
| `POST` | `/api/sessions/{id}/retry` | re-run ingest after a failure or server restart |
| `PATCH` | `/api/sessions/{id}/segments/{seg}` | `{target?, confirm, base_target, role: translator\|reviewer}`: human edit and/or confirm. 409 if agents are running, the segment is locked, or `base_target` is stale |
| `POST` | `/api/sessions/{id}/segments/{seg}/lock` | `{locked}` |
| `GET` | `/api/sessions/{id}/segments/{seg}/tm` | top 5 TM matches for a segment (101 / 100 / fuzzy) |
| `POST` | `/api/sessions/{id}/segments/confirm` | `{ids?, role}`: bulk confirm (translator: AI-checked drafts) or mark reviewed (reviewer: confirmed segments) |
| `POST` | `/api/sessions/{id}/versions` | save pending human edits as one version |
| `GET` | `/api/sessions/{id}/usage` | tokens and cost per pipeline step and model |
| `GET` | `/api/sessions/{id}/qa` | automatic QA issues (computed on request) with a summary per check |
| `POST` | `/api/sessions/{id}/qa/ignore` | `{ids, ignored}`: ignore or restore issues by fingerprint |
| `POST` | `/api/sessions/{id}/replace/preview` | `{find, replace, regex, case, whole_word, scope}` → the changes as before/after |
| `POST` | `/api/sessions/{id}/replace` | same body + `ids` (chosen in the preview): apply as human edits in one version |
| `POST` | `/api/sessions/{id}/lqa` | start an LQA run (MQM scoring of the current version; the result is `doc:lqa`) |
| `POST` | `/api/sessions/{id}/tasks` | `{kind: alternatives\|retranslate\|consistency\|lqa, segment_ids, instruction, n}`: run a task; rewrites and consistency fixes come back as a proposal |
| `POST` | `/api/sessions/{id}/segments/{seg}/comments` | `{text, role}`: add a comment |
| `PATCH` / `DELETE` | `/api/sessions/{id}/segments/{seg}/comments/{cid}` | `{resolved}`: resolve or reopen / delete |
| `POST` | `/api/sessions/{id}/messages` | chat turn for the editor agent (it proposes; nothing is applied yet) |
| `POST` | `/api/sessions/{id}/proposal/accept` | `{changes: ["p1.5\|target", …] \| null, choices: {"p1.5\|target": 1}}`: apply all or the selected changes as a new version, with the chosen alternative per change |
| `POST` | `/api/sessions/{id}/proposal/reject` | discard the pending proposal |
| `POST` | `/api/sessions/{id}/questions/{qid}` | `{target, note}` (or `{}` to dismiss): answer a later (non-blocking) question; the editor proposes the edits |
| `GET` | `/api/sessions/{id}/versions/{n}` | translation snapshot `{segment_id: text}` |
| `GET` | `/api/sessions/{id}/pages/{n}` | rendered page image |
| `GET` | `/api/sessions/{id}/figures/{name}` | cropped figure image |
| `GET` | `/api/sessions/{id}/export?format=original\|pdf\|docx\|html\|md\|bilingual\|xliff\|xliff12&version=&field=` | download a version. `original` is the translated Word/PowerPoint/Excel/XLIFF file; `pdf` is the original layout (text layer or OCR'd scan; rendered once per version and cached); `md` is a zip when the document has figures; `xliff` / `xliff12` are XLIFF 2.0 / 1.2 |
| `POST` | `/api/sessions/{id}/import/xliff` | a returned XLIFF 2.0 or 1.2 → a proposal, plus a report (changes, unchanged, unknown, source changed, locked, kept confirmed, codes) |
| `GET` | `/api/sessions/{id}/export/formats` | which formats this document supports (the layout PDF needs a PDF with a text layer, or a scan or image plus the layout server) |
| `GET` | `/api/sessions/{id}/preview/report?version=` | layout result per segment: `fit\|shrunk\|overflow\|unaligned`, plus boxes |
| `GET` | `/api/sessions/{id}/preview/pages/{n}?version=` | a page of the translated PDF as PNG |
| `GET` / `POST` | `/api/projects` | list / create `{name, source_lang, instructions, auto_confirm_context, lqa_threshold}` (the target is always English) |
| `GET` / `PATCH` / `DELETE` | `/api/projects/{pid}` | with counts of documents, terms and TM units; `PATCH` takes the same fields as create; deleting removes the termbase and TM and keeps the documents |
| `GET` / `POST` | `/api/projects/{pid}/terms` | list / add a term (an existing source is merged) |
| `PATCH` / `DELETE` | `/api/projects/{pid}/terms/{tid}` | edit (replaces fields; 409 on a duplicate source) / delete |
| `GET` | `/api/projects/{pid}/tm?q=` | concordance search (most recent units without `q`) |
| `DELETE` | `/api/projects/{pid}/tm/{uid}` | delete a TM unit |
| `POST` | `/api/projects/{pid}/import` | `.tmx` → TM; `.tbx` / `.csv` → termbase. Returns `{kind, added, updated, warnings}` |
| `GET` | `/api/projects/{pid}/export?format=tmx\|tbx\|csv` | download the TM or termbase |

## Demo

A 15-minute walkthrough for translators and agencies; the full hands-on test script (every feature, German and Chinese, with what each source says) is [docs/TESTING.md](docs/TESTING.md). The backend and frontend should be running; for the scan steps, so should the layout server (`cd layout-server && uv sync` once).

```bash
cd backend
uv run python scripts/make_samples.py              # (re)generate the Chinese and agentic test samples
uv run python scripts/seed_demo.py --reset --upload
```

This creates two projects, each with a style guide, a termbase with forbidden variants and a translation memory, and uploads two documents into each:
- **Acme Energie – Umspannwerk Nord** (German → English): `nachbegehung.pdf` and `pruefbericht.docx`.
- **北区变电站改造 – UW-2291** (Chinese → English): `fucha-baogao.pdf` and `jiance-baogao.docx`.

1. **Questions before translating.** Upload `samples/vertragsauszug.pdf` (German) or `samples/anquan-peixun.pptx` (Chinese) into its project.
   - The step bar shows Read → Analyse; the analysis reads the whole document first (the brief already knows what AG/AN or 三措一案 mean, though they are only defined later).
   - The questions explain each term in plain English, show the sentence in English, and preselect a recommendation. **Accept all recommendations & continue**, or pick another option.
   - The first draft already uses your answers (no re-translation pass). Terms you chose become approved project terms; recommendations you just accepted are saved as proposed (approve them in the Termbase tab).
2. **Translation memory.** Open `nachbegehung.pdf` or `fucha-baogao.pdf`: the chat reports segments reused with no model call and fuzzy matches adapted; in **Segments**, a fuzzy match shows its diff and Alt+1 inserts it. Confirm a few segments with ⌘/Ctrl+Enter: they go into the TM.
3. **Explain.** In **Segments**, click **explain** on any row: the agent says what the source means in plain English and whether the translation carries it (no edits). **Summarise** above the chat input does the same for the whole document.
4. **Word round trip.** Open `pruefbericht.docx` / `jiance-baogao.docx`: tracked changes are noted, formatting shows as tags; download the translated Word file.
5. **Vendor review.** Download menu → **Import a returned XLIFF…** → `samples/demo/pruefbericht.vendor.en.xlf` (or `samples/demo/zh/jiance-baogao.vendor.en.xlf`).
   - The changes arrive as a proposal, in the chat and **inline in the Segments grid** (untick what you don't want; one change is refused because the vendor dropped a code).
   - Accept: **Quality** shows the planted errors; **Run LQA** fails the document.
6. **Agents fix it.** Next steps → **Fix N QA errors** (the editor proposes fixes), and **Apply termbase** above the chat input (consistency task). Accept; QA is clean; run LQA again.
7. **Alternatives.** Tick two segments → **3 alternatives** → pick one per segment (in the grid or the chat) and accept.
8. **Scan → layout PDF.** Upload `samples/abnahmeprotokoll-scanned.pdf` or `samples/fucha-baogao-scanned.pdf`: **Document → Original layout** shows original and translation side by side.
9. **Exchange and cost.** Download XLIFF 2.0 / 1.2 and the project's TMX/TBX. The chip in the header shows tokens and dollars per step; a two-page document costs about one US cent on the budget models.

Regenerate the German vendor file after changing `pruefbericht.docx`: `uv run python scripts/make_vendor_xliff.py ../samples/pruefbericht.docx ../samples/demo/pruefbericht.vendor.en.xlf` (the Chinese one comes from `make_samples.py`).

## Known limitations / next steps

- Layout-preserving PDFs of scans need the layout server (PP-OCRv5); without it, only PDFs with a text layer get one. On scans, the paint-over is a flat colour, so stains or paper texture under a line become a plain patch. Text inside images (diagram labels) keeps its original language in the PDF, and its translation appears as a legend in the reflowed exports. Re-typeset text uses Noto Sans (plus a CJK fallback), not the document's original font.
- Figures keep their original pixels: text inside an image is translated as a legend, not redrawn into the picture. Without the layout server, vector diagrams in PDFs with real text aren't detected, and figure boxes on scans depend on the vision model.
- English is the only target language (the multilingual projects of M6 were removed on purpose).
- One run per document at a time. Runs live in the API process: they survive browser disconnects but not a server restart. An interrupted document shows a **Retry** button, which restarts ingest but reuses the pages already read (OCR is cached per page). A paused question step does survive a restart, because it is stored in the session DB.
- Quality depends on the models. With a small local model (tested with an 8B Gemma 4 on Ollama), the OCR checker can miss a plausible word substitution on scans without a text layer. PDFs with a text layer are cross-checked against it, which catches these. For scans, a stronger vision model for `OCR_MODEL` / `OCR_CHECK_MODEL` is the biggest quality lever.
- Questions before translating come from the analysis; terms the translator still can't resolve pause once more after the draft. Terms flagged during review or chat don't pause anything: they appear as cards that you answer through the editor, which proposes the resulting edits for your approval.
- The analysis reads up to `ANALYSIS_CHUNK_CHARS` (40,000) characters per call; longer documents are analysed in parts, each seeing the brief so far.
- Translation runs pages in order, so it has no cross-page parallelism. With a local model at `MAX_CONCURRENCY=1` that costs nothing; with a hosted model, long documents are slower than with the old parallel batches. OCR and review still run in parallel.
- Office: PowerPoint charts and SmartArt, Word comments, and Excel comments and chart titles aren't translated yet. A Word span inside a hyperlink takes the link's formatting. XLIFF 1.2 is generic: Trados SDLXLIFF confirmation levels (`sdl:conf`) and memoQ's own status attributes aren't read. The XLIFF output hasn't been validated against the OASIS schemas.
- LQA scores are per 1000 source words, so on very short documents a single error swings the score a lot (one major error in 100 words = 50 points).
- No auth; everything runs as a single local user.

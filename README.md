# Agentic Translator

Upload a document in any language, get a reviewed **English** translation as a versioned artifact, then keep refining it by chatting. Every change is diffable.

**The full feature reference is [docs/FEATURES.md](docs/FEATURES.md).** In short:
- **Formats:** PDF (text layer or scanned), images (PNG, JPG, WebP) and text (.txt, .md).
- **Agentic pipeline:** OCR with verification → **a source check** (fix the reading by chatting, before anything is translated) → **whole-document analysis** (brief and key terms fixed up front) → **questions before translating**, explained in plain English with English options and a recommendation, so they can be answered without knowing the source language → translation page by page with carried context → review ⇄ refine by a second model → consistency polish.
- **Projects:** a style guide, a termbase with forbidden variants and a translation memory (101% / 100% / fuzzy) with concordance search.
- **Segment editor:** a CAT-style grid with human-only statuses, keyboard shortcuts, a TM panel, term highlighting, comments, locks and versions.
- **Chat and tasks:** a chat editor (also explains source passages in plain English) and one-click tasks (rewrite, alternatives, consistency fixer). Agents only ever *propose*; you accept or reject, in the chat or right in the segment grid.
- **Quality:** automatic QA checks, find & replace, and MQM-based LQA scoring with a review queue.
- **Output:** a Word document (DOCX, reflowed: headings, lists, tables, figures, running header and footer with page-number fields) and Markdown (a zip with the figures when there are any).
- **Operations:** a step bar for runs, a run queue, retries on rate limits, a token chip, and models set in two YAML files: any OpenAI-compatible server for each step (custom headers and request fields, headers passed on from the API request, errors logged with the server's message).

Sample documents (German and Chinese PDFs and scans, plus a one-page report in 21 more languages, from Spanish to Thai, Arabic and Japanese) are described in [samples/SAMPLES.md](samples/SAMPLES.md); a hands-on test script is in [docs/TESTING.md](docs/TESTING.md).

Built on **Google ADK 2.x** (`Workflow` graph + `LlmAgent`), FastAPI and Next.js. Pages are read by a **vision LLM** (e.g. Qwen3-VL); **PP-DocLayoutV3**, served through an **MCP tool**, finds the pictures on each page.

## Architecture

```
Next.js UI ── REST + SSE ──► FastAPI ──► ADK Runners ──► sessions (SQLite) + artifacts (disk)
 sidebar · project pages      │                         projects.db (projects, termbase, TM)
 chat · step bar · questions  │
 proposals · next steps       ├─ ingest Workflow (once per upload)
 document panel: segments,    │    START → ocr → check_source → analyse → ask → translate → clarify → review ─┬─(refine)→ refine → review
   document, quality,         │                                                                               └─(done)──→ polish → finalize
   history, source & notes    ├─ ops Workflow (tasks: rewrite, alternatives, consistency, LQA)
                              └─ editor LlmAgent (each chat turn; tools stage a proposal)
```

| Node / agent | What it does |
|---|---|
| `ocr` | Fans out over pages (`ctx.run_node`, concurrency-capped); text files are read as they are. **`ocr_reader`**, on the `ocr` step's vision model, transcribes each page into markdown, with the pictures outlined in red and numbered on the page image so it writes `[[FIGURE n]]` in their place; the text inside each picture is read from its crop. Then **`ocr_checker`**, on the `ocr_check` step's vision model, compares the page with the image (and the PDF text layer), and its corrections go through a guard (`ocr/guard.py`): small fixes inside a word, or ones the text layer confirms, are applied; changed numbers, other words and added or dropped text are listed as *possible misreadings* for a person instead (on scans, changes to Chinese, Japanese and Korean characters too, since one character can be another word). The check is skipped when the reading is the same text as the PDF's own text layer on a page without pictures (`OCR_CHECK=auto`). Each page's result is cached as an artifact, so **Retry** doesn't read pages again. |
| `ocr` → figures | Figures are the PDF's embedded images plus the pictures, charts and seals PP-DocLayoutV3 finds (the layout server's `detect_layout` MCP tool, see below); without the layout server, the embedded images only. Each is cropped from the page, `[[FIGURE n]]` sits where it appears, and the text read inside it is kept as the figure's translatable legend. In PDFs with real text, the marker is moved right before the text printed below the picture. |
| `check_source` | **Human-in-the-loop, before anything is translated:** every PDF and image **pauses** after reading (status `awaiting_source_check`). You compare the reading with the page images and describe problems in the chat; the editor proposes a **page fix** (the page's source as OCR markdown, before/after, with the words it adds or removes and the passages it moves), which you accept or reject. Accepting re-splits the page into segments. **Continue to translation** resumes the workflow; undecided page fixes are dropped. Text files don't pause. |
| `analyse` | Reads the **whole document** before translating (`analyst`, in parts of `ANALYSIS_CHUNK_CHARS`): writes the brief up front, including abbreviations and defined terms wherever they are defined, and lists up to `ANALYSIS_MAX_TERMS` key terms with a plain-English meaning and English options. Clear terms go straight into the running termbase; terms whose options differ in meaning (at most `MAX_QUESTIONS`) become questions. Terms already in the glossary or project termbase are skipped. If the analysis fails, translation goes ahead as before. |
| `ask` | **Human-in-the-loop, before translating:** if the analysis has questions, the workflow **pauses** once. Each question carries the meaning, the sentence (source and English gist), 2–3 English options with notes, and the recommendation (preselected). An answer is a glossary entry, so the first draft already uses it, and a project term: **approved** if the person chose it, **proposed** (a suggestion, not enforced) if they just accepted the recommendation. A skipped question keeps the recommendation for this document only. |
| `translate` | Runs the **TM pass** first: 101% and 100% matches are filled in with no model call, and fuzzy matches become references in the prompt. Then it translates **page by page, in order** (segment `p3.2` = page 3, block 2). A page over `PAGE_MAX_CHARS` is split into parts. Each call carries the document brief, the previous text (`CARRY_CONTEXT_CHARS` of source and translation), the running termbase, the project's matching terms and the style guide. `translator` returns the segments, term choices to keep (these go into the running termbase), terms it is unsure about and the updated brief, as schema JSON or tags. Saves **v1**. |
| `clarify` | Pauses again only for terms the translator still couldn't resolve (at most `MAX_QUESTIONS_PER_BATCH` per page; terms the analysis decided aren't asked twice). Answers go into the glossary, the affected segments are re-translated, and a version is saved. |
| `review` / `refine` | Flags and QA errors become forced issues. `reviewer` lists issues per page with an MQM category and severity (minor/major/critical) and a QE score per segment, sees the document brief, and also checks consistency with the termbase. It may challenge a termbase choice it thinks is wrong rather than enforce it. The `refine` route sends the flagged segments to `refiner`. The loop repeats up to `REVIEW_MAX_ROUNDS`, and stops early if a refine pass changes nothing. Point the `review` step (`config/pipeline.yaml`) at a different model than `translate` for a second opinion. 100% TM matches are only refined for major issues, never for style. Terms the reviewer finds unclear become non-blocking question cards — only when it recommends something different from the translation, and closed if the refiner applies it anyway. |
| `polish` | The consistency fixer on the AI draft: one translation per repeated sentence (a person's confirmed translation wins) and the termbase applied, directly (on a finished document the same fixer only proposes). |
| `finalize` | Saves the reviewed version and marks the document ready; the UI shows next-step buttons. |
| `ops` | Tasks started from the UI (`POST …/tasks`): `dispatch` routes to `rewrite` (an instruction, or n alternatives per segment), `consistency` (groups found without a model; a person's confirmed translation wins with no model call) or `assess` (LQA). Rewrites and fixes are staged as a proposal. |
| `editor` | Chat agent with tools: `search_segments`, `get_segments`, `update_segment`, `propose_alternatives`, `replace_in_translation` (case-insensitive and case-preserving), `set_glossary_term`, `run_qa_checks`, `add_comment`, `resolve_question`, `ask_user_about_term`, `fix_source_segment` (one segment, after the source check), `inspect_page_layout` (runs PP-DocLayout on a source page and compares the result with that page's segments). During the source check: `get_page_source` (a page's source as OCR markdown), `propose_page_source` (the editor rewrites the page's structure itself) and `reread_page` (the vision model reads the page image again, with an instruction taken from what you said); these two stage a **page fix** per page, which you accept or reject. Edit tools **stage** changes in `doc:proposal` instead of applying them. Reads return the proposed text, so follow-up turns can refine a pending proposal. `POST …/proposal/accept` applies it as a new version; `…/reject` discards it. |

**Where things are stored:**
- **Project database** (`data/projects.db`, SQLite in WAL mode): projects, termbase and TM, shared across documents. ADK state is per-document and has no indexes, so it can't hold a TM. A document links to its project through `doc:project_id`; a deleted project leaves old documents working, without project data.
- **Session state:** the document. Each segment has its own key (`seg:<id>`), so an edit produces a small state delta. The glossary, termbase, pending proposal, questions, versions and OCR/review reports are stored there too.
- **Artifacts:** the uploaded source file and `translation.json`. Every version of `translation.json` is kept as an ADK artifact version.

**Glossary vs termbase.** The *glossary* is what you confirmed: clarify answers and accepted glossary proposals. It always wins. The *termbase* holds the translator's own choices from earlier pages, which keeps later pages consistent. Those choices are unverified, so a wrong early choice can repeat on later pages. Terms the translator flagged as uncertain are never added. A glossary entry for the same term replaces the termbase entry. Review the termbase in **Checks & glossary**; each row has a **Change** action that drafts the chat request to fix it everywhere.

The editor runs with `include_contents='none'`. Its instruction is built from the document, the glossary and a compact transcript of the chat, so the pipeline's bulky outputs never reach its context.

## Code layout

```
backend/
  config/            models.example.yaml (copy to models.yaml) · pipeline.yaml
  translator/
    config.py        settings from .env (non-model)
    languages.py · text.py · projects.py (project store: projects, termbase, translation memory)
    models/          config.py (models.yaml / pipeline.yaml) · llm.py (calls, errors, request_headers) · structured.py (JSON schemas) · replies.py (tag-format parsers)
    document/        pages.py (PDF/image/text pages, figures, markdown → segments) · state.py · edits.py (human edits, comments, confirm) · proposals.py · versions.py · source_check.py · find_replace.py
    ocr/             layout.py (PP-DocLayoutV3 MCP client) · guard.py (which OCR-check fixes are safe)
    quality/         qa.py · lqa.py (MQM scoring)
    exports/         __init__.py (DOCX / Markdown downloads) · docx.py
    integrations/    dictionary.py
    agents/          pipeline.py (the workflow graph) · steps/ (read, analyse, questions, translate, review, finish) · workers.py (every single-turn LLM agent and its step) · common.py · prompts.py · editor.py + editor_tools.py (chat) · tasks.py · lqa.py
    api/             main.py (app, middleware incl. header forwarding) · services.py (stores, runners, helpers) · routes/ (meta, documents, chat, segments, source_check, projects) · runs.py · timeline.py · usage.py · downloads.py
  tests/             tests/config/ points every model at a port nothing listens on (tests never call a real model)
  scripts/           sample generators · seed_demo.py (demo projects with termbase and translation memory)
frontend/src/
  app/page.tsx       the workbench: sidebar, chat, document panel
  components/        chat/ (chat, questions, proposals, source check, step bar) · document/ (document panel, quality, diffs,
                     downloads) · cat/ (segment grid, find & replace, TM panel, usage) · projects/ · shell/ (sidebar, upload)
  lib/               api.ts (backend calls) · types.ts
layout-server/       PP-DocLayoutV3 as an MCP tool (its own environment)
dictionary-server/   a dummy dictionary API for development
```

## Layout server (PP-DocLayoutV3 as an MCP tool)

`layout-server/` is a separate uv project, because PaddlePaddle is heavy (~800 MB). It finds the pictures on pages. It exposes one MCP tool:
- `detect_layout(image_base64, threshold)` returns labelled regions (`doc_title`, `paragraph_title`, `text`, `table`, `image`, `chart`, `seal`, `header`, `footer`, …) as pixel boxes. The pictures, charts and seals become figures during OCR; the editor's `inspect_page_layout` tool uses it too.

- **Startup:** the backend starts the server automatically over stdio through ADK's `McpToolset`. The first call loads the model (~16 s, plus a one-off download); after that it takes under a second per page on an Apple Silicon CPU.
- **Without it:** figures come from the PDF's embedded images only. A blank `LAYOUT_SERVER_DIR` turns it off.
- **Reuse:** any MCP client can use the same server, for example `uv run --project layout-server python layout-server/server.py`, or `tools=[layout_toolset()]` on an ADK agent.
- **Configuration:** `LAYOUT_MODEL` (default `PP-DocLayoutV3`) is `detect_layout`'s model. `LAYOUT_MODEL_DIR` points at model files you already have (a folder of model folders like `~/.paddlex/official_models`, or the model's own folder) instead of downloading them; see [layout-server/README.md](layout-server/README.md#model-files). `FIGURE_DETECTION=auto|off` keeps or drops figures.

```bash
cd layout-server && uv sync      # one-time install
```

## Dictionary service

Key terms can be looked up in a dictionary service: any HTTP endpoint answering a small JSON contract
(`POST {"terms": [...], "source_lang": "fr", "target_lang": "en"}` → `{"results": {term: [{translation, definition,
domain, source, url}]}}`), set with `DICTIONARY_URL` (plus `DICTIONARY_API_KEY` / `DICTIONARY_HEADERS`). The analysis
looks up all key terms in one call and shows the entries on the question cards (a dictionary translation it didn't
offer becomes an option); the chat editor gets a `look_up_term` tool. `dictionary-server/` is a dummy implementation
(`python3 dictionary-server/server.py`); put an adapter in front of IATE, Wiktionary or a commercial API to use a real
one. See [dictionary-server/README.md](dictionary-server/README.md).

## Running it

**Requirements:** [uv](https://docs.astral.sh/uv/), Node 20+, and models on any OpenAI-compatible server: your own [vLLM](https://docs.vllm.ai) or SGLang servers, or a hosted service such as OpenRouter. The OCR steps need a **vision** model and the chat editor needs **tool calling** (see [Models](#models)). The example config uses OpenRouter; the backend uses port 8000.

```bash
# backend
cd backend
uv sync
cp config/models.example.yaml config/models.yaml   # the models (see "Models")
cp .env.example .env                               # then put the API key in .env (OPENROUTER_API_KEY for the example)
uv run uvicorn translator.api:app --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                 # http://localhost:3000
```

Sample PDFs in `samples/`, each with an image-only `-scanned.pdf` copy:
- German: `abnahmeprotokoll.pdf` (an acceptance report with a table) and `wartungsbericht.pdf` (a maintenance report with a labelled diagram).
- Chinese: `yanshou-baogao.pdf` (an acceptance report with a table and a diagram labelled in Chinese).
- Source check: `review/pruefvermerk-zweispaltig-scanned.pdf` (German) and `review/jianli-tongzhi-shuanglan-scanned.pdf` (Chinese) are two-column scans with a paragraph running across the column break and a red stamp or seal over the text, for fixing the reading in the chat before translating.
- TM demo: `nachbegehung.pdf` is a follow-up inspection of the same substation, with a running header and a "Seite x von 2" footer. Several paragraphs repeat `abnahmeprotokoll.pdf` word for word, and one differs by a single word. Translate `abnahmeprotokoll.pdf` in a project, confirm it in the Segments tab, then translate `nachbegehung.pdf` in the same project: the exact matches are reused without a model call, and the fuzzy ones are offered to the translator.

Languages written without spaces (Chinese, Japanese, Thai, …) are handled throughout: find/replace matches inside sentences, Chinese text counts double toward the "has a text layer" check, and downloads with non-ASCII names use an RFC 5987 filename.

## Models

Models are set in two YAML files in `backend/config/`. `backend/.env` holds only the secrets they refer to, plus the non-model settings.

- **`models.yaml`** lists the models. Copy it from `models.example.yaml` (committed); `models.yaml` is git-ignored, so a key or an internal server address typed into it is never committed. Each model has:
  - `id`: what `pipeline.yaml` refers to;
  - `model_name`: the name the server knows the model by;
  - `url`: any OpenAI-compatible base URL (vLLM, SGLang, OpenRouter, Ollama, LM Studio…);
  - `api_key`: sent as `Authorization: Bearer …`;
  - optional: `headers` (added to `defaults.headers`; the same name wins), `extra_body` (extra request fields, e.g. `chat_template_kwargs`), `timeout`, `retries`, `temperature`, and `structured_output` (`true`: JSON-schema answers; `false`: a tag format).

  `defaults` apply to every model; a model's own values win.
- **`pipeline.yaml`** (committed; only ids, no secrets) says which model does each step: a `default`, plus `steps`.
- **`${NAME}`** in either file is an environment variable from `backend/.env`; `${NAME:-}` may be unset. `MODELS_FILE` and `PIPELINE_FILE` in `.env` point at other files.

```yaml
# config/models.yaml
defaults:                 # every model gets these; a model's own values win
  headers: {}             # sent with every request to every model, e.g. X-Gateway-Token: ${GATEWAY_TOKEN}
  forward_headers: []     # headers of the API request that starts a run, passed on to all its model calls, e.g. [X-Request-Id, X-Tenant-Id]
  timeout: 180            # seconds per call
  retries: 5
  temperature: 0.2
models:
  - id: qwen-flash
    model_name: qwen/qwen3.8-flash
    url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
  - id: claude-haiku
    model_name: anthropic/claude-haiku-5.5
    url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}

# config/pipeline.yaml
default: claude-haiku     # every step not listed below
steps:
  ocr: qwen-flash
  ocr_check: qwen-flash
  review: qwen-flash
  lqa: qwen-flash
```

| Step | What it does | Needs |
|---|---|---|
| `ocr` | Reads each page image, the text inside pictures, and pages read again in the source check | vision |
| `ocr_check` | Compares the reading with the page image | vision |
| `analyse` | Brief, key terms and the questions before translating | |
| `translate` | The translation, page by page | |
| `review` | A second model reviewing the translation; ideally a different model than `translate` | |
| `refine` | Fixes what the review found | |
| `polish` | Consistency fixes before Ready, and the consistency task | |
| `rewrite` | Tasks: rewrite with an instruction, alternatives | |
| `editor` | The chat (it also makes the source check's page fixes) | tool calling |
| `lqa` | Independent quality scoring (MQM) | |

A step can also be a mapping: `{model: <id>, extra_body: {...}, temperature: ...}`. Its `extra_body` is added to the model's, e.g. `review: {model: <id>, extra_body: {thinking_token_budget: 2000}}` caps a reasoning model's hidden thinking on vLLM. The server needs `--reasoning-parser` (e.g. `qwen3`); a server without one gets the call again without the budget.

**Your own vLLM servers:** add each model with its `url`, `model_name` and `api_key` in `models.yaml`, then point the steps at it in `pipeline.yaml`:

```yaml
# models.yaml — the server: vllm serve Qwen/Qwen3-VL-8B-Instruct --port 8100 --api-key … --enable-auto-tool-choice --tool-call-parser hermes
  - id: qwen-vl
    model_name: Qwen/Qwen3-VL-8B-Instruct     # as GET <url>/models lists it
    url: http://gpu-1:8100/v1
    api_key: ${VLLM_API_KEY:-}

# pipeline.yaml
default: qwen-vl
```

- **Headers:** every model request gets headers from three places, later ones winning: `defaults.headers`, the model's own `headers`, and the run's headers. `defaults.forward_headers` copies the named headers of the API request that started the run; integration code can add more with `translator.models.llm.request_headers({...})` (a context manager; runs started inside it keep them). Only the named headers are forwarded, never the caller's other headers (e.g. their `Authorization`).
- **Mistakes in the files** are reported when the backend starts, with the file and what's wrong: an unknown model id, a step without a model and no `default`, a misspelt field, a `${NAME}` that isn't set, or a missing `models.yaml` ("copy models.example.yaml to models.yaml").
- **Errors:** a failed call is logged as `vLLM error — <step> model <name> at <url>: <server message>`, and a run that stops shows the same text. The analysis and the final consistency pass never stop a run: if their call fails, the chat says so with the same error (for a context-length error, with a pointer to `ANALYSIS_CHUNK_CHARS`) and translation goes on. The log never includes keys, header values or credentials in the URL.
- **Retries:** calls retry with exponential backoff on rate limits and API errors (`retries`, default 5) and time out after `timeout` (180 s) instead of hanging on a stalled connection.
- **Structured output:** pipeline agents reply in JSON that follows a schema (vLLM's guided decoding). A model with `structured_output: false` gets simple tag formats (`<seg id="…">`) instead, which small models also handle reliably.

## Tests

```bash
cd backend && uv run pytest
```

`tests/test_analysis.py` covers the workflow upgrades: the whole-document analysis pausing for questions before any translation (options, meaning, gist; the answer shapes the first draft and becomes an approved project term), skipped questions keeping the recommendation, the translator and reviewer not re-asking decided terms, the OCR check skipped only for identical text (a changed digit, word or minus sign still checks), per-page OCR reused on retry, the consistency polish, and paused-run detection when interrupt ids repeat. `tests/test_source_check.py` covers the source check: a scan stops after reading and **Continue** translates it, a page fix the chat proposes re-splits the page when accepted, a fix that changes words says so (markup isn't a word change, a dropped picture is), page fixes only during the source check, and reading a page again with an instruction. `tests/test_ops.py` covers alternatives in proposals (with a choice when accepting), the rewrite task (locked segments skipped, JSON mode), the consistency task (confirmed translations win without a model call, same-source and termbase groups), comments, migrating a multilingual database to English only, the English-only project API, and the run queue. `tests/test_llm.py` covers the model files: each step calls the model `pipeline.yaml` gives it, secrets come from the environment, a wrong config says which file and what, a missing `models.yaml` points to the example, the shipped example and `pipeline.yaml` are valid, configured and forwarded headers reach every model request, the thinking budget with and without a reasoning parser, and error messages without credentials. `tests/test_exports.py` covers the Word download (structure, language, figures, East Asian font, running header and footer with page-number fields) and the Markdown zip with figures. `tests/test_qa.py` has a table of cases for each QA check, plus ignore fingerprints, forced review issues and find & replace (preview, case, regex, CJK, locked segments, one version). `tests/test_lqa.py` covers MQM arithmetic, word counts, tolerant parsing, the LQA run in tag and JSON modes, and a pipeline run where a dropped date is forced through review and fixed. `tests/test_projects.py` covers the project store (TM scoring for 101/100/fuzzy and CJK, term matching, merging), the pipeline's TM pass against a seeded memory (exact matches skip the model, fuzzy ones reach the prompt), TM write-back on human confirmation (one by one only), adding TM units in bulk, and the project API. `tests/test_chinese.py` covers Chinese segmentation, text layers, find/replace without spaces, download names, and a full Chinese → English run (figure placement, clarify, termbase). `tests/test_layout_integration.py` runs the real PP-DocLayout MCP server; it is opt-in (`RUN_LAYOUT_TESTS=1 uv run pytest`).

`tests/test_flow.py` runs the real workflow and editor against a scripted fake model. It covers:
- OCR fan-out with a checker correction
- language auto-detection
- the clarify pause and resume
- glossary re-translation
- the review → refine loop
- an editor tool call creating a new version
- rebuilding the timeline

It needs no network access and finishes in about 2 seconds.

The tests read their models from `tests/config/`, which points every step at a port nothing listens on, so they never call a real model (or read your `models.yaml`).

## API

| Method | Path | |
|---|---|---|
| `GET` | `/api/config` | the model of each step, languages, whether a dictionary is set up |
| `GET` / `POST` | `/api/sessions` | list / upload a document to translate into English: PDF, image (PNG, JPG, WebP), TXT or MD (multipart: `file`, `source_lang`, optional `project_id`, which sets the source language); upload starts the ingest workflow |
| `GET` / `DELETE` | `/api/sessions/{id}` | summary + document state (including `source_fixes`, the pending page fixes) + chat timeline |
| `GET` | `/api/sessions/{id}/stream` | SSE for the active run; replays its buffered events, so you can reconnect at any time |
| `POST` | `/api/sessions/{id}/clarifications` | `{answers: {q1: {"target": "cable tray", "note": ""}, q2: null}}`: resumes the paused workflow (`target` = the English term to use, `note` = an explanation; `null` = keep the recommendation) |
| `POST` | `/api/sessions/{id}/source/fixes/{page}/accept` | accept the pending page fix for a page during the source check: the page is split into segments again (nothing is translated yet) |
| `POST` | `/api/sessions/{id}/source/fixes/{page}/reject` | discard it |
| `POST` | `/api/sessions/{id}/source/continue` | end the source check and translate; undecided page fixes are dropped |
| `POST` | `/api/sessions/{id}/retry` | re-run ingest after a failure or server restart |
| `PATCH` | `/api/sessions/{id}/segments/{seg}` | `{target?, confirm, base_target, role: translator\|reviewer}`: human edit and/or confirm. 409 if agents are running, the segment is locked, or `base_target` is stale |
| `POST` | `/api/sessions/{id}/segments/{seg}/lock` | `{locked}` |
| `GET` | `/api/sessions/{id}/segments/{seg}/tm` | top 5 TM matches for a segment (101 / 100 / fuzzy) |
| `POST` | `/api/sessions/{id}/segments/confirm` | `{ids?, role}`: bulk confirm (translator: AI-checked drafts) or mark reviewed (reviewer: confirmed segments) |
| `POST` | `/api/sessions/{id}/versions` | save pending human edits as one version |
| `GET` | `/api/sessions/{id}/usage` | tokens per pipeline step and model |
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
| `GET` | `/api/sessions/{id}/export?format=docx\|md&version=&field=` | download a version: `docx` is the Word document (reflowed); `md` is Markdown, a zip when the document has figures |
| `GET` | `/api/sessions/{id}/export/formats` | the download formats |
| `GET` / `POST` | `/api/projects` | list / create `{name, source_lang, instructions, auto_confirm_context, lqa_threshold}` (the target is always English) |
| `GET` / `PATCH` / `DELETE` | `/api/projects/{pid}` | with counts of documents, terms and TM units; `PATCH` takes the same fields as create; deleting removes the termbase and TM and keeps the documents |
| `GET` / `POST` | `/api/projects/{pid}/terms` | list / add a term (an existing source is merged) |
| `PATCH` / `DELETE` | `/api/projects/{pid}/terms/{tid}` | edit (replaces fields; 409 on a duplicate source) / delete |
| `GET` | `/api/projects/{pid}/tm?q=` | concordance search (most recent units without `q`) |
| `POST` | `/api/projects/{pid}/tm` | `[{source, target, origin?}]`: add TM units (a unit with the same source is updated). Returns `{added, updated}`. Used by the demo seeder; an integration point |
| `DELETE` | `/api/projects/{pid}/tm/{uid}` | delete a TM unit |

## Demo

A 15-minute walkthrough for translators and agencies; the full hands-on test script (every feature, German and Chinese, with what each source says) is [docs/TESTING.md](docs/TESTING.md). The backend and frontend should be running; for the scan step, so should the layout server (`cd layout-server && uv sync` once), which finds the pictures on pages.

```bash
cd backend
uv run python scripts/make_samples.py              # (re)generate the Chinese and agentic test samples
uv run python scripts/seed_demo.py --reset --upload
```

This creates two projects, each with a style guide, a termbase with forbidden variants and a translation memory, uploads one document into each, and lists more files to try:
- **Acme Energie – Umspannwerk Nord** (German → English): `nachbegehung.pdf`.
- **北区变电站改造 – UW-2291** (Chinese → English): `fucha-baogao.pdf`.

Every PDF stops after reading for the source check (step 6): press **Continue to translation** to go on.

1. **Questions before translating.** Upload `samples/vertragsauszug.pdf` into the German project, or open `fucha-baogao.pdf` in the Chinese one.
   - The step bar shows Read → (Check →) Analyse; the analysis reads the whole document first (the brief already knows what AG/AN or 三措一案 mean, though they are only defined later).
   - The questions explain each term in plain English, show the sentence in English, and preselect a recommendation. **Accept all recommendations & continue**, or pick another option.
   - The first draft already uses your answers (no re-translation pass). Terms you chose become approved project terms; recommendations you just accepted are saved as proposed (approve them in the Termbase tab).
2. **Translation memory.** Open `nachbegehung.pdf` or `fucha-baogao.pdf`: the chat reports segments reused with no model call and fuzzy matches adapted; in **Segments**, a fuzzy match shows its diff and Alt+1 inserts it. Confirm a few segments with ⌘/Ctrl+Enter: they go into the TM.
3. **Explain.** In **Segments**, click **explain** on any row: the agent says what the source means in plain English and whether the translation carries it (no edits). **Summarise** above the chat input does the same for the whole document.
4. **Quality, and agents fix it.** **Quality** lists the QA issues; **Run LQA** scores the document. Next steps → **Fix N QA errors** (the editor proposes fixes), and **Apply termbase** above the chat input (consistency task). Accept; run LQA again.
5. **Alternatives.** Tick two segments → **3 alternatives** → pick one per segment (in the grid or the chat) and accept.
6. **Fix the OCR before translating.** Upload `samples/review/pruefvermerk-zweispaltig-scanned.pdf` (German) or `samples/review/jianli-tongzhi-shuanglan-scanned.pdf` (Chinese): after reading, the run stops at **Check** with *Check the source before translating*.
   - Compare the reading with **Source & notes → Page images & OCR**: the paragraph running across the column break, the running header, the red stamp or seal.
   - Say what's wrong in plain words, e.g. *"Section 3 (Messwerte) got split in two at the column break: it ends with "Fehlerstrom-" and goes on with "Schutzeinrichtung wurde…" — it is one paragraph. The running header also appears twice at the top; keep only the header line. And the red stamp over section 4 is missing: it says "GEPRÜFT 14.03.2026 · Bauleitung UW-2291" — add it as its own line after section 4."* The chat proposes a page fix: before/after, plus the words it adds or removes and the passages it moves.
   - Check the word list and any moved passages against the page image, **Accept**, then **Continue to translation**. Prompts that worked are in [docs/TESTING.md](docs/TESTING.md).
7. **Download.** Download menu → the Word document (reflowed, with the running header and footer) or Markdown. The chip in the header shows the tokens used per step.

## Known limitations / next steps

- Downloads are reflowed (Word, Markdown): the original page layout isn't reproduced.
- Figures keep their original pixels: text inside an image is translated as a legend, not redrawn into the picture. Figures are the picture, chart and seal blocks PP-DocLayoutV3 finds (plus pictures embedded in the PDF).
- English is the only target language (the multilingual projects of M6 were removed on purpose).
- One run per document at a time. Runs live in the API process: they survive browser disconnects but not a server restart. An interrupted document shows a **Retry** button, which restarts ingest but reuses the pages already read (OCR is cached per page). A paused question step does survive a restart, because it is stored in the session DB.
- OCR quality: per-language results are in [samples/SAMPLES.md](samples/SAMPLES.md#ocr-measured). The vision LLM can swap an unclear word for a plausible one (on Thai, a place name), and on two-column scans it can split a paragraph at the column break, drop a stamp's text or miss headings and running headers: that's what the source check is for. The guarded check fixes small misreadings; on scans without a text layer, changes to Chinese/Japanese/Korean text and to numbers are only listed, never applied.
- Questions before translating come from the analysis; terms the translator still can't resolve pause once more after the draft. Terms flagged during review or chat don't pause anything: they appear as cards that you answer through the editor, which proposes the resulting edits for your approval.
- The analysis reads up to `ANALYSIS_CHUNK_CHARS` (40,000) characters per call; longer documents are analysed in parts, each seeing the brief so far.
- Translation runs pages in order, so it has no cross-page parallelism. With a single small GPU at `MAX_CONCURRENCY=1` that costs nothing; with spare capacity, long documents are slower than with the old parallel batches. OCR and review still run in parallel.
- LQA scores are per 1000 source words, so on very short documents a single error swings the score a lot (one major error in 100 words = 50 points).
- No auth; everything runs as a single local user.

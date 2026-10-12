# Manual test script

A hands-on checklist for every feature, written for someone who doesn't read German or Chinese: each test says which sample to use, what to do, what you should see, and what the source text means. Tick the boxes as you go and note anything that differs.

The agents run on real models, so wording differs between runs. **Which** terms get asked about can vary too: "expected" questions are the likely ones, and the important thing is that every question can be answered without knowing the source language. Exact counts (TM matches, QA errors) are deterministic and should match.

- **What each sample contains, and its traps:** [samples/SAMPLES.md](../samples/SAMPLES.md).
- **English reference translations:** `samples/reference/*.en.md`. Compare the app's output with these.

---

## 0. Setup

```bash
# backend (terminal 1): the models are in config/models.yaml and config/pipeline.yaml, their keys in .env
# (see "Models" in the README; for your own vLLM server, add it to models.yaml and point the steps at it)
cd backend && uv sync
cp config/models.example.yaml config/models.yaml && cp .env.example .env    # then put the API key in .env
uv run uvicorn translator.api:app --port 8000

# frontend (terminal 2)
cd frontend && npm install && npm run dev        # http://localhost:3000

# layout server (once; finds pictures on pages)
cd layout-server && uv sync

# samples and demo projects (terminal 3)
cd backend
uv run python scripts/make_samples.py              # regenerates the Chinese + agentic samples
uv run python scripts/make_review_samples.py       # regenerates samples/review/ (the source-check scans)
uv run python scripts/seed_demo.py --reset         # two projects: German → English, Chinese → English
```

- [ ] `seed_demo.py` prints:
  - **German project:** `termbase.csv: 12 terms` and `memory.json: 12 translation-memory units added`.
  - **Chinese project:** `termbase.csv: 15 terms` and `memory.json: 9 translation-memory units added`.
  - For each project, a list of files to try.
- [ ] The sidebar shows two projects: **Acme Energie – Umspannwerk Nord** (German) and **北区变电站改造 – UW-2291** (Chinese (Simplified)).

> If you restarted the backend after an upgrade, older projects are migrated automatically: English terms and TM units are kept, other target languages dropped.

---

## 1. Projects

**1.1 Open a project.** Click the Chinese project in the sidebar.
- [ ] Header: *Chinese (Simplified) → English · N documents · 15 terms · 9 TM units*.
- [ ] **Style guide** tab: the formal register, "Client / Contractor, never Party A / Party B", British spelling.
- [ ] **Termbase** tab: 15 entries. Forbidden variants are shown in red, e.g. 甲方 → *Client*, never *Party A*; 电缆桥架 → *cable tray*, never *cable bridge*.
- [ ] **Translation memory** tab: 9 units (the confirmed translation of `yanshou-baogao.pdf`). Search 结论 → finds *3. Conclusion*.

**1.2 Create a project.** In the sidebar, **+** next to Projects. Name it "Test", source French, add a style guide line, then **Create project**.
- [ ] The project opens; its Settings say *French → English*.
- [ ] Settings → untick **Auto-confirm 101% matches**, set the LQA threshold to 95, reload: both changes are kept.
- [ ] Termbase → add a term with a forbidden variant (e.g. `devis` → `quotation`, never `estimate`). It appears in the list.
- [ ] Delete the project (bin icon). Its documents are kept, outside any project.

---

## 2. Upload and the step bar

**2.1 Upload.** Click **New translation**, choose `samples/fucha-baogao.pdf`, Project = the Chinese project, then **Translate**.
- [ ] The form says *Translate a document into English*; "Into" is fixed to English.
- [ ] The chat shows the **step bar**: Read → Check → Analyse → Translate → Review → Ready (a .txt or .md file has no Check step). The current step spins, with page x/y and a timer.
- [ ] The sidebar shows the document under its project with a spinner.
- [ ] After reading, the run stops at **Check**: the sidebar says *Check source*, and the chat shows *Check the source before translating*. Click **Continue to translation** (fixing the source is section 3).

**2.2 Queue.** Upload two more documents quickly (any samples).
- [ ] At most two run at once; the third shows *Queued* until one finishes.

**2.3 Reading a scan.** Upload `samples/abnahmeprotokoll-scanned.pdf`.
- [ ] The chat says *Reading 2 pages with vision OCR + OCR check*.
- [ ] The run stops for the source check (step bar at **Check**): nothing is translated yet.
- [ ] **Source & notes → Page images & OCR**, page 1: the table is a table (Nr. | Beschreibung | Frist), headings are headings.
- [ ] Any *Possible misreadings* box lists changes the OCR check suggested but did **not** make (other words, numbers): compare them with the page image on the left.
- [ ] Upload `samples/fucha-baogao-scanned.pdf`: the running header and the page number become their own segments (*header*, *footer*), the diagram is a figure with its Chinese labels as the legend, and the caption 图1 sits right below it.
- [ ] Click **Continue to translation** on both.

---

## 3. Fixing the OCR before translating

Every PDF and image stops after reading (**Check**) so you can compare the reading with the page images and have the chat fix it. Nothing is translated yet, so a fix loses nothing. The two scans in `samples/review/` are made to be read wrong: two columns with a narrow gutter, a section running from the bottom of the left column to the top of the right one, and a red stamp or seal printed over the text. English references: `samples/reference/pruefvermerk-zweispaltig.en.md` and `samples/reference/jianli-tongzhi-shuanglan.en.md`.

What the model gets wrong differs between runs; the lists below are what a live run with Qwen3-VL-8B (through OpenRouter) returned. The chat's first attempt may need a second message.

**3.1 German: a paragraph split at the column break, and a stamp.** Upload `samples/review/pruefvermerk-zweispaltig-scanned.pdf`.
- *What it is:* an inspection note, *Prüfvermerk – Erdung der Kabelpritsche* (earthing of the cable tray). Section 3 (*Messwerte*, measured values) runs from the bottom of the left column to the top of the right one, and breaks the word *Fehlerstrom-Schutzeinrichtung* (residual-current device) across the columns. A red, turned rubber stamp *GEPRÜFT · 14.03.2026 · Bauleitung UW-2291* ("checked · … · site management") is printed over section 4.
- [ ] The step bar stops at **Check**, and the chat shows *Check the source before translating* with **Continue to translation**.
- [ ] **Source & notes → Page images & OCR**: compare the reading with the page image. Look for:
  - section 3 split into two segments at the column break (*…Fehlerstrom-* / *Schutzeinrichtung wurde…*);
  - the running header twice (once as a paragraph);
  - the stamp's text missing.
- [ ] Type in the chat: *"Section 3 (Messwerte) got split in two at the column break: it ends with "Fehlerstrom-" and goes on with "Schutzeinrichtung wurde…" — it is one paragraph. The running header also appears twice at the top; keep only the header line. And the red stamp over section 4 is missing: it says "GEPRÜFT 14.03.2026 · Bauleitung UW-2291" — add it as its own line after section 4."*
- [ ] One page fix appears on the card: page 1 before and after as a word-level diff, and *Words would change*: the duplicate header removed, the stamp's words added.
- [ ] **Check the word list before accepting.** It lists every word the fix adds or removes, so an added or dropped word you didn't ask for shows up there. (In a live run it caught the editor joining *Fehlerstrom-Schutzeinrichtung* without its hyphen; the editor is now told to keep a word's own hyphen.)
- [ ] **Check the order too.** The word list can't see a wrong reading order: columns stitched the wrong way round keep every word. Each passage the fix moves is quoted under *Text moves*; check where it lands against the page image, or against `samples/reference/pruefvermerk-zweispaltig.en.md` (section 3 runs left column → right column). The green *Only the structure changes* line means the same words in the same order.
- [ ] **Accept**: the page is split into segments again (19 in the live run), with section 3 as one segment.
- [ ] **Continue to translation**: the run goes on to Analyse and translates. The stamp comes out as *CHECKED 14.03.2026 · Site management UW-2291*. Compare with the reference.

**3.2 Chinese: reading the page again.** Upload `samples/review/jianli-tongzhi-shuanglan-scanned.pdf`.
- *What it is:* a supervision notice, 监理通知单——地下室电缆桥架接地 (earthing of the basement cable tray), in two columns. Section 五 (安全措施, safety measures) runs across the column break mid-sentence. A red round seal (北区变电站改造工程监理部 / 监理专用章: Supervision Office, North District Substation Renovation Project / supervision seal) is printed over the attachments line (八、附件) and the signature.
- [ ] Look for:
  - no heading marked as a heading (the title and 一、二、… as paragraphs);
  - the running header not marked as a header;
  - the seal taken as a picture by PP-DocLayoutV3;
  - under the seal, attachment 1 *现场照片8张* (8 site photos) misread as *图纸1张* (1 drawing).
- [ ] Type in the chat: *"Under the red seal, the attachments line (八、附件) looks misread — please read page 1 again and keep the seal out of the text. Keep the title and section headings as headings, and the running header as the header."*
- [ ] The page is read again (the fix says *read again*): attachment 1 is *现场照片8张*, and the headings and the header are marked. Check the word list and any *Text moves* passages against the page image (section 五 should run on from the left column to the right; see the English reference), then **Accept**.
- [ ] **Continue to translation**. Compare with the reference.

**3.3 Rejecting, and when page fixes apply.**
- [ ] Ask for a page fix, then **Reject** it: the page stays as it was read.
- [ ] Ask for a page fix and click **Continue to translation** without deciding: the card says undecided fixes are left out, and the chat says so after continuing.
- [ ] After **Continue**, ask for a source fix: the chat corrects single segments instead (page fixes are only possible during the source check).
- [ ] Upload a text file (.txt or .md): it doesn't stop at Check.

---

## 4. Analysis and questions you can answer (the key new feature)

**4.1 Questions before translating (German).** Upload `samples/vertragsauszug.pdf` into the German project.
- *What it is:* an extract of a construction contract. It uses the abbreviations **AG** (*Auftraggeber*, the client) and **AN** (*Auftragnehmer*, the contractor) from page 1, but defines them only in an annex on page 2.
- [ ] After the source check (**Continue to translation**), the step bar stops at **Analyse** with a question mark: *Waiting for your answers*.
- [ ] Nothing is translated yet: Document → Reading shows *not translated yet* lines.
- [ ] Each question card has:
  - the term;
  - a plain-English meaning;
  - *Why it matters*;
  - the sentence in German with an English gist underneath;
  - 2–3 English options with notes, the recommended one preselected;
  - *Another English term…* and *Or explain what it means here…*.
- [ ] Likely questions: legal terms such as *Werktag* (working day: do Saturdays count?), *selbstschuldnerische Bürgschaft* (a guarantee payable on demand), *Behinderungsanzeige* or *Bedenkenanzeige*. AG/AN are **not** asked: the analysis already knows them from the annex.
- [ ] Source & notes → **Brief, terms & checks**: the brief mentions AG = client and AN = contractor, and the **Key terms** table lists terms with meanings.
- [ ] Pick a non-recommended option on one card. The button changes to **Continue with my 1 change**. Click it.
- [ ] The step bar moves on to Translate. The finished translation uses *the Client* / *the Contractor* from the first paragraph, and your choice for the term you changed.
- [ ] Project → Termbase: your choice appears as an **approved** term, with the meaning as the note. (Questions where you kept the recommendation are saved as **proposed** — see 4.2.)
- [ ] Compare with `samples/reference/vertragsauszug.en.md`.

**4.2 Questions before translating (Chinese).** `fucha-baogao.pdf` in the Chinese project (uploaded in 2.1; after **Continue to translation**).
- [ ] Likely questions, explained in English:
  - **消缺** (utility jargon for "eliminating a defect"; the report also says 整改, rectification, for the same defects);
  - **运维单位** (which party is that? the utility's O&M organisation);
  - **保电** / 高考保电期 (a period of guaranteed supply, here during the college entrance exam: no planned outages).
- [ ] **Accept all recommendations & continue** → the translation runs with no further pause on those terms.
- [ ] Project → Termbase: the accepted terms are **proposed** (not approved), with an **Approve** button. Click **Approve** on one: it becomes approved.

**4.3 Terms defined later are used from the start.** Same document, `fucha-baogao.pdf`.
- *What it is:* page 1 says the re-inspection follows the approved **三措一案** without explaining it; page 2 (§ 四) defines it (the organisational, technical and safety measures and the construction plan for the outage work).
- [ ] No question about 三措一案 (if one is asked, its recommendation already reflects the definition). The brief and the key terms explain it.
- [ ] Page 1's translation uses the same term as the definition on page 2 (the reference: *Three Measures and One Plan*). Compare with `reference/fucha-baogao.en.md`.

**4.4 Skip.** On any document that asks, click **Skip — let the AI decide**.
- [ ] Translation continues. The term isn't in the glossary or the project termbase, but the recommendation is used consistently.

**4.5 Questions after the run.** If a finished document shows *How should this term be translated?* cards (raised by the reviewer):
- [ ] Each one recommends something **different** from the current translation. Cards that only confirm the translation should not appear.
- [ ] **Apply** → the chat editor proposes the edits (a proposal card). **Keep current** dismisses the card.

---

## 5. Translation memory

**5.1 Chinese TM leverage.** Open `fucha-baogao.pdf` (uploaded in 2.1, or upload it now).
- *What it is:* a follow-up inspection that repeats parts of `yanshou-baogao.pdf`, whose translation is in the TM.
- [ ] The chat reports the TM pass: **5 segments reused** with no model call, and **2 fuzzy matches** to adapt. (More once you have confirmed segments in other Chinese documents: confirmed work goes into the TM.)
  - The exact matches are the headings 二、发现的缺陷 and 三、结论, the defects table, the figure caption and the quoted conclusion.
- [ ] Segments tab: those 5 segments show *TM 100%*, and still do after the review: the AI reviewer only changes a 100% match for a major issue.
- [ ] **Date-line trap:** the date line was a fuzzy match from a TM unit dated 14 March 2026, but this report is dated **20 May 2026**. The translation must say 20 May 2026. If it says 14 March, QA flags a date error.
- [ ] The scope paragraph (97% match) talks about the *review* or *re-inspection* (复查), not the *acceptance* (验收) of the stored translation.

**5.2 German TM.** Open `nachbegehung.pdf` (uploaded by `seed_demo.py --upload`, or upload it into the German project).
- [ ] 5 reused, 3 fuzzy.

**5.3 Confirming fills the TM.** In Segments, click into a draft and press **⌘/Ctrl+Enter** on 3 segments.
- [ ] Their status becomes *Confirmed*, and the next draft is focused.
- [ ] Project → Translation memory: 3 more units.
- [ ] Upload the same file again into the project. Those 3 segments are reused (101% if the previous segment is also the same).

---

## 6. Segment editor

Use `fucha-baogao.pdf` or `nachbegehung.pdf` (any translated document works).

- [ ] **Translator / Reviewer** switch: Ctrl+Enter confirms (Translator) or marks *Reviewed* (Reviewer).
- [ ] **Keyboard:** Alt+↓/↑ move between segments; Esc reverts an edit; Alt+S copies the source; Alt+1 inserts the first TM match (when the TM panel shows one).
- [ ] **Terms:** project terms are underlined in the source. Hovering shows the target and the forbidden variants.
- [ ] **Comments:** add a comment as reviewer, resolve it. The **Comments** filter shows open ones.
- [ ] **Lock** a segment: it can't be edited, and agents skip it.
- [ ] **QA issues under the segment:** a segment with a QA problem shows it right under the row (no need to click in): severity, check, message, **Fix** and **Ignore**. Click **Fix** → the chat gets the request and the agent proposes the correction.
- [ ] **Filters:** To do / QA issues / Confirmed / Lowest score first (by AI quality estimate).
- [ ] **Save version (n)** after edits → a new version appears in History.
- [ ] **Confirm AI-checked (n)** confirms every draft that passed the AI review. Bulk-confirmed segments are **not** added to the translation memory (only one-by-one confirmations are): the project's TM count doesn't change.

---

## 7. Explain and summarise (for languages you don't read)

- [ ] On any segment row, click **explain**. The chat answers in plain English:
  - what the source literally says;
  - nuances the translation can't carry;
  - whether the translation renders it faithfully.

  No proposal is created.
- [ ] Above the chat input, click **Summarise**. You get a plain-English summary of the document (purpose, key facts, dates, obligations), with no changes.
- [ ] Type *"explain p1.3"* yourself: same behaviour.

---

## 8. Chat edits and proposals

- [ ] Ask in the chat: *"Use 'earthing' instead of 'grounding' everywhere"* (or any terminology change).
  - A proposal card lists the changes as diffs. Nothing changes until you accept.
- [ ] **Segments** tab: the same changes appear **under each segment** with tick boxes, and a banner offers **Apply all / Reject all**. The tab label shows the number of proposed changes, and the **Proposed** filter shows only those segments.
- [ ] Untick one change in the grid. The chat card shows it unticked too, and the banner says **Apply N selected**.
- [ ] Apply → a new version. History shows the diff.
- [ ] Ask something, then **Reject** → nothing changes.

---

## 9. Agentic tasks

- [ ] **Rewrite:** in Segments, tick 2 segments (shift-click for a range), then **More formal**. A proposal arrives.
- [ ] **Alternatives:** tick 2 segments → **3 alternatives**. Each change offers 3 options with notes; pick one per segment (in the grid or the chat), then accept.
- [ ] **Apply termbase** (chat shortcut) or Quality → **Fix consistency**. Repeated sentences are unified and termbase rules applied, as a proposal.
  - `fucha-baogao.pdf` repeats 乙方应在整改完成后5个工作日内书面通知甲方，并申请复验。 ("The Contractor shall notify the Client in writing within 5 working days…") on pages 1 and 2.

---

## 10. Quality: QA, find & replace, LQA

**10.1 Planting errors.** On a translated `fucha-baogao.pdf`, edit segments in the grid (as Translator):
- the date line: change *20 May 2026* to *14 March 2026*;
- the repeated paragraph on page 1 (*The Contractor shall notify the Client…*): write *Party A* instead of *the Client*.
- [ ] The **Quality** tab shows:
  - a numbers error: the date 2026年5月20日 is missing;
  - a terminology error: forbidden *Party A* (should be *Client*);
  - a consistency warning: the paragraph is now translated two ways (page 1 and page 2).

**10.2 Fix it with the agents.** In the chat, **Next steps → Fix N QA errors** (or the *Fix QA errors* shortcut).
- [ ] The editor runs the QA checks and proposes fixes. Accept them.
- [ ] Then **Apply termbase**, accept. QA errors go to 0 (warnings about heading numbers like "1." may remain; they're benign).

**10.3 QA details.**
- [ ] **Ignore** a warning: it disappears; **Show ignored** brings it back. It returns if the text changes.

**10.4 Find & replace.** Segments → **Replace**: find `retention`, replace `retainage`.
- [ ] The preview lists the changes as diffs. Untick one, then apply: the rest become one new version. Locked segments are skipped.

**10.5 LQA.** **Next steps → Check quality score** (or Quality → Run LQA).
- [ ] A score per 1,000 words, pass or fail against the threshold, a category × severity scorecard, and the review queue (lowest scores first).
- [ ] Run it with the errors of 10.1 in place, and again after the fixes of 10.2: the score rises. After an edit, the scorecard is marked stale.

---

## 11. Downloads

- [ ] Download each format from the menu, and each file opens:
  - **Word document** (`fucha-baogao.pdf`): real headings, the defects table, the figure; the running header (*North District Substation Renovation Project · UW-2291 · Internal*) is Word's header, and the footer (*Page 1 of 2*) shows live page numbers;
  - **Markdown**: a zip with the figure when the document has one.
- [ ] Pick an older version in the version picker and download: the menu says *Exports version vN*, and the file has that version's text.

---

## 12. Robustness

- [ ] **Reload during a run:** the step bar and progress come back.
- [ ] **Retry:** stop the backend while a PDF is in the *Read* step, restart it, open the document and click **Retry**.
  - Pages already read say *reused from the earlier run* in the activity log.
  - The run completes.
- [ ] **Busy server:** if vLLM answers `429` or `503`, the run slows down but completes; the calls are retried with backoff.
- [ ] **Model errors are printed:** stop the vLLM server while a document is translating.
  - The backend log shows `vLLM error — translate model <name> at <url>: … Cannot connect to host …`.
  - The run's error in the app shows the same text.
  - Start the server again and click **Retry**.
- [ ] **Analysis too long for the model:** set `ANALYSIS_CHUNK_CHARS=200000` and start vLLM with a small `--max-model-len` (e.g. 8192); upload a long document. The chat shows *Note: I couldn't read the whole document first…* with the context-length error and the `ANALYSIS_CHUNK_CHARS` hint, and the document is still translated. Restore the setting.
- [ ] **Wrong model name:** in `config/models.yaml`, set a model's `model_name` to `does-not-exist`, restart, upload a file. The log shows `vLLM error — … HTTP 404 NotFoundError: The model `does-not-exist` does not exist.` Restore it.
- [ ] **Mistakes in the model files:** each one stops the backend at startup with the file and what's wrong. Try one at a time, then restore:
  - in `config/pipeline.yaml`, point a step at an id that isn't in `models.yaml`;
  - in `models.yaml`, refer to `${NOT_SET}` (an environment variable that isn't set);
  - misspell a field (e.g. `modle_name`);
  - rename `models.yaml`: the error says to copy `models.example.yaml` to `models.yaml`.
- [ ] **Custom headers:** with `headers: {X-Test: "1"}` under `defaults` in `models.yaml` (behind a proxy that logs headers, or a gateway that requires one), runs complete and the header arrives on every request.
- [ ] **Forwarded headers:** with `forward_headers: [X-Request-Id]` under `defaults`, upload a document with an `X-Request-Id` header (e.g. with `curl -H`). Every model call of that run carries it (check with a proxy that logs headers); the request's other headers (e.g. `Authorization`) are not passed on.
- [ ] **Reviewer thinking cap:** in `pipeline.yaml`, set `review: {model: <id>, extra_body: {thinking_token_budget: 2000}}` for a reasoning model on vLLM. On a server started with `--reasoning-parser`, review takes well under a minute per page. On a server without one, the log shows `vLLM error — review model … refused the thinking budget (…); retrying without it` once, and review continues.
- [ ] **OCR check skip:** on `nachbegehung.pdf` (a clean digital PDF), the activity log may say *matches the PDF's text layer (no second check needed)* for a page. On scans every page says *verified* or *checker fixed…*, plus *possible misreadings to check* when the checker suggested changes that weren't applied.

---

## 13. Layout and navigation

- [ ] The document panel has five tabs:
  - Segments;
  - Document (Reading / Side by side);
  - Quality;
  - History;
  - Source & notes (Page images & OCR / Brief, terms & checks).
- [ ] Switching tabs returns to the last view you used in that tab.
- [ ] Drag the divider between chat and document. The width is kept after a reload.
- [ ] **Widen** hides the chat; again brings it back.
- [ ] In the sidebar, collapse a project with the chevron; the active document's project stays open.
- [ ] The token chip in the document header shows tokens per step (no dollars).

---

## 14. Other source languages

`samples/languages/` has the same one-page acceptance report in 21 more languages (Spanish, French, Italian,
Portuguese, Dutch, Polish, Swedish, Turkish, Russian, Ukrainian, Greek, Arabic, Hebrew, Hindi, Bengali, Indonesian,
Vietnamese, Thai, Japanese, Korean, Chinese (Traditional)). Every one says what
`samples/reference/acceptance-report.en.md` says, so you can check any of them without reading the language.
Use a project without a termbase (or none) and Source = *Auto-detect*. Each PDF stops at **Check** after reading: click **Continue to translation**.

**14.1 A Latin-script language.** Upload `acceptance-fr-scanned.pdf`.
- [ ] Source & notes shows the running header and *Page 1 sur 1* as their own segments, the defects table as a
  table (3 rows), and the diagram as a figure whose legend is its four French labels.
- [ ] The detected language is French.
- [ ] Questions before translating are likely to include *réceptionnée avec réserves* (accepted with reservations,
  a legal term) and *ASI* (the French abbreviation for UPS).
- [ ] The translation matches the reference: 110 kV, item 4.2.7, the three deadlines, week 18, 5%.

**14.2 Right to left.** Upload `acceptance-ar-scanned.pdf` (or `acceptance-he.pdf`).
- [ ] The Arabic text reads in the right order in the Source tab (it is shown in logical order); the table has
  رقم / الوصف / المهلة as its header.
- [ ] The translation matches the reference.

**14.3 Scripts without spaces, and shaped scripts.** Upload `acceptance-th-scanned.pdf`, `acceptance-ja.pdf` and
`acceptance-hi-scanned.pdf`.
- [ ] Thai and Japanese sentences are not broken up by stray spaces; dates read 2026年3月14日 / 14/03/2026.
- [ ] No *punctuation* QA warnings because Thai sentences end without a full stop, or because Hindi ends them with ।.

**14.4 Text layer vs scan.** For a language with both files (e.g. `acceptance-ko.pdf` and `acceptance-ko-scanned.pdf`):
- [ ] The text PDF's pages say *matches the PDF's text layer* or *verified*; the scan's say *verified* or list
  possible misreadings to compare with the image.

---

## Reporting a problem

Note:
- the test number;
- the document and segment id (e.g. `fucha-baogao.pdf p1.4`);
- what you expected and what you saw;
- a screenshot.

The backend log is useful for errors, and **Source & notes → Brief, terms & checks** shows what the agents decided (brief, key terms, review report).

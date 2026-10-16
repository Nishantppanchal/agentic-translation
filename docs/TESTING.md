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
- [ ] The step bar stops at **Check**, and the chat shows *Check the source before translating* with **Continue to translation**. The message lists **where to look first** (on this scan: page 1 is a scan, plus any possible misreadings or seals).
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

**3.3 A picture that is really text.** Any scan with a figure works, e.g. `samples/wartungsbericht-scanned.pdf` (a wiring diagram).
- [ ] The OCR line in the chat says how many figures were kept; if the layout model took a block of text for a picture, it also says *N region(s) taken for a picture read as text*, and the page line in **Source & notes** says *read as text, not as a picture*.
- [ ] In **Source & notes → Page images & OCR**, under the figure: **This is text, not a picture**. Press it (to try the flow; the diagram really is a picture): after a few seconds the chat card shows a page fix marked *picture → text* with the diagram's labels in place of `[[FIGURE 1]]`. **Reject** it.

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

- [ ] Ask: *"Is the seal on page 1 red? What does it say?"* The chat shows *Looked at page 1* and answers from the image: the seal is red. For the seal's own characters it should say it can't read them reliably (or have the page read again), not quote a name: the seal says 北区变电站改造工程监理部 / 监理专用章, and in a test a general model "read" a real company's name there instead.
- [ ] Ask it to add the seal's text to the page: the fix must come from the page being read again (*read again*), never from text the chat typed itself. Text that is neither in the document nor in your message is refused.

- [ ] On a fresh upload of this file, press **Check the pages for me** instead of typing: the chat looks at the page (*Looked at page 1*), says what looks wrong in English, and proposes a fix or has the page read again — check its word list as above.

**3.3 Rejecting, and when page fixes apply.**
- [ ] Ask for a page fix, then **Reject** it: the page stays as it was read.
- [ ] Ask for a page fix and click **Continue to translation** without deciding: the card says undecided fixes are left out, and the chat says so after continuing.
- [ ] After **Continue**, say a word on page 1 looks misread: the chat has the page read again (*Read page 1 again* — nothing changes yet), then proposes a fix for that one segment with the text as read, and its new translation. You never have to type German or Chinese; page fixes are only possible during the source check.
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
- [ ] Project → Translation memory: 3 more units. Each row shows **in TM**.
- [ ] Upload the same file again into the project. Those 3 segments are reused (101% if the previous segment is also the same). A 101% match from a segment you confirmed one by one starts *Confirmed*; one from **Confirm AI-checked** (bulk) starts as a *Draft*.
- [ ] A segment the translator adapted from a fuzzy match is labelled *MT · TM 87%* (its score), not *TM*.

---

## 5b. Word, PowerPoint and Excel

**5b.1 Word.** Upload `samples/jiance-baogao.docx` into the Chinese project.
- [ ] No source check: the chat says *Read the Word document: 51 segments in 2 parts; 2 tracked changes accepted*, plus a note on the tracked changes, and *Read the text in 1 picture* (the wiring sketch). The document opens in **Document → Layout**: the original on the left.
- [ ] After the questions and the translation, the right side shows the English file: same page layout, the table with its grey header row, the bold *main earth grid* and the italic clause, the link on *test plan*, the footnote, the header, and the footer *Page 1*.
- [ ] **Sync scroll:** scroll the left side; the right follows to the same paragraph. Click a paragraph on the right: the Segments tab opens on it.
- [ ] Segments tab: rows say where they are (*Header*, *Table 1 · R2C3*, *Footnote 1*). The footer row reads `第 [^1]1[^2] 页` with chips for the page field.
- [ ] Download → *Translated Word document (original layout)* opens in Word with no revision marks, the footnote and link working, the language English (UK).
- [ ] **The picture:** Reading shows the wiring sketch (p1.10) with its labels in English under it. In the downloaded file, a small italic caption under the sketch lists the labels in English (main transformer, earth grid, …), and the picture's alt text (right-click → *Edit Alt Text*) starts *Text in the picture:*.

**5b.2 PowerPoint.** Upload `samples/anquan-peixun.pptx`.
- [ ] Layout shows the slides side by side; the speaker notes of the current slide are underneath, original and translation.
- [ ] Slide 4's slogan box (安全第一、预防为主、综合治理) is far longer in English: in the translated slide it shrinks to fit; the chip lists *Shrunk to fit*.
- [ ] 五防 / 两票三制 on slide 1 read the same as their definitions on slides 3 and 4.
- [ ] **The picture:** slide 2's safety sign (p2.6) is read and translated (*Stop! High voltage danger!*). In the downloaded deck, slide 2's speaker notes end with *Text in pictures (English): Picture 1: …*, and the sign's alt text has the English; the slide itself looks unchanged.

**5b.3 Excel.** Upload `samples/quexian-qingdan.xlsx`.
- [ ] Layout shows the sheet as a grid with tabs (缺陷, 汇总); the sheet names stay Chinese, dates and numbers unchanged.
- [ ] 已整改 / 未整改 are translated once each, everywhere. In the downloaded workbook, 汇总 still counts 3 and 3 (the COUNTIF texts were translated with the cells).
- [ ] **The picture and its alt text:** the defect sketch at H2 gives two segments — *Alt text* (p1.21, 缺陷位置示意图) and the picture's own text (p1.22). In the downloaded workbook the picture's alt text reads *Defect location diagram — Text in the picture: …*.

**5b.4 Old formats.** Upload a `.doc` (or rename any file to `.doc`): refused with *save it as .docx in Word, or export it to PDF*.

## 6. Segment editor

Use `fucha-baogao.pdf` or `nachbegehung.pdf` (any translated document works).

- [ ] **Translator / Reviewer** switch: Ctrl+Enter confirms (Translator) or marks *Reviewed* (Reviewer).
- [ ] **Keyboard:** Alt+↓/↑ move between segments; Esc reverts an edit; Alt+S copies the source; Alt+1 inserts the first TM match (when the TM panel shows one).
- [ ] **Terms:** project terms are underlined in the source. Hovering shows the target and the forbidden variants.
- [ ] **Comments:** hover a row → **comment** → type, Enter. Switch to Reviewer and add another; resolve one. The **Comments** filter shows open ones.
- [ ] **Comments before translating:** on a PDF at the source check (status *Check source*), open **Document → Reading**, hover a passage → **Comment**: you can post. While the agents run, the thread says "Comments open when the agents finish".
- [ ] **Comments survive a source fix:** comment on a paragraph, then in the chat ask for a page fix that splits a different paragraph on that page and accept it. The comment is still on its paragraph (its id may have changed).
- [ ] **Comments in Reading:** a passage with an open comment has an accent bar and a "1 comment" chip; the chip opens the thread. Ask the chat "what do the comments say?": it lists them.
- [ ] **Lock** a segment: it can't be edited, and agents skip it.
- [ ] **QA issues under the segment:** a segment with a QA problem shows it right under the row (no need to click in): severity, check, message, **Fix** and **Ignore**. Click **Fix** → the chat gets the request and the agent proposes the correction.
- [ ] **Filters:** To do / QA issues / Confirmed / Lowest score first (by AI quality estimate).
- [ ] **Save version (n)** after edits → a new version appears in History.
- [ ] **Confirm AI-checked (n)** confirms every draft that passed the AI review. The chat says *Confirmed n segments · n saved to the TM*; those rows show **in TM**, and in the project's Translation memory tab their units are marked **bulk**.
- [ ] **Accept & confirm:** ask the chat for "More formal" on two segments, then press **Accept & confirm** on the proposal: both segments become *Confirmed* and show **in TM**.

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
- [ ] The token chip in the document toolbar shows tokens per step (no dollars), each model with its company's logo; after a chat with suggestions it also lists *Suggestions*.
- [ ] **Sidebar:** the floating orb and TRANSLATE at the top (no product name). The button at the top right of the sidebar (or ⌘/Ctrl+\\) folds it to an icon rail and back. Drag its right edge: it gets wider or narrower (between about 210 and 420 px); double-click the edge: back to normal. Reload: width and folding stay as you left them, with no flash.
- [ ] **Search and filter:** type part of a title or file name in the sidebar's search: the list narrows. Pick a project in the filter next to it (or click a document's project tag): only its documents; the chip above the list clears it.
- [ ] **⌘K** (or Ctrl+K): the palette lists actions, documents and projects; type to filter; Enter opens one.
- [ ] **Projects:** the sidebar's *Projects* opens the overview (one card per project with its counts); a card opens the project page.
- [ ] **Titles and summaries:** after the analysis, a document's sidebar row and the top bar show an English title instead of the file name (e.g. *Re-inspection protocol, Substation North* for `nachbegehung.pdf`); click the summary line in the top bar to read it all.
- [ ] **Theme:** the moon/sun/monitor button at the bottom of the sidebar cycles System → Light → Dark; **Settings → Appearance** has the same choice. Reload: no flash of the other theme. On *System*, change the OS appearance: the app follows.
- [ ] **Settings → Models:** the gear in the sidebar. The diagram at the top shows every step with its model (company logo, name) and reasoning level. Hover the *Translating* row: Analysis, Translation, Refinement, Consistency and Rewrites light up, the rest dims. Click *Review* in the diagram: a small editor opens to change just that step. Rows: Reading, Translating, Reviewing, Chat, Assist; the model picker greys out models that can't read images for Reading and Chat, and shows *Reads images* / *Thinks*.
- [ ] **What Default means:** each level row says *Default: Low (pipeline.yaml)* or *Default: Instant (models.yaml)*, and a dot marks that level. Pick *High* for Translating: it says *Chosen: High · Use default (Low)*; **Save**, reopen: it stuck, and the step has a dot and ring in the diagram. **Reset to default** puts the defaults back. Closing with unsaved changes asks first.
- [ ] **A model that doesn't think:** in `models.yaml`, a model without `thinking: true` says *This model doesn't reason* instead of the levels.
- [ ] **One document's models:** on the upload page, a chip per group shows what new documents use (logo, model, level). Click one → change the Translating model → **Use for this document**. After uploading, the models chip in the top bar shows it; hover it for every group (*(default)* where nobody chose). Click it, change Reviewing, **Save**: the chat notes *Settings for this document: Review → …* (from the next run).
- [ ] **Chat model:** under the chat input, *Claude Haiku 5.5 · Low* (with the logo). Click it, pick another model or level: *Applies from your next message*. While the agents work it is greyed out.
- [ ] **Usage:** after a run with a reasoning level, the token chip's breakdown shows the level and the tokens spent thinking (e.g. *claude-haiku · high · 1.2k thinking*).
- [ ] **References in the analysis:** start the dummy dictionary (`python3 dictionary-server/server.py`; `backend/.env` already has `DICTIONARY_URL=http://localhost:8200/lookup` from `.env.example`). Upload `fucha-baogao.pdf` into the Chinese project, continue after the source check. The chat shows lookups: *Translation memory: 5 segments reused…*, *Termbase: N terms already decided*, *Translation memory: 4 of 20 key terms used before*, *Dictionary: 3 of 20 key terms found* — open one to see each term and its outcome. In a live run 消缺 became a question: *Dictionary disagrees: … gives defect elimination, not "defect cleared"*, with *defect elimination* recommended.
- [ ] **Key terms:** Source & notes → Brief, terms & checks: terms say *as in the TM*, *dictionary agrees* or *asked*, with the dictionary senses and TM sentences under the meaning.
- [ ] **Chat lookups:** ask "How was 缺陷 translated before, and what does the termbase say about 消缺?" The chat shows *Translation memory: …* and *Termbase: …* lookups (open them for the entries) and answers from them.
- [ ] **Dictionary switch:** without `DICTIONARY_URL` it is greyed out with the reason. With the dummy dictionary running (README, *Dictionary service*), turn it off for a document: the analysis looks nothing up.
- [ ] **Reading on translate:** upload `nachbegehung.pdf`. At the source check the panel shows the page images; press **Continue to translation** → the panel switches to **Document → Reading**. Switch to Segments while it translates: it stays there.

- [ ] **Theme and colour:** light and dark both use the soft blue accent; the diff colours (green added, red removed) stay distinct from it.

## 13b. AI assist

- [ ] **Suggested follow-ups:** open a ready document (e.g. `nachbegehung.pdf`). Above the chat input, up to three ✦ chips appear (in a live run: *Explain the AI reviewer changes*, *Check the defect 3 deadline*, *Make the terminology consistent*). Click one: it is sent. After the answer, new chips appear. Turn **Settings → AI assist** off: no chips and no grey text.
- [ ] **Tab completion:** type *Make the tone* and wait a moment: grey text continues it (e.g. *more formal, matching the German register*). Tab accepts it, Esc dismisses it, typing on replaces it. In an empty box, the grey text is the first suggestion: Tab fills it in.
- [ ] **Ask about a selection:** in Document → Reading, select a few words of the translation: a small toolbar appears. **Explain** answers in the chat (no changes); **Other options** gives three alternatives as a proposal; **Rewrite ▾ → Shorter** gives a proposal; **Ask…** puts the passage in the chat box. On the source side (Side by side), **Explain** says what the source says in plain English.
- [ ] **Rewrite on a passage:** hover a paragraph in Reading → **Rewrite ▾ → More formal**: a proposal for that segment only. The same menu is on each Segments row.
- [ ] **Rendered changes:** proposals and version changes show the text as it reads (headings, bold, tables) with additions in green and removals in red; the small `</>` button shows the markdown diff instead. A change that only made a word bold says *Only the formatting changed*.
- [ ] **Question cards:** the sentence a term is in shows as text (no `**`, `#` or `|`), with the term highlighted; the English line highlights the recommended option.
- [ ] **Translation summary:** download menu → *Translation summary…*: a short summary appears (summary, terminology decisions and where each came from, assumptions, open queries, what wasn't translated, quality). Copy and Download `.md` work; **Regenerate** writes it again. The download menu then also lists *Translation summary (.md)*.

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

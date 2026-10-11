# Manual test script

A hands-on checklist for every feature, written for someone who doesn't read German or Chinese: each test says which sample to use, what to do, what you should see, and what the source text means. Tick the boxes as you go and note anything that differs.

The agents run on real models, so wording differs between runs. **Which** terms get asked about can vary too: "expected" questions are the likely ones, and the important thing is that every question can be answered without knowing the source language. Exact counts (TM matches, QA errors, import reports) are deterministic and should match.

- **What each sample contains, and its traps:** [samples/SAMPLES.md](../samples/SAMPLES.md).
- **English reference translations:** `samples/reference/*.en.md`. Compare the app's output with these.

---

## 0. Setup

```bash
# backend (terminal 1)
cd backend && uv sync && uv run uvicorn translator.api:app --port 8000

# frontend (terminal 2)
cd frontend && npm install && npm run dev        # http://localhost:3000

# layout server (once; needed for scans → layout PDF)
cd layout-server && uv sync

# samples and demo projects (terminal 3)
cd backend
uv run python scripts/make_samples.py              # regenerates the Chinese + agentic samples
uv run python scripts/seed_demo.py --reset         # two projects: German → English, Chinese → English
```

- [ ] `seed_demo.py` prints:
  - **German project:** 12 terms and 12 TM units added.
  - **Chinese project:** 15 terms and 9 TM units added.
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
- [ ] Termbase → **Export CSV**: the file opens in Excel with correct accents.
- [ ] Delete the project (bin icon). Its documents are kept, outside any project.

---

## 2. Upload and the step bar

**2.1 Upload.** Click **New translation**, choose `samples/fucha-baogao.pdf`, Project = the Chinese project, then **Translate**.
- [ ] The form says *Translate a document into English*; "Into" is fixed to English.
- [ ] The chat shows the **step bar**: Read → Analyse → Translate → Review → Ready. The current step spins, with page x/y and a timer.
- [ ] The sidebar shows the document under its project with a spinner.

**2.2 Queue.** Upload two more documents quickly (any samples).
- [ ] At most two run at once; the third shows *Queued* until one finishes.

---

## 3. Analysis and questions you can answer (the key new feature)

**3.1 Questions before translating (German).** Upload `samples/vertragsauszug.pdf` into the German project.
- *What it is:* an extract of a construction contract. It uses the abbreviations **AG** (*Auftraggeber*, the client) and **AN** (*Auftragnehmer*, the contractor) from page 1, but defines them only in an annex on page 2.
- [ ] The step bar stops at **Analyse** with a question mark: *Waiting for your answers*.
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
- [ ] Project → Termbase: your choice appears as an **approved** term, with the meaning as the note. (Questions where you kept the recommendation are saved as **proposed** — see 3.2.)
- [ ] Compare with `samples/reference/vertragsauszug.en.md`.

**3.2 Questions before translating (Chinese).** Upload `samples/quexian-qingdan.xlsx` (a defect list) into the Chinese project.
- [ ] A question about **运维方** ("the operations and maintenance side": which party is that?), explained in English.
- [ ] **Accept all recommendations & continue** → the translation runs with no further pause on that term.
- [ ] Project → Termbase: the accepted term is **proposed** (not approved), with an **Approve** button. Click **Approve**: it becomes approved.

**3.3 Terms defined later are used from the start.** Upload `samples/anquan-peixun.pptx` (a safety training).
- *What it is:* slide 1 demands strict **两票三制** and **五防**; slides 3 and 4 explain them (the "two permits and three systems" and the "five preventions", safety rules in Chinese utilities).
- [ ] No question about 五防 / 两票三制. The brief and the key terms explain them.
- [ ] Slide 1's translation uses the same terms as slides 3–4. Compare with `reference/anquan-peixun.en.md`.

**3.4 Skip.** On any document that asks, click **Skip — let the AI decide**.
- [ ] Translation continues. The term isn't in the glossary or the project termbase, but the recommendation is used consistently.

**3.5 Questions after the run.** If a finished document shows *How should this term be translated?* cards (raised by the reviewer):
- [ ] Each one recommends something **different** from the current translation. Cards that only confirm the translation should not appear.
- [ ] **Apply** → the chat editor proposes the edits (a proposal card). **Keep current** dismisses the card.

---

## 4. Translation memory

**4.1 Chinese TM leverage.** Open `fucha-baogao.pdf` (uploaded in 2.1, or upload it now).
- *What it is:* a follow-up inspection that repeats parts of `yanshou-baogao.pdf`, whose translation is in the TM.
- [ ] The chat reports the TM pass: **5 segments reused** with no model call, and **2 fuzzy matches** to adapt. (More once you have confirmed segments in other Chinese documents: confirmed work goes into the TM.)
  - The exact matches are the headings 二、发现的缺陷 and 三、结论, the defects table, the figure caption and the quoted conclusion.
- [ ] Segments tab: those 5 segments show *TM 100%*, and still do after the review: the AI reviewer only changes a 100% match for a major issue.
- [ ] **Date-line trap:** the date line was a fuzzy match from a TM unit dated 14 March 2026, but this report is dated **20 May 2026**. The translation must say 20 May 2026. If it says 14 March, QA flags a date error.
- [ ] The scope paragraph (97% match) talks about the *review* or *re-inspection* (复查), not the *acceptance* (验收) of the stored translation.

**4.2 German TM.** Open `nachbegehung.pdf` (uploaded by `seed_demo.py --upload`, or upload it into the German project).
- [ ] 5 reused, 3 fuzzy.

**4.3 Confirming fills the TM.** In Segments, click into a draft and press **⌘/Ctrl+Enter** on 3 segments.
- [ ] Their status becomes *Confirmed*, and the next draft is focused.
- [ ] Project → Translation memory: 3 more units.
- [ ] Upload the same file again into the project. Those 3 segments are reused (101% if the previous segment is also the same).

---

## 5. Segment editor

Use `jiance-baogao.docx` (a Chinese earthing test report in Word) or `pruefbericht.docx`.

- [ ] **Translator / Reviewer** switch: Ctrl+Enter confirms (Translator) or marks *Reviewed* (Reviewer).
- [ ] **Keyboard:** Alt+↓/↑ move between segments; Esc reverts an edit; Alt+S copies the source; Alt+1 inserts the first TM match (when the TM panel shows one).
- [ ] **Terms:** project terms are underlined in the source. Hovering shows the target and the forbidden variants.
- [ ] **Formatting codes:** the source of p1.4 shows numbered tags (bold, italic). In the target, the code chips insert at the cursor. Deleting a code and leaving the segment gives a *codes don't match* error and the save is refused.
- [ ] **Comments:** add a comment as reviewer, resolve it. The **Comments** filter shows open ones.
- [ ] **Lock** a segment: it can't be edited, and agents skip it.
- [ ] **QA issues under the segment:** a segment with a QA problem shows it right under the row (no need to click in): severity, check, message, **Fix** and **Ignore**. Click **Fix** → the chat gets the request and the agent proposes the correction.
- [ ] **Filters:** To do / QA issues / Confirmed / Lowest score first (by AI quality estimate).
- [ ] **Save version (n)** after edits → a new version appears in History.
- [ ] **Confirm AI-checked (n)** confirms every draft that passed the AI review. Bulk-confirmed segments are **not** added to the translation memory (only one-by-one confirmations are): the project's TM count doesn't change.

---

## 6. Explain and summarise (for languages you don't read)

- [ ] On any segment row, click **explain**. The chat answers in plain English:
  - what the source literally says;
  - nuances the translation can't carry;
  - whether the translation renders it faithfully.

  No proposal is created.
- [ ] Above the chat input, click **Summarise**. You get a plain-English summary of the document (purpose, key facts, dates, obligations), with no changes.
- [ ] Type *"explain p1.3"* yourself: same behaviour.

---

## 7. Chat edits and proposals

- [ ] Ask in the chat: *"Use 'earthing' instead of 'grounding' everywhere"* (or any terminology change).
  - A proposal card lists the changes as diffs. Nothing changes until you accept.
- [ ] **Segments** tab: the same changes appear **under each segment** with tick boxes, and a banner offers **Apply all / Reject all**. The tab label shows the number of proposed changes, and the **Proposed** filter shows only those segments.
- [ ] Untick one change in the grid. The chat card shows it unticked too, and the banner says **Apply N selected**.
- [ ] Apply → a new version. History shows the diff.
- [ ] Ask something, then **Reject** → nothing changes.

---

## 8. Agentic tasks

- [ ] **Rewrite:** in Segments, tick 2 segments (shift-click for a range), then **More formal**. A proposal arrives.
- [ ] **Alternatives:** tick 2 segments → **3 alternatives**. Each change offers 3 options with notes; pick one per segment (in the grid or the chat), then accept.
- [ ] **Apply termbase** (chat shortcut) or Quality → **Fix consistency**. Repeated sentences are unified and termbase rules applied, as a proposal.
  - `jiance-baogao.docx` repeats 测试条件：天气晴… ("Test conditions: sunny, ambient temperature 25 °C…") as p1.10 and p1.28.

---

## 9. Quality: QA, find & replace, LQA

**9.1 Vendor XLIFF (Chinese).** On `jiance-baogao.docx`: download menu → **Import a returned XLIFF…** → `samples/demo/zh/jiance-baogao.vendor.en.xlf`.
- [ ] The report lists the vendor's changes (about 30–49: units identical to the AI's translation count as *unchanged*), with **p1.6 refused** because the vendor dropped the footnote code.
- [ ] Accept the proposal. The **Quality** tab shows the 4 planted errors and the consistency warning:
  - p1.4: forbidden *Party A* (should be *Client*);
  - p1.24: 0.35 Ω became *0.53 Ω*;
  - p1.46: the deadline 15 **June** 2026 became *15 May*;
  - p1.47: left in Chinese (untranslated);
  - p1.10 / p1.28: the same sentence translated two ways (consistency warning).

**9.2 Vendor XLIFF (German).** On `pruefbericht.docx`, import `samples/demo/pruefbericht.vendor.en.xlf`.
- [ ] The report gives the vendor's proposed changes and one refusal (a dropped footnote code).
- [ ] After accepting, QA shows:
  - forbidden *cable bridge* and *Substation Nord*;
  - a wrong date;
  - an untranslated sentence;
  - *in Ordnung* ("OK / satisfactory") translated two ways.

**9.3 Fix it with the agents.** In the chat, **Next steps → Fix N QA errors** (or the *Fix QA errors* shortcut).
- [ ] The editor runs the QA checks and proposes fixes. Accept them.
- [ ] Then **Apply termbase**, accept. QA errors go to 0 (warnings about heading numbers like "1." may remain; they're benign).

**9.4 QA details.**
- [ ] **Ignore** a warning: it disappears; **Show ignored** brings it back. It returns if the text changes.
- [ ] **Excel formulas:** on `quexian-qingdan.xlsx` the chat says 3 cell texts are used inside formulas. Download menu → *Translated file — original format* notes that those formulas are updated to the translation.

**9.5 Find & replace.** Segments → **Replace**: find `retention`, replace `retainage`.
- [ ] The preview lists the changes as diffs. Untick one, then apply: the rest become one new version. Locked segments are skipped.

**9.6 LQA.** **Next steps → Check quality score** (or Quality → Run LQA).
- [ ] A score per 1,000 words, pass or fail against the threshold, a category × severity scorecard, and the review queue (lowest scores first).
- [ ] After the vendor import (before fixes) the document fails; after the fixes the score rises.

---

## 10. Office round trips

- [ ] **Word** (`jiance-baogao.docx`):
  - The chat notes **2 tracked changes**, translated as accepted.
  - Download **Translated file — original format**. In Word: bold and italic in the right places, the link works, the footnote is there, the footer shows a live page number, and there are no revision marks.
  - p1.46 says the work must be done **by 15 June 2026**. That's the tracked insertion; the deleted word 尽快 ("as soon as possible") is gone.
- [ ] **PowerPoint** (`anquan-peixun.pptx`): download the PPTX. Speaker notes are translated. The slogan box on slide 4 (*Safety first, prevention foremost, comprehensive management*) shrinks to fit instead of overflowing.
- [ ] **Excel view:** Document → **Sheets** shows each sheet as a grid (tabs 缺陷 / 汇总): the header row shaded, numbers right-aligned, deadlines as dates, the summary sheet's formula results with an *fx* marker (hover shows the formula). Toggle **Original**: the Chinese text in the same cells. Click a cell: its segment opens.
- [ ] **PowerPoint view:** Document → **Slides** shows each slide with its text where it sits and the notes underneath; **Side by side** puts the Chinese slide next to the English one; the slogan box on slide 4 shrinks its text to fit.
- [ ] **Excel** (`quexian-qingdan.xlsx`): download the XLSX.
  - Formulas, numbers and real dates are untouched.
  - The bold 【重要】 ("[Important]") part of C7 stays bold.
  - The summary sheet's formulas compare against the English texts (`=COUNTIF(缺陷!F:F,"Not rectified")`), so the counts stay 3 / 3 / 4 after Excel recalculates. Sheet names (缺陷, 汇总) are not translated, so the references still work.

---

## 11. Layout-preserving PDF

- [ ] **Text-layer PDF** (`fucha-baogao.pdf`): **Document → Original layout** shows original and translated pages side by side.
  - The table, the figure, the header ("North District Substation Renovation Project · UW-2291 · Internal") and the footer ("Page 1 of 2") stay in place.
  - The paragraph that runs across the page break flows across in English.
  - Boxes are coloured *fit* or *shrunk*.
- [ ] **Scan** (`fucha-baogao-scanned.pdf` or `abnahmeprotokoll-scanned.pdf`, layout server installed): the same view; the source is painted out in the paper colour and the English set on top.
- [ ] Download **Translated PDF — original layout** and open it: searchable English text.

---

## 12. Exports and exchange

- [ ] Download each format from the menu, and each file opens:
  - Word (reflowed);
  - HTML;
  - Markdown (a zip when there are figures);
  - **Bilingual review table** (a landscape table with id, source, target, status and notes);
  - XLIFF 2.0;
  - XLIFF 1.2.
- [ ] Export XLIFF 2.0, then import it straight back: *0 changes*.
- [ ] Project → Translation memory → **Export TMX**; Termbase → **Export TBX**. Import them into a new project: same counts.

---

## 13. Robustness

- [ ] **Reload during a run:** the step bar and progress come back.
- [ ] **Retry:** stop the backend while a PDF is in the *Read* step, restart it, open the document and click **Retry**.
  - Pages already read say *reused from the earlier run* in the activity log.
  - The run completes.
- [ ] **Rate limits:** if the budget model is throttled (`429` in the backend log), the run slows down but completes; the calls are retried with backoff.
- [ ] **OCR check skip:** on `nachbegehung.pdf` (a clean digital PDF), the activity log may say *matches the PDF's text layer (no second check needed)* for a page. On scans every page says *verified* or *checker fixed…*.

---

## 14. Layout and navigation

- [ ] The document panel has five tabs:
  - Segments;
  - Document (Reading / Side by side / Original layout);
  - Quality;
  - History;
  - Source & notes (Source or Page images & OCR / Brief, terms & checks).
- [ ] Switching tabs returns to the last view you used in that tab.
- [ ] Drag the divider between chat and document. The width is kept after a reload.
- [ ] **Widen** hides the chat; again brings it back.
- [ ] In the sidebar, collapse a project with the chevron; the active document's project stays open.
- [ ] The cost chip in the document header shows dollars and tokens per step. A two-page document costs about one cent.

---

## Reporting a problem

Note:
- the test number;
- the document and segment id (e.g. `fucha-baogao.pdf p1.4`);
- what you expected and what you saw;
- a screenshot.

The backend log is useful for errors, and **Source & notes → Brief, terms & checks** shows what the agents decided (brief, key terms, review report).

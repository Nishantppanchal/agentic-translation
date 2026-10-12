# Sample documents

Every file in `samples/`: what it is, what it exercises, and the traps it plants, with the behaviour the app
should show. All samples belong to one fictional project: the renovation of the 110 kV switchgear at the
**Umspannwerk Nord / 北区变电站** (North District Substation), project **UW-2291**. Client: Acme Energie Netz
GmbH (甲方); Contractor: Albrecht Elektrotechnik GmbH (乙方, site manager K. Albrecht).

- **English references** for every Chinese sample, the German contract and the two source-check scans are in `reference/<sample>.en.md`.
  Each ends with translator's notes on the planted terms.
- **Generators.** `backend/scripts/make_samples.py` regenerates every file marked *new* below, byte for byte:
  `cd backend && uv run python scripts/make_samples.py` (it does not write this file).
  `backend/scripts/make_language_samples.py` writes `languages/` (the acceptance report in 21 more languages, see
  [Other languages](#other-languages)); `backend/scripts/make_review_samples.py` writes `review/` (the
  [source-check scans](#source-check)) and their English references. The older samples were
  made by one-off scripts outside the repo; `demo/pruefbericht.vendor.en.xlf` comes from
  `backend/scripts/make_vendor_xliff.py`.
- **How the numbers below were computed.** Segment ids and counts come from `translator.filters.office.extract`.
  QA results come from `translator.qa.run` with the project termbase. TM scores use the current lookup in
  `translator/projects.py`: the key is normalised (NFKC, case-folded, punctuation and spaces removed); the fuzzy
  score is Levenshtein similarity over words, or over characters for Chinese. PDF segment ids depend on the OCR
  model's markdown, so PDF traps are given by content and page.
- **Benign QA warnings.** A correct translation still gets a few warnings:
  - Chinese section numbers (一、二、…, （一）) are not read as numbers, so “1.”, “2.1” in English headings give
    *“Number n is in the translation but not in the source”*.
  - The terminology check is a substring test, so 已整改 → “Rectified” gets *“整改 should be translated as
    rectification”*.

  A correct translation has **0 QA errors** on every sample (checked against the references).

## Index

| File | Lang | Format | Size | Main purpose | |
|---|---|---|---|---|---|
| `abnahmeprotokoll.pdf` (+ `-scanned.pdf`) | de | PDF, text layer / scan | 2 pp. | Acceptance report; source of the German TM | existing |
| `nachbegehung.pdf` | de | PDF | 2 pp. | TM leverage (exact + fuzzy), header/footer | existing |
| `wartungsbericht.pdf` (+ `-scanned.pdf`) | de | PDF | 1 p. | Raster diagram with German labels | existing |
| `pruefbericht.docx` | de | Word | 21 seg. | Office round trip, inline codes, tracked changes, vendor XLIFF | existing |
| `unterweisung.pptx` | de | PowerPoint | 12 seg. | Slides and speaker notes | existing |
| `maengelliste.xlsx` | de | Excel | 18 seg. | Shared strings, rich text, COUNTIF literal | existing |
| `yanshou-baogao.pdf` (+ `-scanned.pdf`) | zh | PDF | 1 p. | Chinese acceptance report; source of the Chinese TM | existing |
| `fucha-baogao.pdf` (+ `-scanned.pdf`) | zh | PDF | 2 pp. | Forward definition, cross-page paragraph, TM leverage, questions | **new** |
| `jiance-baogao.docx` | zh | Word | 50 seg. | Codes, tracked changes, repeated sentence, Chinese vendor XLIFF | **new** |
| `anquan-peixun.pptx` | zh | PowerPoint | 26 seg. | Terms defined on later slides, shrink-on-overflow | **new** |
| `quexian-qingdan.xlsx` | zh | Excel | 31 seg. | Shared strings, rich text, formulas over status texts, real dates | **new** |
| `vertragsauszug.pdf` (+ `-scanned.pdf`) | de | PDF | 2 pp. | AG/AN defined late, VOB/B legal terms, repeated clause | **new** |
| `demo/termbase.csv`, `demo/memory.tmx` | de→en | CSV, TMX | 12 + 12 | German project termbase and TM | existing |
| `demo/pruefbericht.vendor.en.xlf` | de→en | XLIFF 2.0 | 21 units | Vendor file with planted errors | existing |
| `demo/zh/termbase.csv`, `demo/zh/memory.tmx` | zh→en | CSV, TMX | 15 + 9 | Chinese project termbase and TM | **new** |
| `demo/zh/jiance-baogao.vendor.en.xlf` | zh→en | XLIFF 2.0 | 50 units | Chinese vendor file with planted errors | **new** |
| `reference/*.en.md` | en | Markdown | 9 files | English references (`acceptance-report.en.md` fits every file in `languages/`) | **new** |
| `languages/acceptance-<code>.pdf` (+ `-scanned.pdf`) | 21 languages | PDF, text layer / scan | 1 p. | The same acceptance report in every other source language: OCR per script, right-to-left, captions, local legal terms and abbreviations | **new** |
| `review/pruefvermerk-zweispaltig-scanned.pdf` | de | PDF, scan | 1 p. | Source check: two columns, a paragraph across the column break, a stamp over the text | **new** |
| `review/jianli-tongzhi-shuanglan-scanned.pdf` | zh | PDF, scan | 1 p. | Source check: two columns, a paragraph across the column break, a seal over the text | **new** |

### Trap matrix (new samples)

| Trap | fucha-baogao.pdf | jiance-baogao.docx | anquan-peixun.pptx | quexian-qingdan.xlsx | vertragsauszug.pdf |
|---|---|---|---|---|---|
| Ambiguous terms to ask about | 消缺, 运维单位, 保电 | 运维单位, 消缺 | 保电 (运维单位) | 运维方, 消缺 | Behinderungsanzeige, Bedenkenanzeige |
| Used before it is defined | 三措一案 (p. 1 → p. 2) | – | 五防, 两票三制 (slide 1 → 3, 4) | – | AG, AN (p. 1 → Annex 1, p. 2) |
| Repeated segment | 乙方应在整改完成后5个工作日内… (p. 1, p. 2) | 测试条件：… (p1.10, p1.28) | 严禁擅自解除防误闭锁装置。 (p3.8, p4.7) | shared strings ×3 | § 4 (3) = § 5 (3) |
| Paragraph across a page break | 第3项缺陷涉及UPS直流母线… | – | – | – | § 7 (1) |
| Running header + page footer | yes (第 n 页 共 2 页) | header + PAGE field | – | – | yes (Seite n von 2) |
| TM matches (zh / de memory) | 5 exact, 2 fuzzy | 1 exact (三、结论) | none | none | none |
| Vendor XLIFF | – | 6 planted errors | – | – | – |

### Setting up the projects

`backend/scripts/seed_demo.py` creates both demo projects through the API, each translated into English:
- **Acme Energie – Umspannwerk Nord** (German): `demo/termbase.csv` and `demo/memory.tmx`;
- **北区变电站改造 – UW-2291** (Chinese (Simplified)): `demo/zh/termbase.csv` (15 terms, `Chinese;English;Note;Forbidden`,
  semicolon-separated, forbidden variants separated by `|`) and `demo/zh/memory.tmx` (9 units).

```bash
cd backend
uv run python scripts/seed_demo.py --reset            # both projects
uv run python scripts/seed_demo.py --only zh --upload # just the Chinese one, and upload fucha-baogao.pdf + jiance-baogao.docx
```

---

## Other languages

`languages/acceptance-<code>.pdf` (+ `-scanned.pdf`): the same one-page acceptance report in every other source
language the app offers. Each page has a running header, a title and date line, three numbered headings, a
paragraph, a 3-row defects table, a diagram whose labels are in the language, a caption, a conclusion and a page
footer. They all say what `reference/acceptance-report.en.md` says, so any of them can be checked without reading
the language. Regenerate with `cd backend && uv run python scripts/make_language_samples.py`.

- **Scan only** for Arabic, Hindi, Bengali and Thai: PyMuPDF typesets those scripts correctly but its text layer
  doesn't map the shaped glyphs back to the right characters, and a sample with a wrong text layer would test the
  wrong thing (`tests/test_language_samples.py` checks every text layer against the source).
- **Right to left:** Arabic and Hebrew are laid out right to left (table columns too).
- **Traps:** each conclusion uses the language's legal term for a conditional acceptance (réception avec réserves,
  collaudo con riserva, 条件付き受入, 조건부 인수…), and the UPS has its local abbreviation (SAI, ASI, ИБП, ДБЖ, KGK,
  אל-פסק, यूपीएस, 不斷電… → the analysis should ask about these or render them consistently). Dates follow local
  formats (14/03/2026, 14.03.2026, 14-03-2026, 2026-03-14, 2026年3月14日, 2026년 3월 14일).

### OCR: measured

Each scan was read the way the app reads it, and the reading compared with the text the page was typeset from
(the share of characters that match, after removing markdown and spacing). The reader is the **vision LLM**
(`qwen/qwen3-vl-8b-instruct` through OpenRouter, the same model as the vLLM default, with pictures outlined by
PP-DocLayoutV3). Raw readings, before the OCR check.

| Code | Language | Script | Files | Vision LLM |
|---|---|---|---|---|
| es | Spanish | Latin | text + scan | 100.0% |
| fr | French | Latin | text + scan | 99.7% |
| it | Italian | Latin | text + scan | 99.7% |
| pt | Portuguese | Latin | text + scan | 99.7% |
| nl | Dutch | Latin | text + scan | 99.6% |
| pl | Polish | Latin | text + scan | 99.8% |
| sv | Swedish | Latin | text + scan | 99.7% |
| tr | Turkish | Latin | text + scan | 99.7% |
| ru | Russian | Cyrillic | text + scan | 99.7% |
| uk | Ukrainian | Cyrillic | text + scan | 99.4% |
| el | Greek | Greek | text + scan | 99.7% |
| ar | Arabic | Arabic (RTL) | scan only | 99.5% |
| he | Hebrew | Hebrew (RTL) | text + scan | 87.4% |
| hi | Hindi | Devanagari | scan only | 99.3% |
| bn | Bengali | Bengali | scan only | 97.3% |
| id | Indonesian | Latin | text + scan | 100.0% |
| vi | Vietnamese | Latin | text + scan | 99.5% |
| th | Thai | Thai | scan only | 94.3% |
| ja | Japanese | Japanese | text + scan | 100.0% |
| ko | Korean | Korean | text + scan | 100.0% |
| zh-Hant | Chinese (Traditional) | Traditional Chinese | text + scan | 100.0% |
| de | German | Latin | `abnahmeprotokoll-scanned.pdf` p. 1 | 100.0% |
| zh | Chinese (Simplified) | Simplified Chinese | `fucha-baogao-scanned.pdf` p. 1 | 96.6% |

**PaddleOCR-VL 1.5** (`PaddleOCR-VL-1.5-0.9B` + PP-DocLayoutV3, 2026-10-12) was evaluated on the same pages and
dropped: the vision LLM read 15 of the 23 languages better, PaddleOCR-VL could not read Hebrew and invented a
paragraph on Arabic, and its advantage elsewhere was a character or two.

What the numbers don't show:
- **The vision LLM can swap in a plausible word.** On Thai it read "สถานีไฟฟ้าย่อยเหนือ" (North substation) as
  "…อยุธยา" (Ayutthaya, a well-known place name) — the failure an OCR-specialised model avoids; Hebrew had letter
  substitutions throughout (87.4%). The OCR check lists such doubts rather than applying them.
- **Structure:** these pages have one column. On two columns, or with a stamp or seal over the text, the vision LLM
  can split a paragraph, drop text or miss headings: see [Source check](#source-check).
- These are clean, typeset scans: they weren't tested on blurred, skewed or handwritten pages.

## Source check

`review/*-scanned.pdf`: two one-page scans whose structure a vision model tends to get wrong, for the source check
(fixing the OCR in the chat before translating; the test script is section 3 of
[docs/TESTING.md](../docs/TESTING.md)). Each has:
- two columns with a narrow gutter, so reading straight across is tempting;
- a paragraph running from the bottom of the left column to the top of the right one, mid-sentence;
- a red stamp or seal printed over the text.

Regenerate with `cd backend && uv run python scripts/make_review_samples.py` (it also writes the English
references). What each one got wrong was measured in a live run (Qwen3-VL-8B via OpenRouter, 2026-10-12).

### `review/pruefvermerk-zweispaltig-scanned.pdf`: German, 1 page

**Summary.** Prüfvermerk – Erdung der Kabelpritsche (inspection note: earthing of the cable tray), in two columns.
Section 3 (Messwerte, measured values) runs from the bottom of the left column to the top of the right one, and
breaks the word “Fehlerstrom-Schutzeinrichtung” (residual-current device) across the columns. A red, rotated
rubber stamp “GEPRÜFT · 14.03.2026 · Bauleitung UW-2291” is printed over section 4. Reference:
`reference/pruefvermerk-zweispaltig.en.md`.

**What the live run read wrong.**
- Section 3 came back as two segments, split at the column break (“…Fehlerstrom-” / “Schutzeinrichtung wurde…”).
- The running header appeared twice (once as a paragraph).
- The stamp's text was dropped entirely.

**The fix that worked.** “Section 3 (Messwerte) got split in two at the column break: it ends with "Fehlerstrom-"
and goes on with "Schutzeinrichtung wurde…" — it is one paragraph. The running header also appears twice at the
top; keep only the header line. And the red stamp over section 4 is missing: it says "GEPRÜFT 14.03.2026 ·
Bauleitung UW-2291" — add it as its own line after section 4.”
- One page fix; its word changes listed the duplicate header removed and the stamp's words added.
- Accept → 19 segments. Continue → translated; the stamp became “CHECKED 14.03.2026 · Site management UW-2291”.
- Check the word changes before accepting: they caught the editor joining “Fehlerstrom-Schutzeinrichtung” without
  its hyphen (the editor is now told to keep a word's own hyphen).

### `review/jianli-tongzhi-shuanglan-scanned.pdf`: Chinese, 1 page

**Summary.** 监理通知单——地下室电缆桥架接地 (supervision notice: earthing of the basement cable tray), in two
columns. Section 五 (安全措施, safety measures) runs across the column break mid-sentence. A red round seal
(北区变电站改造工程监理部 / 监理专用章) is printed over the attachments line (八、附件) and the signature.
Reference: `reference/jianli-tongzhi-shuanglan.en.md`.

**What the live run read wrong.**
- No heading was marked as a heading: the title and 一、二、… came back as paragraphs.
- The running header wasn't marked as a header.
- PP-DocLayoutV3 took the seal as a picture.
- Under the seal, attachment 1 “现场照片8张” (8 site photos) was misread as “图纸1张” (1 drawing).

**The fix that worked.** “Under the red seal, the attachments line (八、附件) looks misread — please read page 1
again and keep the seal out of the text. Keep the title and section headings as headings, and the running header
as the header.” The page was read again (`reread_page`): attachment 1 came back as “现场照片8张”, and the headings
and the header were marked.

## New samples

### `fucha-baogao.pdf` (+ `fucha-baogao-scanned.pdf`): Chinese, 2 pages

**Summary.** 缺陷复查报告 (defect re-inspection report) of 20 May 2026. It re-inspects the three defects listed in
`yanshou-baogao.pdf`:
- Defect 1 (cable tray not earthed) has been cleared: a bonding jumper was fitted and 0.08 Ω measured.
- Defect 2 (feeder-bay labels) has been rectified.
- Defect 3 (UPS DC busbar) needs an outage. The outage can't happen during the gaokao supply-assurance period,
  so its deadline moves to 15 June 2026.

Two of the five per cent retention money (CNY 12,500.00) is released now. Page 2 defines 三措一案 and has
three signature lines. The scanned copy is the same document as an image-only PDF (2 JPEG pages, no text
layer). Reference: `reference/fucha-baogao.en.md`.

**Layout.**
- Page 1:
  - running header 北区变电站改造工程 · UW-2291 · 内部资料;
  - title, date line;
  - § 一 复查范围 (three paragraphs);
  - § 二 发现的缺陷: the defects table, the findings paragraph, the repeated paragraph, a raster figure with
    caption 图1;
  - the first lines of the cross-page paragraph.
- Page 2:
  - the rest of the cross-page paragraph;
  - § 三 结论 (intro line, quoted conclusion, new conclusion, the repeated paragraph);
  - § 四 附注 (the definition);
  - § 五 签字确认 (three signature lines).
- Footer on both pages: 第 1 页 共 2 页 / 第 2 页 共 2 页.

**Exercises.**
- Text-layer OCR and scan OCR of Chinese.
- A table, a raster figure with Chinese labels (接地连接已恢复（实测0.08 Ω）, 配电柜, UPS电源, 电缆桥架, 接地跨接线),
  and header/footer segments.
- Joining a paragraph across a page break.
- Up-front whole-document analysis, clarification questions, termbase, TM, and QA for numbers, dates and
  consistency.

**Traps and expected behaviour.**

1. **Forward definition: 三措一案.**
   - Used on page 1 without explanation, twice: § 一 paragraph 2 (复查工作依据经审批的三措一案组织实施…) and the
     cross-page paragraph (乙方应据此修订三措一案…).
   - Defined only on page 2, § 四: 本报告所称“三措一案”，是指乙方针对停电作业编制的组织措施、技术措施、安全措施和施工方案…
   - Expected: the analysis finds the definition before translating page 1. Page 1 is translated consistently
     with it (reference: “Three Measures and One Plan”). The agent does not ask about 三措一案; if it does,
     its guess already reflects the definition.

2. **Questions the agent should ask** (none of these are in the termbase):
   - **消缺**, in § 二 findings (已消缺 ×1, 尚未消缺 ×1) and the § 三 new conclusion. Utility jargon for
     “eliminating a defect”. The same report also uses 整改 (termbase: rectification) for the same defects, so
     the translator needs to know whether to distinguish them (reference: “cleared”).
   - **运维单位**, in § 一 paragraph 2, the cross-page paragraph (twice), § 四 and a signature line. It is
     unclear which party this is (the utility's O&M department rather than a contractor) and how to render it
     (O&M organisation / operator) (reference: “O&M organisation”).
   - **保电 / 高考保电期**, in the cross-page paragraph. It literally means “protect power”: a period of
     guaranteed supply for a major event, here the national college entrance exam (gaokao), with no planned
     outages. Not guessable without domain knowledge (reference: “supply-assurance period”).
   - Not expected:
     - 监理单位 has a standard translation (construction supervisor).
     - Termbase terms must not be asked: 北区变电站, 甲方, 乙方, 承包方, 电缆桥架, 整改, 验收, 接地, 质量保证金,
       质保金, 倒闸操作, 工程量清单, 出线间隔, 电网调度中心.

3. **Paragraph across the page break.** 第3项缺陷涉及UPS直流母线，… is split mid-sentence:
   - page 1 ends with …乙方应据此修订三措一案，经审批后于;
   - page 2 starts with 停电前3个工作日向电网调度中心提交停电申请。….

   Expected: one segment on page 1 with `pages: [1, 2]`. The first half has no sentence-final punctuation, and
   CJK text has no case to go by. The scanned copy should give the same result after OCR.

4. **Running header and footer.**
   - Expected: header segments (北区变电站改造工程 · UW-2291 · 内部资料 → “North District Substation Renovation
     Project · UW-2291 · Internal”).
   - Expected: footer segments (第 1 页 共 2 页 → “Page 1 of 2”).
   - Neither should merge into body text, and neither should break the cross-page join.

5. **Repeated paragraph (consistency group).** 乙方应在整改完成后5个工作日内书面通知甲方，并申请复验。 appears on
   page 1 (after the findings) and page 2 (after the new conclusion). Expected: identical translations. If they
   differ, the QA consistency check warns.

6. **TM leverage** against `demo/zh/memory.tmx`. Sources are exactly the strings of `yanshou-baogao.pdf`.

   | Segment (source) | Match | TM unit / note |
   |---|---|---|
   | 二、发现的缺陷 (heading) | 100 % | “2. Defects Identified” |
   | the defects table (序号/描述/整改期限, 3 rows) | 100 % | whole markdown table |
   | 图1：地下室设备概览 | 100 % | “Figure 1: Overview of the basement equipment” |
   | 三、结论 (heading) | 100 % | “3. Conclusion” |
   | 设备在上述缺陷整改完成前有条件验收。…统一下令。 (quoted conclusion, p. 2) | 100 % | full paragraph |
   | 本次复查范围为110千伏开关设备的更新改造，… | 97 % fuzzy | 验收 → 复查; the TM target says “acceptance”, must become “re-inspection” |
   | 日期：2026年5月20日 ｜ 项目编号：UW-2291 | 88 % fuzzy | TM has 2026年3月14日; reusing “14 March 2026” is a date error QA must catch |
   | 缺陷复查报告——北区变电站 (title) | 69 %: no match | below the 75 % threshold |
   | 一、复查范围 | 67 %: no match | |

   The TMX has no context, so expect 100 % rather than 101 %. Expected: the 5 exact matches are reused without
   a model call, and the 2 fuzzy ones are offered to the translator and adapted.

7. **Numbers, dates, times and amounts** for QA:
   - dates 2026年5月20日, 2026年6月7日至6月10日, 2026年6月15日, 2026年3月14日;
   - times 9:30, 14:30;
   - 30%, 16 mm², 0.08 Ω, 0.2 Ω, 3个工作日, 5个工作日, 第18周, 110千伏, 4.2.7;
   - ¥12,500.00 (2%), ¥18,750.00 (3%), 5%.

   The date range must keep both dates (“from 7 June to 10 June 2026”). “7–10 June” drops a date.

**Expected QA on a correct translation:** 0 errors. Warnings: the heading numbers 1.–5. (benign), and
possibly a length warning on the short date line.

---

### `jiance-baogao.docx`: Chinese, Word

**Summary.** 接地及绝缘电阻检测报告 (earthing and insulation resistance test report) of 18 May 2026. The
Contractor tested:
- the main earth grid: 0.42 Ω, which meets 0.5 Ω;
- earthing continuity: basement cable tray 0.08 Ω pass, UPS cabinet 0.35 Ω fail;
- insulation of the 110 kV switchgear phases A/B/C: 2500/2300/2400 MΩ, all pass.

The UPS cabinet must be fixed and retested by 15 June 2026. Reference: `reference/jiance-baogao.en.md`.

**Extraction** (`office.extract`): 50 segments, all translatable;
`{'pages': 2, 'tracked_changes': 2, 'with_codes': 4, 'in_formulas': 0}`. Key segments:

| Id | Where | Source (abridged) | What it tests |
|---|---|---|---|
| p1.1 | Footer | `第 <x id="1"/>1<x id="2"/> 页` | live PAGE field (field + field end codes) |
| p1.2 | Header | 北区变电站改造工程 · UW-2291 · 内部资料 | header |
| p1.3 | Body, Heading 1 | 接地及绝缘电阻检测报告 | heading style |
| p1.4 | Body | 受甲方委托，乙方于2026年5月18日…的`<g id="1">主接地网</g>`…0.42 Ω，`<g id="2">满足设计值0.5 Ω的要求</g>`。 | bold term (g1), italic phrase (g2), 甲方/乙方, date, numbers |
| p1.5 | Heading 2 | 一、检测依据 | |
| p1.6 | Body | 检测按照经审批的`<g id="1">检测方案</g>`及DL/T 475—2017执行。`<x id="2"/>` | hyperlink (g1, to example.com), footnote mark (x2) |
| p1.7 | Body | 检测前，运维单位已按操作票完成相关倒闸操作… | 运维单位 (ask), 倒闸操作 (termbase) |
| p1.10, p1.28 | Body | 测试条件：天气晴，环境温度25 ℃，相对湿度45%。 | repeated sentence |
| p1.11–p1.26 | Table 1 | 测量位置/实测值/标准要求/结论; 主接地网 0.42 Ω ≤0.5 Ω 合格; 地下室电缆桥架 0.08 Ω; UPS屏柜 0.35 Ω (p1.24) 不合格 | table cells |
| p1.29–p1.44 | Table 2 | the same headers; 110 kV开关柜A/B/C相 2500/2300/2400 MΩ ≥1000 MΩ 合格 | table cells |
| p1.45 | Heading 2 | 三、结论 | TM exact match (“3. Conclusion”, from the yanshou memory) |
| p1.46 | Body | UPS屏柜接地导通电阻超标，判定为不合格。乙方须于2026年6月15日前完成消缺并复测。 | tracked changes: deletion 尽快 and insertion 于2026年6月15日前, read as accepted; 消缺 (ask) |
| p1.47 | Body | 其余检测项目均合格，相关设备具备投运条件。 | |
| p1.48, p1.49 | Body | 检测人员：赵磊 / 审核：王建国 | |
| p2.1 | Footnote 1 | `<x id="1"/>`DL/T 475—2017《接地装置特性参数测量导则》。 | footnote text (footnote number code) |

**Traps and expected behaviour.**

- **Questions:**
  - **运维单位** (p1.7) and **消缺** (p1.46) should be asked; same reasoning as `fucha-baogao.pdf`.
  - 操作票 may come up (switching order vs. operation ticket).
  - Termbase terms (甲方, 乙方, 北区变电站, 电缆桥架, 接地, 倒闸操作, 绝缘电阻) must not be asked.
- **Tracked changes:** the chat notes 2 tracked changes. The source to translate contains 于2026年6月15日前
  and not 尽快. The translated Word file has no revision marks (`tracked_changes_accepted: 2` on write).
- **Consistency groups** (QA checks sources of 3+ characters):
  - p1.10 = p1.28;
  - p1.11 = p1.29, p1.12 = p1.30, p1.13 = p1.31;
  - p1.21 = p1.25 (≤0.2 Ω);
  - p1.35 = p1.39 = p1.43 (≥1000 MΩ).
- **Inline codes:** bold, italic, link and footnote mark must survive into the translation and the exported
  Word file. So must the PAGE field in the footer.
- **Expected QA on a correct translation:** 0 errors. Benign warnings on the headings p1.5 (1), p1.8 (2),
  p1.9 (2.1), p1.27 (2.2) and p1.45 (3).

**Vendor XLIFF: `demo/zh/jiance-baogao.vendor.en.xlf`.** XLIFF 2.0, `srcLang="zh-Hans" trgLang="en"`, 50 units,
state `translated` (`at:draft`). Unit ids and sources are exactly the extraction above. Import it on
`jiance-baogao.docx` (download menu → *Import a returned XLIFF…*).
- Import report: **`codes: ['p1.6']`**: p1.6 is refused because the vendor dropped the footnote mark
  `<x id="2"/>`. No unknown units and no source changes. On an untranslated document there are 49 changes;
  after the pipeline has translated it, units identical to the AI's translation count as unchanged (about 30
  changes in a live run).
- After accepting the proposal, QA shows the planted errors:

  | Segment | Planted error | Expected QA |
  |---|---|---|
  | p1.4 | 甲方 translated “Party A” (forbidden) | terminology **error**: forbidden “Party A” → use “Client” |
  | p1.24 | 0.35 Ω → “0.53 Ω” | numbers **error** (0.35 missing) + warning (0.53 extra) |
  | p1.46 | 2026年6月15日 → “15 May 2026” | numbers **error** (date missing) + warning (date extra) |
  | p1.47 | left in Chinese | untranslated **error** (+ length warning) |
  | p1.10 / p1.28 | same sentence translated two ways (“clear weather, ambient temperature…” vs “sunny, ambient temp.…”) | consistency **warning** on both |
  | p1.6 | dropped footnote code | refused on import, so it stays untranslated: untranslated + numbers errors until translated |

  Plus the benign heading-number warnings above.
- Totals with the zh termbase on an untranslated document: 7 errors, 10 warnings. After the pipeline has
  translated it, p1.6 keeps the AI's translation, so 4 errors (live run: 4 errors, 10 warnings). The other vendor wording (“O&M unit”, “eliminate the
  defect”, “Checked by”) is acceptable and not flagged.

---

### `anquan-peixun.pptx`: Chinese, PowerPoint, 4 slides

**Summary.** 停电作业安全培训 (safety training for outage work) for project UW-2291:
- Slide 1: title and subtitle, which demands strict 两票三制 and 五防.
- Slide 2: preparation before work, including the 保电 period 7–10 June.
- Slide 3: the Five Preventions.
- Slide 4: the Two Permits and Three Systems, plus a fixed-size slogan box.

Every slide has speaker notes. Default 4:3 template. Reference: `reference/anquan-peixun.en.md`.

**Extraction:** 26 segments; `{'pages': 4, 'with_codes': 0}`. Ids:

| Slide | Title | Body | Other | Notes |
|---|---|---|---|---|
| 1 | p1.1 | p1.2, p1.3 (subtitle; p1.3 = 严格执行两票三制，全面落实五防要求) | | p1.4, p1.5 |
| 2 | p2.1 | p2.2–p2.5 (p2.3 倒闸操作/运维单位; p2.4 110 kV, 1.5 m; p2.5 6月7日至6月10日为保电期…) | | p2.6 |
| 3 | p3.1 什么是“五防” | p3.2–p3.6 (the five rules) | | p3.7, p3.8 |
| 4 | p4.1 什么是“两票三制” | p4.2–p4.4 | p4.5 `TextBox 3`: 安全第一、预防为主、综合治理 | p4.6, p4.7 |

**Traps and expected behaviour.**
- **Forward definitions:**
  - **五防** and **两票三制** are used on slide 1 (p1.3). They are defined on slide 3 (p3.1–p3.6: the five
    anti-maloperation rules) and slide 4 (p4.2–p4.3: work permit + switching order; shift handover, patrol
    inspection, periodic testing and changeover).
  - Expected: the analysis uses the later slides, so p1.3 gets the same terms as the definition slides
    (reference: “Five Preventions”, “Two Permits and Three Systems”). No question is needed. If one is asked,
    its guess reflects slides 3–4.
- **Questions:**
  - **保电** (p2.5, p2.6) should be asked.
  - 运维单位 (p2.3, p2.6) may be.
  - Termbase terms 倒闸操作, 电网调度中心, 接地 and 北区变电站 must not be.
- **Repeat:** p3.8 = p4.7 (严禁擅自解除防误闭锁装置。): one consistency group.
- **Shrink on overflow:**
  - p4.5 is a fixed-size text box: 4.6 × 0.62 in, 20 pt bold, `<a:noAutofit/>`. The Chinese fits on one line.
    The English (“Safety first, prevention foremost, comprehensive management”) is about 4× longer.
  - Expected on download: the box gets `<a:normAutofit/>`.
  - With the reference translation, `office.write` reports `autofit: 13`: every title, body, the text box and
    every notes body grows by more than 10%.
- **Dates/numbers:** 6月7日至6月10日 (keep both dates), 45分钟, 80分, 110 kV, 1.5 m.
- **Expected QA on a correct translation:** 0 errors, 0 warnings.

---

### `quexian-qingdan.xlsx`: Chinese, Excel, 2 sheets

**Summary.** 缺陷清单 (defect list), with two sheets:
- **缺陷**: six defects with columns 编号/位置/缺陷描述/责任方/整改期限/状态. 编号 holds numbers, 整改期限 real
  Excel dates (format yyyy"年"m"月"d"日), 状态 已整改/未整改.
- **汇总**: formulas
  - `B2 =COUNTA(缺陷!A2:A7)`
  - `B3 =COUNTIF(缺陷!F:F,"已整改")`
  - `B4 =COUNTIF(缺陷!F:F,"未整改")`
  - `B5 =B3/B2`
  - `B6 =COUNTIF(缺陷!D:D,"乙方")`
  - `B9 =B7*B8`

  The formulas carry cached results 6, 3, 3, 50%, 4 and 31,250.00. The sheet also has numbers B7 625000 and
  B8 5%, and the date B10 2026-05-20.

Reference: `reference/quexian-qingdan.en.md`.

**Extraction:** 31 segments; `{'pages': 2, 'with_codes': 1, 'in_formulas': 3}`. Shared strings, with first
use and repeats:
- p1.9 乙方 (D2, +3 more), p1.10 已整改 (F2, +2 more), p1.15 未整改 (F4, +2 more);
- p1.11 110 kV开关室 (+1), p1.13 UPS室 (+1), p1.19 运维方 (+1).

Rich text: p1.20 (C7) `<g id="1">【重要】</g>2号主变110 kV侧隔离开关触头发热，红外测温82 ℃` (bold run).
formula_refs: p1.9 → 汇总!B6, p1.10 → 汇总!B3, p1.15 → 汇总!B4. Numbers and dates are cell values, not
segments.

**Traps and expected behaviour.**
- **Formula literals:** p1.9, p1.10 and p1.15 are compared against by COUNTIF formulas. Expected: the translated
  workbook updates those literals to the translations (`COUNTIF(缺陷!F:F,"Not rectified")`), so the counts stay
  3 / 3 / 4; the download menu notes it.
- **Shared strings:** one translation per shared string covers all its cells. 已整改/未整改 must not be
  translated two ways.
- **Questions:** **运维方** (p1.19, also inside p1.18) should be asked: it is the O&M side as opposed to 乙方
  (Contractor). **消缺** (p1.18) should be asked too.
- **Expected QA on a correct translation:** 0 errors. Warnings:
  - terminology warnings on p1.10/p1.15 when rendered “Rectified” / “Not rectified” (inflection; benign).
- No TM matches: the yanshou memory stores its table as one unit, not cell by cell.

---

### `vertragsauszug.pdf` (+ `vertragsauszug-scanned.pdf`): German, 2 pages

**Summary.** Auszug aus dem Bauvertrag (extract from the construction contract UW-2291-BV of 12.01.2026)
between AG and AN:
- § 4 Ausführungsfristen: start 02.02.2026, completion 13.03.2026, Behinderungsanzeige.
- § 5 Bedenken: Bedenkenanzeige.
- § 6 Vergütung und Zahlung: lump sum 1.248.500,00 EUR net + 19 % VAT, payment terms, a 0,2 %/day penalty
  capped at 5 %.
- § 7 Abnahme: formal acceptance, deemed acceptance excluded.
- § 8 Sicherheitsleistung: 5 % Sicherheitseinbehalt, returned by 31.03.2031.
- Anlage 1 – Begriffe und Abkürzungen.

Header: Umspannwerk Nord · Projekt UW-2291 · Vertragsauszug · Vertraulich. Footer: Seite 1 von 2 /
Seite 2 von 2. Reference: `reference/vertragsauszug.en.md`. Use it in the German project (`seed_demo.py`).

**Traps and expected behaviour.**
1. **Forward definition: AG / AN.**
   - Used from the intro paragraph onwards on page 1 (§ 4–§ 7).
   - Defined only on page 2, in Anlage 1: “Auftraggeber (AG): Acme Energie Netz GmbH…” and “Auftragnehmer (AN):
     Albrecht Elektrotechnik GmbH…”.
   - Expected: AG → “the Client” and AN → “the Contractor” from page 1 on, without a question. The termbase
     entries Auftraggeber → client and Auftragnehmer → contractor apply to Anlage 1.
2. **Questions the agent should ask** (not in the German termbase):
   - **Behinderungsanzeige** (§ 4 (2)): notice of hindrance / obstruction / delay.
   - **Bedenkenanzeige** (§ 5 (1), (2)): notice of concerns / reservations / objection.

   Both are VOB/B terms of art with several English renderings. May also come up: selbstschuldnerische Bürgschaft
   (§ 8 (1)), whether to expand **VOB/B**, and **fiktive Abnahme** (deemed acceptance).

   **Abnahme** and **Sicherheitseinbehalt** are in `demo/termbase.csv` (acceptance; security retention). With the
   termbase imported they must not be asked. Without a project they are reasonable questions.
3. **Paragraph across the page break.** § 7 (1) is split mid-sentence:
   - page 1 ends with …nach Zugang der Fertigstellungsanzeige beim AG;
   - page 2 starts with durchzuführen. Über die Abnahme….

   Expected: one segment with `pages: [1, 2]` (the second half starts lowercase).
4. **Repeated clause:** “(3) Die Anzeige bedarf der Schriftform und ist an die Projektleitung des AG zu richten.”
   is § 4 (3) and § 5 (3): one consistency group.
5. **Numbers, dates and amounts:**
   - 12.01.2026, 02.02.2026, 13.03.2026, 31.03.2031, 05.12.2025;
   - 1.248.500,00 EUR → EUR 1,248,500.00; 19 %, 0,2 %, 5 %;
   - 10/12 Werktage, 21 Kalendertage, 30 Tage, 5 Jahre;
   - § 6 Abs. 1 → § 6(1), LV-Position 4.2.7, Ausgabe 2016.
6. **Termbase hits:** Umspannwerk Nord (header, title, intro → Substation North; forbidden “Substation Nord”),
   Netzleitstelle, Abnahme, Gewährleistungsfrist, Sicherheitseinbehalt, Auftraggeber, Auftragnehmer.
7. **TM:** no segment reaches 60 % against `demo/memory.tmx`, so the translation memory has no effect.

**Expected QA on a correct translation:** 0 errors, 0 warnings.

---

### `demo/zh/termbase.csv`: zh→en termbase, 15 entries

Same format as `demo/termbase.csv`: `Chinese;English;Note;Forbidden`, with `|` between forbidden variants.

| Chinese | English | Forbidden |
|---|---|---|
| 北区变电站 | North District Substation | North Area Substation, Beiqu Substation |
| 甲方 | Client | Party A |
| 乙方 | Contractor | Party B |
| 承包方 | Contractor | contracting party, undertaker |
| 电缆桥架 | cable tray | cable bridge, cable rack |
| 整改 | rectification | reform, correction |
| 验收 | acceptance | check and accept, check before acceptance |
| 接地 | earth | grounding, grounded |
| 质量保证金 | retention money | quality deposit, quality guarantee deposit, quality assurance deposit |
| 质保金 | retention money | quality deposit, warranty deposit |
| 倒闸操作 | switching operation | gate switching, switchover operation |
| 工程量清单 | bill of quantities | engineering quantity list, quantity list |
| 出线间隔 | outgoing feeder bay | outlet interval, outgoing line interval |
| 电网调度中心 | network control centre | grid dispatching center, dispatch center |
| 绝缘电阻 | insulation resistance | isolation resistance |

The question terms 两票三制, 五防, 消缺, 三措一案, 运维单位/运维方 and 保电 are deliberately **not** in the
termbase. 接地 maps to “earth”, so that earthing / earthed / earth grid all satisfy the substring check.

### `demo/zh/memory.tmx`: zh→en translation memory, 9 units

Confirmed translations of `yanshou-baogao.pdf` (origin `yanshou-baogao.pdf (confirmed)`, `srclang="zh-Hans"`),
in the same conventions as `demo/memory.tmx`:
- one unit per heading or paragraph, without markdown heading markers;
- the table as one markdown-table unit;
- no unit for the diagram labels.

Units, in order:
1. the title;
2. the date line;
3. 一、验收范围;
4. the scope paragraph;
5. 二、发现的缺陷;
6. the defects table;
7. 图1：地下室设备概览;
8. 三、结论;
9. the conclusion paragraph.

The English is the text of `reference/yanshou-baogao.en.md`.

Expected: re-translating `yanshou-baogao.pdf` in the Chinese project gives exact matches for all 9 units. The
figure legend is translated normally. See `fucha-baogao.pdf` and `jiance-baogao.docx` (p1.45) for leverage in
other documents.

---

## Existing samples

### `abnahmeprotokoll.pdf` (+ `abnahmeprotokoll-scanned.pdf`): German, 2 pages

**Summary.** Abnahmeprotokoll (acceptance report) of 14.03.2026:
- the subject: the 110-kV-Schaltanlage renewal, LV-Position 4.2.7;
- a table of three defects with deadlines 30.04.2026 / 15.04.2026 / 30.04.2026;
- the result: acceptance subject to the defects, a follow-up in KW 18, a 5 % Sicherheitseinbehalt;
- the switching authorisation under BA-17 and the Netzleitstelle;
- signatures.

**Exercises.** Text-layer and scan OCR, a table, and layout-preserving PDF output from the text-layer PDF.

**Traps.**
- Termbase hits: Umspannwerk Nord, Kabelpritsche, Zwischenkreis, Abnahme, Gewährleistungsfrist,
  Sicherheitseinbehalt, Schaltberechtigung, Netzleitstelle, Auftraggeber, Auftragnehmer.
- Its confirmed translation is `demo/memory.tmx`, so re-translating it in the German project matches every
  unit exactly.

### `nachbegehung.pdf`: German, 2 pages

**Summary.** Protokoll der Nachbegehung (follow-up inspection) of 06.05.2026 for the same defects. Running
header “Umspannwerk Nord · Projekt UW-2291 · Vertraulich”; footer “Seite n von 2”.

**TM against `demo/memory.tmx`:**
- **Exact (100 %):** 2. Festgestellte Mängel; Die Mängel sind bis zu den genannten Fristen zu beseitigen. …;
  3. Ergebnis; Für die Inbetriebsetzung gilt weiterhin … Netzleitstelle anzuordnen.; 4. Unterschriften.
- **Fuzzy:**
  - Gegenstand der Nachbegehung ist … (97 %, one word);
  - Datum: 06.05.2026 | Projekt-Nr.: UW-2291 (75 %): reusing the TM date is a QA date error;
  - 1. Gegenstand der Nachbegehung (75 %).
- **No match:**
  - the title (40 %);
  - the table (67 %: a Status column instead of Frist);
  - the two new paragraphs;
  - the signature lines (the TM stores both as one unit).

This matches the README demo: 5 reused without a model call, 3 fuzzy.

### `wartungsbericht.pdf` (+ `wartungsbericht-scanned.pdf`): German, 1 page

**Summary.** Wartungsbericht (maintenance report, basement) of 02.04.2026. It has a raster diagram labelled in
German: Schaltschrank, USV-Anlage, Kabelpritsche, and in red “Erdungsanschluss fehlt”. Caption: *Abb. 1:
Anlagenübersicht Kellergeschoss*. The earthing connection is due by 30.04.2026, and the UPS runs in bypass
mode until then.

**Exercises.** Figure detection and cropping, translating the figure text as a legend, keeping the caption
attached, and termbase hits (Kabelpritsche, Netzleitstelle).

### `pruefbericht.docx`: German, Word

**Summary.** Prüfbericht Erdungsanlage (earthing test of 12.05.2026). 21 segments;
`{'pages': 2, 'tracked_changes': 2, 'with_codes': 4}`.
- p1.1: footer PAGE field.
- p1.2: header.
- p1.4: bold Erdungsanlage/Kabelpritsche and italic *unter*.
- p1.6–p1.17: table, with “in Ordnung” at p1.11 and p1.14.
- p1.18: link + footnote mark.
- p1.19: tracked deletion *vorläufig* and insertion *uneingeschränkt*.
- p1.20: date 31.05.2026.
- p2.1: footnote.

**Vendor XLIFF `demo/pruefbericht.vendor.en.xlf`:**
- Import: **21 changes**, `codes: ['p1.18']` (dropped footnote mark).
- After accepting, QA:
  - forbidden “Substation Nord” (p1.2) and “cable bridge” (p1.4);
  - “in Ordnung” translated two ways (p1.11 “OK”, p1.14 “satisfactory”);
  - untranslated p1.19 (and p1.18, refused);
  - wrong date p1.20 (31.03.2026 for 31.05.2026).

### `unterweisung.pptx`: German, PowerPoint, 3 slides

**Summary.** Unterweisung Erdungsanlagen (safety briefing): title slide, the five safety rules (bold run on
*Wiedereinschalten*, p2.3), inspection intervals. Speaker notes on slides 1–2. 12 segments; `with_codes: 1`.

### `maengelliste.xlsx`: German, Excel

**Summary.** Mängelliste (defect list), sheet “Mängel”. 18 segments;
`{'with_codes': 1, 'in_formulas': 1}`.
- “behoben” is a shared string used twice (p1.9).
- B6 is rich text (bold “Hinweis:”, p1.17).
- B7 `=COUNTIF(E2:E4,"offen")` compares against “offen” (p1.16): the translated file updates it to the translation.
- The deadlines are text, not dates.

### `yanshou-baogao.pdf` (+ `yanshou-baogao-scanned.pdf`): Chinese, 1 page

**Summary.** 设备验收报告 (equipment acceptance report) of 14 March 2026:
- scope: 110 kV switchgear renovation, bill-of-quantities item 4.2.7;
- a table of three defects with deadlines;
- a raster diagram labelled in Chinese: 配电柜, UPS电源, 电缆桥架, and in red 缺少接地连接;
- caption 图1;
- the conclusion: conditional acceptance, re-inspection in week 18, 5% 质量保证金, switching ordered by the
  电网调度中心.

The text layer uses a CJK font with wide Latin glyphs, so OCR tends to insert spaces (2026 年3 月14 日). TM keys
ignore spaces and punctuation. Reference: `reference/yanshou-baogao.en.md`. Its units are `demo/zh/memory.tmx`.

**Traps.**
- Without the zh termbase, a model may ask about 质量保证金 (quality retention vs retention money). With it
  imported, it should not.
- 配电柜 in the figure (distribution cabinet vs switchgear cabinet) is a plausible question; it is not in the
  termbase.

### `demo/termbase.csv`, `demo/memory.tmx`: German demo assets

- 12 de→en terms with forbidden variants.
- 12 TM units: the confirmed translation of `abnahmeprotokoll.pdf`.

Both are seeded by `backend/scripts/seed_demo.py` into “Acme Energie – Umspannwerk Nord” (German → English,
French).

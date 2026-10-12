"""Samples for the source check (fixing the OCR before translating): scans whose structure a vision model tends to
get wrong. Each is a one-page scan with two columns — a paragraph running from the bottom of the left column to the
top of the right one, mid-sentence, with a narrow gutter so reading straight across is tempting — and a stamp or
seal printed over the text, whose words end up inside a sentence.

    uv run python scripts/make_review_samples.py       # writes samples/review/ and the English references

- pruefvermerk-zweispaltig-scanned.pdf  German inspection note, red "GEPRÜFT" rubber stamp over the right column
- jianli-tongzhi-shuanglan-scanned.pdf  Chinese supervision notice, red round seal over the signature and text
"""

from __future__ import annotations

import io
import math
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_samples import FURNITURE_CSS, PDF_CSS, PDF_TIME, ROOT, esc, scanned  # noqa: E402

OUT = ROOT / "samples" / "review"
RED = (0.82, 0.12, 0.12)
PAGE = pymupdf.paper_rect("a4")
LEFT, RIGHT = pymupdf.Rect(56, 150, 290, 760), pymupdf.Rect(302, 150, 539, 760)  # a 12 pt gutter


def two_columns(title: str, meta: str, body_html: str, header: str, footer: str, css: str = "") -> pymupdf.Document:
    """A page with a full-width title, then the body flowing down the left column and on into the right one."""
    story = pymupdf.Story(body_html, user_css=PDF_CSS + css)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    device = writer.begin_page(PAGE)
    for column in (LEFT, RIGHT):
        more, _ = story.place(column)
        story.draw(device)
        if not more:
            break
    writer.end_page()
    writer.close()
    doc = pymupdf.open("pdf", buf.getvalue())
    assert len(doc) == 1 and not more, "the body must fit the two columns of one page"
    page = doc[0]
    page.insert_htmlbox(pymupdf.Rect(56, 30, 539, 46), f"<p>{esc(header)}</p>", css=FURNITURE_CSS)
    page.draw_line((56, 46), (539, 46), color=(0.7, 0.7, 0.7), width=0.5)
    page.insert_htmlbox(pymupdf.Rect(56, 70, 539, 140),
                        f"<h1>{esc(title)}</h1><p class='meta'>{esc(meta)}</p>", css=PDF_CSS + css)
    page.draw_line((56, 798), (539, 798), color=(0.7, 0.7, 0.7), width=0.5)
    page.insert_htmlbox(pymupdf.Rect(56, 802, 539, 818), f'<p style="text-align: right">{esc(footer)}</p>', css=FURNITURE_CSS)
    doc.set_metadata({"title": title, "creator": "make_review_samples.py", "producer": "PyMuPDF",
                      "creationDate": PDF_TIME, "modDate": PDF_TIME})
    return doc


def rubber_stamp(page: pymupdf.Page, centre: pymupdf.Point, lines: list[str], angle: float = -9) -> None:
    """A red rectangular rubber stamp, slightly turned, printed over whatever is underneath."""
    turn = pymupdf.Matrix(angle)
    w, h = 190, 22 + 16 * len(lines)
    box = pymupdf.Rect(centre.x - w / 2, centre.y - h / 2, centre.x + w / 2, centre.y + h / 2)
    shape = page.new_shape()
    shape.draw_rect(box)
    shape.draw_rect(box + (4, 4, -4, -4))
    shape.finish(color=RED, width=1.6, morph=(centre, turn), stroke_opacity=0.85)
    for i, text in enumerate(lines):
        size = 15 if i == 0 else 10
        y = box.y0 + 22 + 16 * i
        x = centre.x - pymupdf.get_text_length(text, fontname="hebo" if i == 0 else "helv", fontsize=size) / 2
        shape.insert_text((x, y), text, fontname="hebo" if i == 0 else "helv", fontsize=size, color=RED,
                          morph=(centre, turn), fill_opacity=0.85)
    shape.commit(overlay=True)


def round_seal(page: pymupdf.Page, centre: pymupdf.Point, ring: str, middle: str, radius: float = 52) -> None:
    """A red round seal (公章): the organisation's name around the rim, a star, the seal's purpose below it."""
    shape = page.new_shape()
    shape.draw_circle(centre, radius)
    shape.finish(color=RED, width=2.4, stroke_opacity=0.8)
    star = [centre + (math.cos(math.radians(-90 + 72 * k * 2)) * 15, math.sin(math.radians(-90 + 72 * k * 2)) * 15)
            for k in range(6)]
    shape.draw_polyline(star)
    shape.finish(color=RED, fill=RED, width=0.5, fill_opacity=0.8, stroke_opacity=0.8, closePath=True)
    size, span = 11.5, 230  # degrees of the rim the name takes, centred on the top
    for i, ch in enumerate(ring):
        a = math.radians(-90 - span / 2 + span * (i + 0.5) / len(ring))
        p = centre + (math.cos(a) * (radius - 13), math.sin(a) * (radius - 13))
        shape.insert_text(p + (-size / 2, size / 2.6), ch, fontname="china-s", fontsize=size, color=RED,
                          morph=(p, pymupdf.Matrix(math.degrees(a) + 90)), fill_opacity=0.8)
    w = len(middle) * 9.5
    shape.insert_text(centre + (-w / 2, 33), middle, fontname="china-s", fontsize=9.5, color=RED, fill_opacity=0.8)
    shape.commit(overlay=True)


# --------------------------------------------------------------------------- #
# German: Prüfvermerk, two columns, rubber stamp
# --------------------------------------------------------------------------- #

DE_BODY = """
<h2>1. Anlass</h2>
<p>Die Bauleitung hat am 14.03.2026 die Kabeltrasse im Kellergeschoss des Umspannwerks Nord begangen. Anlass war die
Mängelanzeige des Auftraggebers vom 02.03.2026 zur fehlenden Erdung der Kabelpritsche.</p>
<h2>2. Befund</h2>
<p>Die Kabelpritsche verläuft auf einer Länge von etwa 48 m entlang der Nordwand und trägt die Steuer- und
Messleitungen der Felder E01 bis E12. An der Kabelpritsche zwischen Achse B und Achse D fehlt die Erdungsverbindung weiterhin. Die vorhandene
Potentialausgleichsschiene ist montiert, jedoch nicht angeschlossen. Der Auftragnehmer hat zugesagt, die Verbindung
mit einem Kupferleiter 16 mm² herzustellen und den Übergangswiderstand zu messen. Die Messung ist vor der Wiederinbetriebnahme
der Unterverteilung UV-K2 durchzuführen und im Prüfprotokoll zu dokumentieren.</p>
<p>Die Beschriftung der Abgangsfelder wurde inzwischen vervollständigt; die Restarbeiten am Zwischenkreis der
USV-Anlage sind noch offen.</p>
<h2>3. Messwerte</h2>
<p>Der Isolationswiderstand der Abgänge 1 bis 6 liegt zwischen 120 MΩ und 410 MΩ und damit über dem Grenzwert von
1 MΩ. Der Schleifenwiderstand am Abgang 4 beträgt 0,38 Ω. Die Auslösezeit der Fehlerstrom-Schutzeinrichtung wurde mit
23 ms gemessen. Die Werte für die Kabelpritsche können erst nach dem Anschluss der Erdungsverbindung ermittelt werden.</p>
<h2>4. Bewertung</h2>
<p>Der Mangel ist sicherheitsrelevant, weil bei einem Isolationsfehler an der Pritsche eine gefährliche Berührungsspannung
anstehen kann. Bis zur Beseitigung darf die USV-Anlage nur im Bypass-Betrieb gefahren werden, und der Zugang zum
Kellergeschoss bleibt auf eingewiesenes Personal beschränkt. Die Abnahme bleibt unter Vorbehalt bestehen.</p>
<h2>5. Weiteres Vorgehen</h2>
<p>Frist für die Mängelbeseitigung ist der 30.04.2026. Der Auftragnehmer meldet die Fertigstellung schriftlich und legt
das Messprotokoll vor. Die Nachbegehung findet in der 18. Kalenderwoche statt. Bis dahin wird ein Einbehalt von 5 % der
Abrechnungssumme vorgenommen.</p>
<h2>6. Verteiler</h2>
<p>Auftraggeber (Netzbetrieb), Auftragnehmer (Bauleitung Elektro), Fachplaner TGA, Akte UW-2291.</p>
<p class="sign">Aufgestellt: K. Albrecht, Bauleitung</p>
"""

DE_EN = """# Inspection note – earthing of the cable tray (two columns, stamp)

*Running header:* Substation North · Project UW-2291 · Inspection note

Date: 14 March 2026 | Project no.: UW-2291 | Reference: defect notice of 2 March 2026

## 1. Occasion

On 14 March 2026 the site management inspected the cable route in the basement of Substation North. The occasion was
the client's defect notice of 2 March 2026 about the missing earthing of the cable tray.

## 2. Findings

The cable tray runs about 48 m along the north wall and carries the control and measurement cables of bays E01 to E12.
The earth connection of the cable tray between axis B and axis D is still missing. The equipotential bonding bar is
mounted but not connected. The contractor has undertaken to make the connection with a 16 mm² copper conductor and to
measure the contact resistance. The measurement must be carried out before the sub-distribution board UV-K2 is put
back into operation, and recorded in the test report.

The labelling of the outgoing feeders has since been completed; the remaining work on the UPS DC link is still open.

## 3. Measurements

The insulation resistance of outgoing feeders 1 to 6 is between 120 MΩ and 410 MΩ, above the 1 MΩ limit. The loop
resistance of feeder 4 is 0.38 Ω. The tripping time of the residual-current device was measured at 23 ms. The values
for the cable tray can only be measured once the earth connection is in place. *(This paragraph runs from the bottom of
the left column to the top of the right one, breaking the word "Fehlerstrom-Schutzeinrichtung" — residual-current
device — across the columns.)*

## 4. Assessment

The defect is safety-relevant, because an insulation fault on the tray could cause a dangerous touch voltage. Until it
is remedied, the UPS may only be run in bypass mode, and access to the basement is restricted to instructed staff. The
acceptance remains subject to reservations.

*Stamp, printed in red over this section:* **CHECKED** · 14 March 2026 · Site management UW-2291

## 5. Next steps

The deadline for remedying the defect is 30 April 2026. The contractor reports completion in writing and submits the
measurement record. The follow-up inspection takes place in calendar week 18. Until then, 5% of the invoiced amount is
retained.

## 6. Distribution

Client (network operations), contractor (electrical site management), building services designer, file UW-2291.

Prepared by: K. Albrecht, site management

*Footer:* Page 1 of 1

---

What to check before translating (docs/TESTING.md, "Fixing the OCR before translating"): section 3 must be one
paragraph, with "Fehlerstrom-Schutzeinrichtung" whole — not split at the column break, not interleaved with the right
column's lines — and the stamp's words ("GEPRÜFT · 14.03.2026 · Bauleitung UW-2291") must be a line of their own, not
inside the section 4 text.
"""

# --------------------------------------------------------------------------- #
# Chinese: 监理通知单, two columns, round seal
# --------------------------------------------------------------------------- #

ZH_CSS = "* {font-family: sans-serif;} h1 {font-size: 15pt;}"
ZH_BODY = """
<h2>一、事由</h2>
<p>2026年3月14日，监理部对北区变电站地下室电缆通道进行了专项检查。检查依据为甲方2026年3月2日发出的缺陷通知单。</p>
<h2>二、检查情况</h2>
<p>电缆桥架沿北墙敷设，全长约48米，承载E01至E12间隔的控制及测量电缆。B轴至D轴之间的电缆桥架仍未接地。等电位连接排已安装，但尚未连接。乙方承诺采用16 mm²铜芯导线完成跨接，并测量接触电阻。
测量须在UV-K2分配电箱重新投运前完成，并记入试验报告。出线间隔标识已完善，UPS直流母线的遗留工作尚未完成。</p>
<p>检查中还发现，部分电缆在桥架转角处的弯曲半径不足，个别电缆标识牌缺失。乙方已安排人员对相关电缆重新整理并补挂标识牌，预计于2026年3月20日完成。</p>
<h2>三、监理意见</h2>
<p>该缺陷涉及安全：桥架一旦发生绝缘故障，可能出现危险的接触电压。整改完成前，UPS只允许在旁路方式下运行，验收结论维持为有条件验收。</p>
<h2>四、测量结果</h2>
<p>出线1至出线6的绝缘电阻为120 MΩ至410 MΩ，均高于1 MΩ的限值。出线4的回路电阻为0.38 Ω。剩余电流保护装置的动作时间实测为23 ms。
电缆桥架的接地数值须在跨接完成后方可测得。</p>
<h2>五、安全措施</h2>
<p>整改作业须办理第一种工作票。作业前应对相关回路验电并装设接地线，作业区域应设置围栏和警示标识，并安排专人监护。
如需动火作业，须另行办理动火工作票，并配备灭火器材。</p>
<h2>六、整改要求</h2>
<p>乙方须于2026年4月30日前完成整改，并书面回复监理部，同时提交测量记录。整改期间，地下室仅限经培训的人员进入。复查定于第18周进行。
在此之前，暂扣结算金额的5%。</p>
<h2>七、抄送</h2>
<p>甲方运维单位、乙方项目部、设计单位、工程档案。</p>
<h2>八、附件</h2>
<p>1. 现场照片8张；2. 绝缘电阻测试记录；3. 甲方缺陷通知单（2026年3月2日）。</p>
<p class="sign">监理工程师：张伟</p>
<p class="sign">2026年3月14日</p>
"""

ZH_EN = """# Supervision notice – earthing of the cable tray (two columns, seal)

*Running header:* North District Substation Renovation Project · UW-2291 · Supervision notice

Date: 14 March 2026 | Notice no.: JL-2026-017 | Project no.: UW-2291

## 1. Subject

On 14 March 2026 the supervision office carried out a special inspection of the basement cable channel of the North
District Substation, on the basis of the defect notice issued by Party A (the client) on 2 March 2026.

## 2. Findings

The cable tray runs about 48 m along the north wall and carries the control and measurement cables of bays E01 to E12.
The cable tray between axis B and axis D is still not earthed. The equipotential bonding bar has been installed but
is not yet connected. Party B (the contractor) has undertaken to make the bonding connection with a 16 mm² copper
conductor and to measure the contact resistance. The measurement must be made before the UV-K2 distribution box is put
back into operation, and recorded in the test report. The labelling of the outgoing bays has been completed; the
remaining work on the UPS DC bus is not finished yet.

The inspection also found that some cables do not keep their minimum bending radius at the corners of the tray, and a
few cable labels are missing. Party B has arranged for the cables to be re-laid and the labels added, expected to be
finished by 20 March 2026.

## 3. Supervisor's opinion

The defect concerns safety: an insulation fault on the tray could cause a dangerous touch voltage. Until it is rectified, the UPS may only run in bypass mode, and the acceptance remains a
conditional acceptance.

## 4. Measurements

The insulation resistance of outgoing feeders 1 to 6 is between 120 MΩ and 410 MΩ, above the 1 MΩ limit. The loop
resistance of feeder 4 is 0.38 Ω. The tripping time of the residual-current device was measured at 23 ms. The earthing
values of the cable tray can only be measured once the bonding is in place.

## 5. Safety measures

The rectification work requires a type 1 work permit. Before work, the circuits concerned must be tested for absence of
voltage and earthed; the work area must be fenced off and signposted, with a dedicated safety supervisor. Any hot work
needs a separate hot-work permit and fire extinguishers on hand. *(This paragraph runs from the bottom of the left column
to the top of the right one, mid-sentence.)*

## 6. Rectification required

Party B must complete the rectification by 30 April 2026 and reply to the supervision office in writing. The
re-inspection is scheduled for week 18. Until then, 5% of the settlement amount is withheld. During the rectification,
only trained staff may enter the basement; Party B also submits the measurement records.

## 7. Copies to

Party A's operation and maintenance unit, Party B's project department, the design institute, the project file.

## 8. Attachments

1. 8 site photos; 2. insulation resistance test record; 3. Party A's defect notice (2 March 2026).

Supervising engineer: Zhang Wei — 14 March 2026

*Red round seal over the attachments and the signature:* 北区变电站改造工程监理部 (Supervision Office, North District Substation
Renovation Project) around the rim, a star, and 监理专用章 (supervision seal) in the middle.

*Footer:* Page 1 of 1

---

What to check before translating: section 5 (safety measures) is one paragraph, read from the bottom of the left
column on into the right one; the seal's characters (北区变电站改造工程监理部 / 监理专用章) are their own line, not mixed
into the attachments list or 张伟's signature.
"""


def check_columns(doc: pymupdf.Document) -> None:
    """Both columns hold text, and the left column ends mid-sentence (the trap: one paragraph, two columns)."""
    blocks = [b for b in doc[0].get_text("blocks") if 150 <= b[1] < 765]
    left = [b for b in blocks if b[2] <= LEFT.x1 + 1]
    right = [b for b in blocks if b[0] >= RIGHT.x0 - 1]
    assert left and right and max(b[3] for b in right) > 420, "the right column must hold a good part of the text"
    last = max(left, key=lambda b: b[3])[4].strip()
    assert last[-1] not in ".。:：", f"the left column must end mid-sentence, not with: …{last[-20:]!r}"


def build_de() -> pymupdf.Document:
    doc = two_columns("Prüfvermerk – Erdung der Kabelpritsche",
                      "Datum: 14.03.2026 | Projekt-Nr.: UW-2291 | Bezug: Mängelanzeige vom 02.03.2026", DE_BODY,
                      "Umspannwerk Nord · Projekt UW-2291 · Prüfvermerk", "Seite 1 von 1")
    rubber_stamp(doc[0], pymupdf.Point(420, 330), ["GEPRÜFT", "14.03.2026 · Bauleitung UW-2291"])
    check_columns(doc)
    return doc


def build_zh() -> pymupdf.Document:
    doc = two_columns("监理通知单——地下室电缆桥架接地", "日期：2026年3月14日 ｜ 编号：JL-2026-017 ｜ 项目编号：UW-2291", ZH_BODY,
                      "北区变电站改造工程 · UW-2291 · 监理通知", "第 1 页 共 1 页", css=ZH_CSS)
    page = doc[0]
    sign = page.search_for("监理工程师")
    centre = pymupdf.Point(sign[0].x1 + 18, sign[0].y0 + 6) if sign else pymupdf.Point(420, 600)
    round_seal(page, centre, "北区变电站改造工程监理部", "监理专用章")
    check_columns(doc)
    return doc


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, doc, english in (("pruefvermerk-zweispaltig", build_de(), DE_EN), ("jianli-tongzhi-shuanglan", build_zh(), ZH_EN)):
        (OUT / f"{name}-scanned.pdf").write_bytes(scanned(doc))
        (ROOT / "samples" / "reference" / f"{name}.en.md").write_text(english)
        print(f"samples/review/{name}-scanned.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

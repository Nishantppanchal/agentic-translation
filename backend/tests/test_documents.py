"""Segmentation across page breaks."""

from translator.document.pages import segments_from_pages


def _segs(*pages: str) -> list[dict]:
    return segments_from_pages(list(enumerate(pages, start=1)))


def test_hyphenated_word_split_by_page_break_is_rejoined():
    segs = _segs(
        "# Titel\n\nDie Mängel sind bis zu den genannten Fristen zu beseitigen. Die Gewähr-",
        "leistungsfrist beginnt mit dem Tag der Abnahme.\n\n## Ergebnis",
    )
    assert [s["id"] for s in segs] == ["p1.1", "p1.2", "p2.1"]
    assert segs[1]["source"].endswith("Die Gewährleistungsfrist beginnt mit dem Tag der Abnahme.")
    assert segs[1]["pages"] == [1, 2]
    assert segs[2]["source"] == "## Ergebnis"


def test_capitalised_german_noun_continues_the_sentence():
    segs = _segs(
        "Die Gewährleistungsfrist für alle Leistungen des Auftragnehmers beginnt mit dem Tag der",
        "Abnahme durch den Auftraggeber.",
    )
    assert len(segs) == 1 and segs[0]["source"].endswith("mit dem Tag der Abnahme durch den Auftraggeber.")


def test_chinese_is_joined_without_a_space():
    segs = _segs("本次验收范围为110千伏开关设备的更新改造，包括二次系统以及全部相关的", "辅助设施。")
    assert len(segs) == 1 and segs[0]["source"] == "本次验收范围为110千伏开关设备的更新改造，包括二次系统以及全部相关的辅助设施。"


def test_page_number_at_the_bottom_is_skipped():
    segs = _segs(
        "Die Arbeiten wurden gemäß LV-Position 4.2.7 ausgeführt und der Auftragnehmer hat die\n\n- 2 -",
        "Prüfprotokolle vollständig übergeben.",
    )
    assert segs[0]["source"].endswith("hat die Prüfprotokolle vollständig übergeben.")
    assert segs[1]["source"] == "- 2 -" and not segs[1]["translatable"]


def test_complete_sentences_headings_and_short_lines_are_not_joined():
    # Sentence ends with a period.
    assert len(_segs("Die Anlage wird unter Vorbehalt der genannten Mängel abgenommen.", "Eine Nachbegehung folgt.")) == 2
    # Next page starts with a heading.
    assert len(_segs("Die Arbeiten wurden ausgeführt und die Protokolle werden nachgereicht von der", "## Ergebnis")) == 2
    # A short caption or signature line is not running text.
    assert len(_segs("Abb. 1: Anlagenübersicht Kellergeschoss", "Der Erdungsanschluss ist herzustellen.")) == 2
    assert len(_segs("Für den Auftragnehmer: K. Albrecht, Bauleiter", "Die Abnahme ist erfolgt.")) == 2
    # Tables never merge.
    assert len(_segs("| a | b |\n|---|---|\n| 1 | 2 |", "weiter im Text ohne Großbuchstaben am Anfang.")) == 2


def test_headers_footers_and_page_numbers_are_segments():
    segs = _segs(
        "[[HEADER]] Vertraulich – Projekt UW-2291\n\n# Titel\n\nDie Gewährleistungsfrist für alle Leistungen des Auftragnehmers beginnt mit dem Tag der\n\n[[FOOTER]] Seite 1 von 2",
        "[[HEADER]] Vertraulich – Projekt UW-2291\n\nförmlichen Abnahme durch den Auftraggeber.\n\n[[FOOTER]] 2",
    )
    kinds = [(s["id"], s["kind"], s["translatable"]) for s in segs]
    assert kinds == [
        ("p1.1", "header", True), ("p1.2", "heading", True), ("p1.3", "paragraph", True),
        ("p1.4", "footer", True), ("p2.1", "header", True), ("p2.2", "footer", False),  # bare page number: copied
    ]
    # The paragraph still joins across footer → page break → header.
    assert segs[2]["source"].endswith("mit dem Tag der förmlichen Abnahme durch den Auftraggeber.") and segs[2]["pages"] == [1, 2]

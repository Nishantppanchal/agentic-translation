"""QA checks (one table per check), ignore fingerprints, forced review issues, and find & replace."""

from __future__ import annotations

import asyncio

import pytest
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService

from translator import projects, qa, replace, segments
from translator import state as st


def _seg(source: str, target: str | None, sid: str = "p1.1", kind: str = "paragraph", **extra) -> dict:
    return {"id": sid, "page": 1, "kind": kind, "source": source, "target": target, "translatable": True, **extra}


def _issues(check: str, seg: dict, terms: list[dict] | None = None, target_lang: str = "English") -> list[tuple[str, str]]:
    return [(i["severity"], i["message"]) for i in qa.run([seg], terms or [], target_lang, only=[check])]


# --------------------------------------------------------------------------- #
# One table per check
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source, target, expected", [
    ("Die Mängel sind bis zum 30.04.2026 zu beseitigen.", "The defects must be rectified by 30 April 2026.", []),
    ("Die Mängel sind bis zum 30.04.2026 zu beseitigen.", "The defects must be rectified by 04/30/2026.", []),
    ("Die Mängel sind bis zum 30.04.2026 zu beseitigen.", "The defects must be rectified by 31 April 2026.",
     ["error:Date 30.04.2026", "warning:Date 31 April 2026"]),
    ("bis zum 30.04. herzustellen", "to be made by 30 April", []),
    ("5 % von 1.500,50 EUR", "5% of EUR 1,500.50", []),
    ("Länge 1.000 m", "Length 1,000 m", []),
    ("gemäß LV-Position 4.2.7", "in accordance with LV item 4.2", ["error:Number 4.2.7", "warning:Number 4.2"]),
    ("in der 18. KW", "in calendar week 18", []),
    ("um 14:30 Uhr", "at 2:30 pm", []),
    ("Spannung 110 kV", "voltage 220 kV", ["error:Number 110", "warning:Number 220"]),
    ("本次验收日期为2026年4月30日，电压110千伏。", "The acceptance date is 30 April 2026, voltage 110 kV.", []),
    ("Defects 1 and 2 may be closed.", "Die Mängel 1 und 2 können geschlossen werden.", []),  # "2 may" is not a date
])
def test_numbers_and_dates(source, target, expected):
    found = [f"{sev}:{msg.split(' from the source')[0].split(' is in the')[0]}" for sev, msg in _issues("numbers", _seg(source, target))]
    assert found == expected


TERMS = [
    {"source": "Kabelpritsche", "target": "cable tray", "forbidden": ["cable bridge"], "case_sensitive": False},
    {"source": "LV", "target": "bill of quantities", "forbidden": [], "case_sensitive": True},
]


@pytest.mark.parametrize("source, target, expected", [
    ("Die Kabelpritsche ist geerdet.", "The cable tray is earthed.", []),
    ("Die Kabelpritschen sind geerdet.", "The cable trays are earthed.", []),  # not a whole word in the source
    ("Die Kabelpritsche ist geerdet.", "The cable trays are earthed.", []),  # inflected target still counts
    ("Die Kabelpritsche ist geerdet.", "The cable bridge is earthed.",  # one finding, not two
     [("error", 'Forbidden translation "cable bridge" for "Kabelpritsche" → use "cable tray".')]),
    ("gemäß LV-Position", "according to the BoQ item", [("warning", '"LV" should be translated as "bill of quantities".')]),
    ("die lv-position", "the item", []),  # case-sensitive term doesn't match
])
def test_terminology(source, target, expected):
    assert _issues("terminology", _seg(source, target), TERMS) == expected


@pytest.mark.parametrize("source, target, kind, expected", [
    ("## 3. Ergebnis", "## 3. Result", "heading", []),
    ("## 3. Ergebnis", "3. Result", "heading", ["error"]),
    ("## 3. Ergebnis", "### 3. Result", "heading", ["error"]),
    ("| a | b |\n|---|---|\n| 1 | 2 |", "| a | b |\n|---|---|\n| 1 | 2 |", "table", []),
    ("| a | b |\n|---|---|\n| 1 | 2 |", "| a |\n|---|\n| 1 |", "table", ["error"]),
    ("- eins\n- zwei", "- one, two", "list", ["warning"]),
    ("Die **Anlage** ist fertig.", "The plant is ready.", "paragraph", ["warning"]),
    ('Klicken Sie <g id="1">hier</g><x id="2"/>.', 'Click <g id="1">here</g><x id="2"/>.', "paragraph", []),
    ('Klicken Sie <g id="1">hier</g><x id="2"/>.', 'Click <g id="1">here</g>.', "paragraph", ["error"]),
])
def test_markup(source, target, kind, expected):
    assert [sev for sev, _ in _issues("markup", _seg(source, target, kind=kind))] == expected


@pytest.mark.parametrize("source, target, target_lang, expected", [
    ("Die Anlage ist abgenommen.", "The plant is accepted.", "English", []),
    ("Die Anlage ist abgenommen.", "The plant is accepted", "English", ["punctuation"]),
    ("Folgende Mängel:", "The following defects:", "English", []),
    ("本次验收合格。", "The acceptance passed.", "English", []),  # 。 ↔ .
    ("Ist die Anlage geerdet?", "La installation est-elle mise à la terre ?", "French", []),  # French spacing is fine
    ("Die Anlage ist abgenommen.", "The plant  is accepted .", "English", ["spaces", "spaces"]),
    ("编号", "No.", "English", []),  # an abbreviation's full stop isn't sentence punctuation
    ("Abb. 3", "Fig.", "English", []),
    ("Spannung ca.", "approx.", "English", []),
    ("Die Prüfung ist abgeschlossen", "The test is complete.", "English", ["punctuation"]),  # a real one still counts
    ("कार्य पूरा हो गया है।", "The work is complete.", "English", []),  # Devanagari danda ↔ .
    ("هل المنشأة مؤرضة؟", "Is the installation earthed?", "English", []),  # Arabic question mark ↔ ?
    ("ตรวจรับงานแบบมีเงื่อนไข", "Conditional acceptance.", "English", []),  # Thai ends sentences without a mark
    ("Είναι γειωμένη\u037e", "Is it earthed?", "English", []),  # Greek question mark
])
def test_punctuation_and_spaces(source, target, target_lang, expected):
    seg = _seg(source, target)
    found = [i["check"] for i in qa.run([seg], [], target_lang, only=["punctuation", "spaces"])]
    assert found == expected


def test_untranslated_merged_consistency_and_length():
    segs = [
        _seg("Die Anlage wird unter Vorbehalt abgenommen.", "Die Anlage wird unter Vorbehalt abgenommen.", "p1.1"),
        _seg("Ergebnis", "Result", "p1.2", kind="heading"),
        _seg("Ergebnis", "Outcome", "p2.1", kind="heading"),
        _seg("Eine Nachbegehung ist vorgesehen.", "A follow-up inspection is planned.", "p2.2", flags=["merged"]),
        *[_seg(f"Dies ist ein normaler Satz Nummer {n}.", f"This is a normal sentence number {n}.", f"p3.{n}") for n in range(1, 5)],
        _seg("Kurzer Satz mit Inhalt.", "A short sentence with content that goes on and on and on and on and on and on.", "p4.1"),
    ]
    found = {(i["check"], i["segment_id"], i["severity"]) for i in qa.run(segs, [], "English")}
    assert ("untranslated", "p1.1", "error") in found
    assert ("merged", "p2.2", "error") in found
    assert {("consistency", "p1.2", "warning"), ("consistency", "p2.1", "warning")} <= found
    assert ("length", "p4.1", "warning") in found
    assert not any(c == "length" and s.startswith("p3") for c, s, _ in found)


def test_non_translatable_segments_are_skipped():
    seg = {**_seg("- 2 -", "- 2 -", kind="footer"), "translatable": False}
    assert qa.run([seg], [], "English") == []


# --------------------------------------------------------------------------- #
# Fingerprints, ignore, forced review issues
# --------------------------------------------------------------------------- #


def test_ignored_issue_comes_back_when_the_text_changes():
    seg = _seg("Spannung 110 kV", "voltage 220 kV")
    [missing, _extra] = qa.run([seg], [], "English", only=["numbers"])
    again = qa.run([seg], [], "English", ignored=[missing["id"]], only=["numbers"])
    assert again[0]["ignored"] and qa.summary(again)["ignored"] == 1 and qa.summary(again)["errors"] == 0
    changed = qa.run([{**seg, "target": "voltage 230 kV"}], [], "English", ignored=[missing["id"]], only=["numbers"])
    assert not changed[0]["ignored"]


def test_forced_review_issues_are_errors_only_and_respect_ignores():
    pid = projects.get_store().create_project("P", "German")["id"]
    projects.get_store().upsert_term(pid, "Kabelpritsche", "cable tray", forbidden=["cable bridge"])
    segs = [
        _seg("Die Kabelpritsche bis 30.04.2026.", "The cable bridge by 30 April 2026.", "p1.1"),
        _seg("Ergebnis", "Outcome.", "p1.2", kind="heading"),  # punctuation warning only
    ]
    state = {"doc:project_id": pid, "doc:target_lang": "English", "doc:qa_ignored": []}
    forced = qa.forced_review_issues(state, segs)
    assert [(f["segment_id"], f["category"], f["severity"]) for f in forced] == [("p1.1", "terminology", "major")]
    assert "cable bridge" in forced[0]["note"] and forced[0]["auto"]
    ignored = {**state, "doc:qa_ignored": [i["id"] for i in qa.document_qa(state, segs)]}
    assert qa.forced_review_issues(ignored, segs) == []


# --------------------------------------------------------------------------- #
# Find & replace
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("find, repl, opts, target, expected", [
    ("plant", "installation", {}, "The plant and the Plant.", "The installation and the Installation."),  # keeps case
    ("cable tray", "cable bridge", {}, "Cable tray in the basement", "Cable bridge in the basement"),
    ("plant", "installation", {"case": True}, "The plant and the Plant.", "The installation and the Plant."),
    ("tray", "rack", {"whole_word": True}, "cable tray, cable trays", "cable rack, cable trays"),
    (r"(\d+)/(\d+)/(\d{4})", "$1.$2.$3", {"regex": True}, "by 30/04/2026", "by 30.04.2026"),
    (r"(\d+)/(\d+)", r"\2-\1", {"regex": True}, "1/2", "2-1"),
    ("a.b", "x", {}, "a.b and acb", "x and acb"),  # literal unless regex
    ("验收", "检验", {"whole_word": True}, "本次验收合格", "本次检验合格"),  # CJK: no word boundaries
])
def test_find_and_replace_preview(find, repl, opts, target, expected):
    pattern = replace.compile_find(find, **{k: v for k, v in opts.items() if k != "regex"}, regex=opts.get("regex", False))
    [m], locked = replace.matches([_seg("x", target)], pattern, repl, regex=opts.get("regex", False))
    assert m["after"] == expected and locked == 0


def test_bad_patterns_are_reported():
    with pytest.raises(replace.ReplaceError):
        replace.compile_find("(unclosed", regex=True)
    with pytest.raises(replace.ReplaceError):
        replace.matches([_seg("x", "a b")], replace.compile_find("(a) (b)", regex=True), r"\3", regex=True)


def test_replace_applies_as_human_edits_in_one_version_and_skips_locked():
    async def main():
        sessions, artifacts = InMemorySessionService(), InMemoryArtifactService()
        segs = {
            "p1.1": _seg("A", "The plant is ready.", "p1.1", status="confirmed", origin="mt"),
            "p1.2": _seg("B", "The plant is old.", "p1.2", status="draft", origin="mt"),
            "p1.3": _seg("C", "Another plant.", "p1.3", status="draft", origin="mt", locked=True),
            "p1.4": _seg("D", "No match here.", "p1.4", status="draft", origin="mt"),
        }
        s = await sessions.create_session(app_name="t", user_id="u", state={
            "doc:status": "ready", "doc:seg_ids": list(segs), "doc:versions": [],
            "doc:proposal": {"id": "x", "notes": [], "glossary": {}, "changes": [
                {"segment_id": "p1.2", "field": "target", "before": "The plant is old.", "after": "agent text"},
                {"segment_id": "p1.4", "field": "target", "before": "No match here.", "after": "agent text 2"}]},
            **{st.seg_key(k): v for k, v in segs.items()}})
        pattern = replace.compile_find("plant")
        preview, locked = replace.matches(st.get_segments(s.state), pattern, "installation", scope="unconfirmed")
        assert [m["segment_id"] for m in preview] == ["p1.2"] and locked == 1  # confirmed out of scope, locked skipped

        result = await segments.replace_in_targets(sessions, artifacts, s, "plant", "installation", ids=["p1.1", "p1.2"])
        assert result == {"changed": ["p1.1", "p1.2"], "version": 1, "locked": 1}
        s = await sessions.get_session(app_name="t", user_id="u", session_id=s.id)
        p11, p12 = (st.normalize(st.get_segment(s.state, k)) for k in ("p1.1", "p1.2"))
        assert (p11["target"], p11["status"], p11["origin"]) == ("The installation is ready.", "draft", "human")
        assert p12["target"] == "The installation is old."
        assert st.get_segment(s.state, "p1.3")["target"] == "Another plant."
        assert s.state["doc:versions"][-1]["note"] == "Find & replace: “plant” → “installation”"
        assert [c["segment_id"] for c in s.state["doc:proposal"]["changes"]] == ["p1.4"]  # the person's edit wins

    asyncio.run(main())

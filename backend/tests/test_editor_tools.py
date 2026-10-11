from types import SimpleNamespace

from translator import state as st
from translator.agents.editor_tools import get_segments, replace_in_translation, set_glossary_term, update_segment


def _ctx():
    segs = {
        "p1.1": {"id": "p1.1", "page": 1, "source": "a", "target": "The cable gland is loose.", "translatable": True},
        "p2.1": {"id": "p2.1", "page": 2, "source": "b", "target": "Replace the cable gland.", "translatable": True},
    }
    state = {"doc:seg_ids": list(segs), "doc:termbase": {"Kabelpritsche": "cable gland"}}
    state.update({st.seg_key(k): v for k, v in segs.items()})
    return SimpleNamespace(state=state)


def test_edits_are_staged_not_applied():
    ctx = _ctx()
    result = replace_in_translation("cable gland", "cable tray", [], ctx)
    assert result["proposed_in"] == ["p1.1", "p2.1"]
    assert st.get_segment(ctx.state, "p2.1")["target"] == "Replace the cable gland."  # committed text untouched
    # Reads show the proposed text, so the agent can keep refining it.
    [seg] = get_segments(["p2.1"], ctx)["segments"]
    assert seg["translation"] == "Replace the cable tray." and seg["pending_approval"]
    # Further edits compose on top of the proposal; the "before" stays the committed text.
    update_segment("p2.1", "Replace the cable tray now.", ctx)
    change = next(c for c in ctx.state["doc:proposal"]["changes"] if c["segment_id"] == "p2.1")
    assert change == {"segment_id": "p2.1", "field": "target", "before": "Replace the cable gland.", "after": "Replace the cable tray now."}


def test_reverting_an_edit_drops_it_from_the_proposal():
    ctx = _ctx()
    update_segment("p1.1", "Something else.", ctx)
    update_segment("p1.1", "The cable gland is loose.", ctx)
    assert ctx.state["doc:proposal"] is None


def test_glossary_is_proposed_and_hides_termbase_choice():
    ctx = _ctx()
    set_glossary_term("Kabelpritsche", "cable tray", "", ctx)
    assert ctx.state["doc:proposal"]["glossary"] == {"Kabelpritsche": {"target": "cable tray", "note": ""}}
    assert "doc:glossary" not in ctx.state  # applied only on accept
    assert "Kabelpritsche" in st.termbase_text(ctx.state)


def test_replace_is_case_insensitive_and_keeps_case():
    ctx = _ctx()
    ctx.state[st.seg_key("p1.1")]["target"] = "# Defects\n\nAll defects (DEFECTS) listed."
    replace_in_translation("defects", "deficiencies", [], ctx)
    [change] = ctx.state["doc:proposal"]["changes"]
    assert change["after"] == "# Deficiencies\n\nAll deficiencies (DEFICIENCIES) listed."
    # Acronym-style replacements keep their casing.
    ctx = _ctx()
    ctx.state[st.seg_key("p1.1")]["target"] = "per lv position 4.2.7"
    replace_in_translation("LV position", "BoQ item", [], ctx)
    assert ctx.state["doc:proposal"]["changes"][0]["after"] == "per BoQ item 4.2.7"

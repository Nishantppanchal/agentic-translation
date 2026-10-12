"""samples/languages/: the acceptance report in every source language the app offers (scripts/make_language_samples.py)."""

import sys
from pathlib import Path

import pytest

from translator.document.pages import load_pages
from translator.languages import LANGUAGES, lang_code

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from make_language_samples import LANGS, OUT, source_texts  # noqa: E402
from make_samples import norm  # noqa: E402


def test_every_source_language_has_a_sample():
    # German and Chinese (Simplified) have their own, larger sample set; English is the target.
    expected = {lang_code(name) for name in LANGUAGES} - {"en", "de", "zh-Hans"}
    assert {lang.code for lang in LANGS} == expected


@pytest.mark.parametrize("lang", LANGS, ids=lambda lang: lang.code)
def test_the_samples_are_what_they_say(lang):
    scan = OUT / f"acceptance-{lang.code}-scanned.pdf"
    [page] = load_pages(scan.read_bytes(), scan.name)
    assert page.is_scan and not page.has_text_layer
    text = OUT / f"acceptance-{lang.code}.pdf"
    if lang.code in ("ar", "hi", "bn", "th"):  # shaped scripts: PyMuPDF's text layer doesn't round-trip, so scan only
        assert not text.exists()
        return
    [page] = load_pages(text.read_bytes(), text.name)
    assert page.has_text_layer and not page.is_scan and len(page.figures) == 1  # the diagram is an embedded picture
    layer = norm(page.text_layer)
    assert all(norm(t) in layer for t in source_texts(lang))

"""Ingest pipeline as an ADK Workflow graph.

    START → ocr → check_source → analyse → ask → translate → clarify → review ─┬─(refine)→ refine → review
                                                                               └─(done)──→ polish → finalize

* `ocr`       fans out per page: vision OCR agent, then OCR-checker agent (image vs text). The check is
              skipped where the transcription matches the PDF's own text layer on a page without
              pictures; each page's result is cached so a retry doesn't read it again. Text files are
              read as they are.
* `check_source` human-in-the-loop: PDFs and images pause so the person can compare the reading with the
              page images and have the chat fix it (`document/source_check.py`) before anything is translated.
* `analyse`   reads the WHOLE document before translating: writes the brief up front and fixes the key
              terms once (forward definitions included); terms whose options differ in meaning become
              questions, explained in plain English with English options and a recommendation.
* `ask`       human-in-the-loop: pauses ONCE for those questions; answers go into the glossary (and the
              project termbase), so the translation uses them from the first page.
* `translate` goes page by page IN ORDER: each call carries the brief, the previous text (source +
              translation) and the running termbase; the translator records new term choices and
              may still flag a term it can't resolve.
* `clarify`   pauses again only for such late terms; answers re-translate the affected segments.
* `review`    fans out per page: reviewer agent lists issues; routes to refine or done.
* `refine`    fans out per page with issues: refiner agent rewrites flagged segments.
* `polish`    one translation per repeated sentence and the termbase applied (`tasks.consistency_fixes`).
* `finalize`  saves the reviewed version and marks the document ready.

Function nodes stream progress by yielding `Event(state=...)`; the LLM work is done
by single-turn `LlmAgent`s invoked through `ctx.run_node` with a concurrency cap.
Bulk data (page images, segments) never travels as node output — it lives in the
source artifact and in session state, so session events stay small.
"""

from __future__ import annotations

from google.adk import Workflow
from google.adk.workflow import START

from .steps.analyse import analyse, ask
from .steps.finish import finalize, polish
from .steps.read import check_source, ocr
from .steps.review import refine, review
from .steps.translate import clarify, translate

PIPELINE_NAME = "ingest"


ingest_workflow = Workflow(
    name=PIPELINE_NAME,
    edges=[
        (START, ocr),
        (ocr, check_source, analyse, ask, translate, clarify, review),
        (review, {"refine": refine, "done": polish}),
        (refine, review),
        (polish, finalize),
    ],
)

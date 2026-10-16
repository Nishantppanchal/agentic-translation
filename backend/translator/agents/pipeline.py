"""Ingest pipeline as an ADK Workflow graph.

    START → route_source ─(ocr)────→ ocr → read_pages → assemble → check_source ─┬→ memory → analyse → ask → translate → clarify → review ─┬─(refine)→ refine → review
                         └(extract)→ extract → read_pictures → finish_extract ────┘                                                         └─(done)──→ polish → finalize

* `route_source` PDFs, images and text files go to `ocr`; Word, PowerPoint and Excel files to `extract`, which
              reads their text from the file (office/) — no OCR and no source check.
* `read_pages` every page at once, each a small graph of its own (agents/steps/page.py): picture candidates
              (each read by the picture graph, agents/steps/picture.py), then two vision models read the page side
              by side and the OCR check model settles where they differ — or, with one reading, checks it. A page
              that is hard to read is marked, nothing changed. Each page's result is cached, so a retry doesn't
              read it again. `ocr` lists the pages; `assemble` turns the results into segments. Text files are
              read as they are.
* `read_pictures` the text in the pictures of a Word, PowerPoint or Excel file, each by the picture graph
              (`extract` reads the file's own text; `finish_extract` puts the pictures' text in).
* `check_source` human-in-the-loop: PDFs and images pause so the person can compare the reading with the
              page images and have the chat fix it (`document/source_check.py`) before anything is translated.
* `memory`    the project's translation memory first: 100/101% matches fill their segments (no model call),
              fuzzy matches become references for the translator (`document/memory.py`).
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
from .steps.extract import extract, finish_extract, read_pictures, route_source
from .steps.finish import finalize, polish
from .steps.memory import memory
from .steps.read import assemble, check_source, ocr, read_pages
from .steps.review import refine, review
from .steps.translate import clarify, translate

PIPELINE_NAME = "ingest"


ingest_workflow = Workflow(
    name=PIPELINE_NAME,
    edges=[
        (START, route_source),
        (route_source, {"ocr": ocr, "extract": extract}),
        (ocr, read_pages, assemble, check_source, memory, analyse, ask, translate, clarify, review),
        (extract, read_pictures, finish_extract, memory),
        (review, {"refine": refine, "done": polish}),
        (refine, review),
        (polish, finalize),
    ],
)

"""A fake vision OCR for pipeline tests: the page markdown a test writes is what the OCR agents "read"."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from types import SimpleNamespace

from google.adk.models import LlmResponse
from google.genai import types


def _reply(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _prompt(llm_request) -> str:
    return "\n".join(p.text or "" for c in llm_request.contents for p in c.parts or [] if p.text)


def fake_ocr(monkeypatch, read: str | Callable | Iterator, legends: dict[int, str | tuple[str, str]] | None = None,
             second: str | Callable | None = None, second_legends: dict[int, str | tuple[str, str]] | None = None,
             arbiter: Callable[[str], str] | None = None) -> list[str]:
    """Replace the OCR agents. `read`: the page markdown (every page), a function of the page (`page.number`), or
    an iterator of pages. `legends[n]`: what the n-th picture candidate looked at (in order) holds — its text (a
    picture), or ("text", "…") for a region that is plain text, not a picture.

    The second reading (`ocr_second`) reads what the first does, unless `second` (like `read`) or `second_legends`
    say otherwise. `arbiter`: the OCR check model settling where they differ — the prompt → its reply ("1: …");
    without one, a test where the readings differ fails. Returns the prompts."""
    from translator.agents import workers

    prompts: list[str] = []
    first_reads: dict[int, str] = {}

    def looker(table, counter):
        def look(callback_context, llm_request):  # the figure check: picture or text, and the text inside
            prompts.append(_prompt(llm_request))
            found = (table or {}).get(next(counter), "<none/>")
            kind, text = found if isinstance(found, tuple) else ("picture", found)
            return _reply(f"<kind>{kind}</kind>\n<text>\n{text}\n</text>")
        return look

    def page_of(text: str) -> int:
        return int(re.search(r"Transcribe page (\d+)", text).group(1))

    def first(callback_context, llm_request):
        text = _prompt(llm_request)
        prompts.append(text)
        number = page_of(text)
        if isinstance(read, Iterator):
            out = next(read)
        else:
            out = read(SimpleNamespace(number=number)) if callable(read) else read
        first_reads[number] = out
        return _reply(out)

    def second_reader(callback_context, llm_request):
        text = _prompt(llm_request)
        prompts.append(text)
        number = page_of(text)
        if second is None:
            if number not in first_reads and not isinstance(read, Iterator):
                first_reads[number] = read(SimpleNamespace(number=number)) if callable(read) else read
            return _reply(first_reads.get(number, ""))
        return _reply(second(SimpleNamespace(number=number)) if callable(second) else second)

    def settle(callback_context, llm_request):
        text = _prompt(llm_request)
        prompts.append(text)
        if arbiter is None:
            raise AssertionError("the two readings differ, but the test gave no arbiter:\n" + text[-600:])
        return _reply(arbiter(text))

    monkeypatch.setattr(workers.ocr_reader, "before_model_callback", first)
    monkeypatch.setattr(workers.ocr_second_reader, "before_model_callback", second_reader)
    monkeypatch.setattr(workers.ocr_arbiter, "before_model_callback", settle)
    monkeypatch.setattr(workers.figure_reader, "before_model_callback", looker(legends, iter(range(1, 1000))))
    monkeypatch.setattr(workers.figure_second_reader, "before_model_callback",
                        looker(second_legends if second_legends is not None else legends, iter(range(1, 1000))))
    return prompts

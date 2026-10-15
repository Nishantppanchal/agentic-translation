"""A fake vision OCR for pipeline tests: the page markdown a test writes is what the OCR agent "reads"."""

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


def fake_ocr(monkeypatch, read: str | Callable | Iterator, legends: dict[int, str | tuple[str, str]] | None = None) -> list[str]:
    """Replace the OCR agents. `read`: the page markdown (every page), a function of the page (`page.number`), or
    an iterator of pages. `legends[n]`: what the n-th picture candidate looked at (in order) holds — its text (a
    picture), or ("text", "…") for a region that is plain text, not a picture. Returns the prompts."""
    from translator.agents import workers

    prompts: list[str] = []
    pictures = iter(range(1, 1000))

    def look(callback_context, llm_request):  # the figure check: picture or text, and the text inside
        prompts.append(_prompt(llm_request))
        found = (legends or {}).get(next(pictures), "<none/>")
        kind, text = found if isinstance(found, tuple) else ("picture", found)
        return _reply(f"<kind>{kind}</kind>\n<text>\n{text}\n</text>")

    def callback(callback_context, llm_request):
        text = _prompt(llm_request)
        prompts.append(text)
        number = int(re.search(r"Transcribe page (\d+)", text).group(1))
        if isinstance(read, Iterator):
            return _reply(next(read))
        return _reply(read(SimpleNamespace(number=number)) if callable(read) else read)

    monkeypatch.setattr(workers.ocr_reader, "before_model_callback", callback)
    monkeypatch.setattr(workers.figure_reader, "before_model_callback", look)
    return prompts

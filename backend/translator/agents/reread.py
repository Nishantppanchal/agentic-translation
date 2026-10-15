"""Reading a page again with an instruction: the OCR model (a vision model) transcribes the whole page anew, given
what was read before and what to do differently. Used by the chat editor (`reread_page`) and by the source check
("this is text, not a picture")."""

from __future__ import annotations

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from ..models import llm, routing
from ..models.replies import clean
from . import prompts


async def read_page_again(page_image: types.Part, page_number: int, instruction: str, previous: str,
                          extra: list[types.Part] | None = None, state=None) -> str:
    """The page's new markdown, read by the document's OCR model (`state`). `extra`: more images for the model
    (e.g. the region the instruction is about). Raises when the model call fails."""
    request = LlmRequest(contents=[types.Content(role="user", parts=[
        page_image,
        *(extra or []),
        types.Part(text=f"Transcribe page {page_number}." + prompts.REREAD_PAGE.format(
            instruction=instruction.strip(), previous=previous)),
    ])])
    request.config.system_instruction = prompts.VISION_OCR
    replies = [r async for r in llm.build_model("ocr", routing.resolve("ocr", state)).generate_content_async(request)]
    # Not the model's thinking: a reasoning model's arrives as thought parts (OpenRouter's `reasoning`, vLLM's
    # reasoning parser) and would otherwise open the page.
    return clean("".join(p.text or "" for r in replies if r.content for p in r.content.parts or [] if not p.thought))

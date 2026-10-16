"""The single-turn LLM agents, each running on its step's model (config/pipeline.yaml)."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models import BaseLlm

from ..models import routing, structured
from ..models.config import Step
from ..models.llm import build_model
from . import prompts


class StepAgent(LlmAgent):
    """An agent whose model is chosen per document: ADK asks for it on every call, and the document's choice
    (models/routing.py: pipeline.yaml, then Settings, then the document's own) answers. `model` stays
    pipeline.yaml's, for ADK's synchronous paths."""

    step: str = ""

    async def canonical_model_async(self, ctx: ReadonlyContext) -> BaseLlm:
        return routing.llm(self.step, ctx.state)


def worker(name: str, step: Step, instruction: str, structured_output: bool = False) -> StepAgent:
    return StepAgent(
        name=name,
        step=step,
        model=build_model(step),
        instruction=instruction,
        # Adds a per-call JSON schema when the prompt asks for JSON (see models/structured.py).
        before_model_callback=structured.inject_schema if structured_output else None,
    )


# The pipeline. Two vision LLMs read each scanned page and picture independently (`ocr`, `ocr_second`); where they
# differ, the arbiter (the OCR check model) says which is printed. With one reading, the OCR check compares it with
# the image.
FIGURE_READER = ("You look at regions cropped from document pages: you say whether each is a picture or plain text, "
                 "and transcribe the text in it.")
ocr_reader = worker("ocr_reader", "ocr", prompts.VISION_OCR)
ocr_second_reader = worker("ocr_second_reader", "ocr_second", prompts.VISION_OCR)
ocr_checker = worker("ocr_checker", "ocr_check", "You verify OCR transcriptions against page images.")
ocr_arbiter = worker("ocr_arbiter", "ocr_check", "You settle where two readings of a document image disagree.")
figure_reader = worker("figure_reader", "ocr", FIGURE_READER)
figure_second_reader = worker("figure_second_reader", "ocr_second", FIGURE_READER)
analyst = worker("analyst", "analyse", "You are a lead translator preparing a document for translation.", structured_output=True)
translator = worker("translator", "translate", "You are a meticulous professional translator.", structured_output=True)
reviewer = worker("reviewer", "review", "You are a strict senior translation reviewer.", structured_output=True)
refiner = worker("refiner", "refine", "You are a professional translator revising your work.", structured_output=True)

# Tasks on a finished document (agents/tasks.py) and the independent quality score (agents/lqa.py).
rewriter = worker("rewriter", "rewrite", "You are a senior translator revising translations on request.", structured_output=True)
consistency_fixer = worker(
    "consistency_fixer", "polish", "You are a senior translator making a translation consistent.", structured_output=True
)
lqa_reviewer = worker(
    "lqa_reviewer", "lqa", "You are an independent language quality assessor using the MQM framework.", structured_output=True
)

ALL = [ocr_reader, ocr_second_reader, ocr_checker, ocr_arbiter, figure_reader, figure_second_reader, analyst, translator,
       reviewer, refiner, rewriter, consistency_fixer, lqa_reviewer]

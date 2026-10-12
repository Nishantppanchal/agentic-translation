"""The single-turn LLM agents, each running on its step's model (config/pipeline.yaml)."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from ..models import structured
from ..models.config import Step, step_model
from ..models.llm import build_model
from . import prompts


def worker(name: str, step: Step, instruction: str, structured_output: bool = False) -> LlmAgent:
    return LlmAgent(
        name=name,
        model=build_model(step),
        instruction=instruction,
        generate_content_config=types.GenerateContentConfig(temperature=step_model(step).temperature),
        # Adds a per-call JSON schema when the prompt asks for JSON (see models/structured.py).
        before_model_callback=structured.inject_schema if structured_output else None,
    )


# The pipeline. A vision LLM reads each page; a second look (the OCR check) compares the reading with the image.
ocr_reader = worker("ocr_reader", "ocr", prompts.VISION_OCR)
ocr_checker = worker("ocr_checker", "ocr_check", "You verify OCR transcriptions against page images.")
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

ALL = [ocr_reader, ocr_checker, analyst, translator, reviewer, refiner, rewriter, consistency_fixer, lqa_reviewer]

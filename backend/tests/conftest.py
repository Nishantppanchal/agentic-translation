import os

import pytest

from translator import layout, projects, structured
from translator.agents import pipeline
from translator.agents.editor import editor_agent
from translator.agents.lqa import lqa_reviewer
from translator.agents.ops import consistency_fixer, rewriter

WORKERS = [
    pipeline.analyst,
    pipeline.ocr_extractor,
    pipeline.ocr_checker,
    pipeline.figure_detector,
    pipeline.translator,
    pipeline.reviewer,
    pipeline.refiner,
    editor_agent,
    lqa_reviewer,
    rewriter,
    consistency_fixer,
]


@pytest.fixture(autouse=True)
def no_real_models(monkeypatch):
    """Every agent fails loudly unless the test fakes it, and provider keys are removed,
    so a test can never make a real (billed) model call."""
    for key in list(os.environ):
        if key.endswith("_API_KEY"):
            monkeypatch.delenv(key)

    def unexpected(name):
        def callback(*_args, **_kwargs):
            raise AssertionError(f"Unexpected real model call from agent {name!r}: fake it in the test.")

        return callback

    for agent in WORKERS:
        monkeypatch.setattr(agent, "before_model_callback", unexpected(agent.name))


@pytest.fixture(autouse=True)
def isolated_project_store():
    """Projects, termbase and TM live in a fresh in-memory database per test (never data/projects.db)."""
    projects.set_store(projects.ProjectStore(":memory:"))
    yield
    projects.set_store(None)


@pytest.fixture(autouse=True)
def tag_format_by_default(request, monkeypatch):
    """Fakes reply in the tag format unless a test opts into structured (JSON) output; never probe models."""
    if "structured" not in request.keywords:
        monkeypatch.setattr(structured, "enabled", lambda role: False)


@pytest.fixture(autouse=True)
def analysis_off_by_default(request, monkeypatch):
    """The whole-document analysis is its own model call: tests opt in with the `analysis` marker."""
    from translator.config import get_settings

    monkeypatch.setattr(get_settings(), "analysis_enabled", "analysis" in request.keywords)


@pytest.fixture(autouse=True)
def no_layout_server(request, monkeypatch):
    """Unit tests never spawn the PP-DocLayout server; tests marked `layout` use the real one."""
    if "layout" not in request.keywords:
        monkeypatch.setattr(layout, "available", lambda: False)


def pytest_configure(config):
    config.addinivalue_line("markers", "layout: needs the real PP-DocLayout MCP server (set RUN_LAYOUT_TESTS=1)")
    config.addinivalue_line("markers", "structured: run with JSON-schema output enabled")
    config.addinivalue_line("markers", "analysis: run the whole-document analysis (fake the analyst)")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LAYOUT_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set RUN_LAYOUT_TESTS=1 to run against the real layout server")
    for item in items:
        if "layout" in item.keywords:
            item.add_marker(skip)

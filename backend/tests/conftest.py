import os
import tempfile
import threading
from http.server import ThreadingHTTPServer

import pytest

# Before anything imports the settings: tests use the defaults, never a developer's .env (its endpoints,
# keys and headers stay out of every test). LiteLLM would otherwise load .env itself on import.
os.environ["TRANSLATOR_ENV_FILE"] = ""
os.environ["LITELLM_MODE"] = "PRODUCTION"
# Models: tests/config, where every step's model is a port nothing listens on — never a developer's models.yaml.
os.environ["MODELS_FILE"] = os.path.join(os.path.dirname(__file__), "config", "models.yaml")
os.environ["PIPELINE_FILE"] = os.path.join(os.path.dirname(__file__), "config", "pipeline.yaml")
# Storage: a throwaway folder, so importing the API (its session database) never touches backend/data.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="translator-tests-")

from translator import projects
from translator.agents import workers
from translator.agents.editor import editor_agent  # noqa: E402
from translator.agents.workers import (  # noqa: E402
    consistency_fixer,
    lqa_reviewer,  # noqa: E402
    rewriter,
)
from translator.models import config as model_config  # noqa: E402
from translator.models import structured  # noqa: E402
from translator.models.config import ModelsFile, PipelineFile, build  # noqa: E402
from translator.ocr import layout

from .fake_vllm import FakeVllm  # noqa: E402

WORKERS = [
    workers.analyst,
    workers.ocr_reader,
    workers.ocr_second_reader,
    workers.ocr_checker,
    workers.ocr_arbiter,
    workers.figure_reader,
    workers.figure_second_reader,
    workers.translator,
    workers.reviewer,
    workers.refiner,
    editor_agent,
    lqa_reviewer,
    rewriter,
    consistency_fixer,
]


@pytest.fixture(autouse=True)
def no_real_models(monkeypatch):
    """Every agent fails loudly unless the test fakes it, and provider keys and headers are removed from the
    environment, so a test can never make a real (billed) model call."""
    for key in list(os.environ):
        if key.endswith(("_API_KEY", "_HEADERS")):
            monkeypatch.delenv(key)

    def unexpected(name):
        def callback(*_args, **_kwargs):
            raise AssertionError(f"Unexpected real model call from agent {name!r}: fake it in the test.")

        return callback

    for agent in WORKERS:
        monkeypatch.setattr(agent, "before_model_callback", unexpected(agent.name))


@pytest.fixture(autouse=True)
def source_check_off_by_default(request, monkeypatch):
    """PDFs and images pause for the source check after reading: tests opt in with the `source_check` marker."""
    from translator.document import source_check

    if "source_check" not in request.keywords:
        monkeypatch.setattr(source_check, "needs_check", lambda state: False)


@pytest.fixture(autouse=True)
def second_reading_off_by_default(request, monkeypatch):
    """Scanned pages and pictures get one reading (and the OCR check) unless a test opts into the second reading
    with the `second_reading` marker (then fake_ocr fakes both readers and the arbiter)."""
    from translator.ocr import second

    if "second_reading" not in request.keywords:
        monkeypatch.setattr(second, "enabled", lambda state=None: False)


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
        monkeypatch.setattr(structured, "enabled", lambda step, state=None: False)


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
    config.addinivalue_line("markers", "source_check: pause after reading PDFs and images for the source check")
    config.addinivalue_line("markers", "second_reading: a second model reads scanned pages and pictures too")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LAYOUT_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set RUN_LAYOUT_TESTS=1 to run against the real layout server")
    for item in items:
        if "layout" in item.keywords:
            item.add_marker(skip)


# --------------------------------------------------------------------------- #
# Model servers and model config for tests that check what goes over the wire
# --------------------------------------------------------------------------- #


@pytest.fixture
def use_models(monkeypatch):
    """Run with these models.yaml / pipeline.yaml contents (as dicts)."""

    def use(models: dict, pipeline: dict | None = None):
        cfg = build(ModelsFile.model_validate(models),
                    PipelineFile.model_validate(pipeline or {"default": models["models"][0]["id"]}))
        monkeypatch.setattr(model_config, "current", lambda: cfg)
        return cfg

    return use


@pytest.fixture
def fake_vllm():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVllm)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeVllm.requests, FakeVllm.reasoning_parser, FakeVllm.fail_with, FakeVllm.refuse_effort = [], True, None, False
    FakeVllm.content = '{"ok": true}'
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()
    server.server_close()

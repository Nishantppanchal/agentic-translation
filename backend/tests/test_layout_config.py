"""What the backend tells the layout server: the model and where its files are."""

from pathlib import Path

from translator.config import get_settings
from translator.ocr import layout


def test_the_model_folder_is_passed_to_the_layout_server_as_an_absolute_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(get_settings(), "layout_model", "PP-DocLayoutV3")
    monkeypatch.setattr(get_settings(), "layout_model_dir", "models/paddle")
    env = layout.server_env()
    assert env["LAYOUT_MODEL"] == "PP-DocLayoutV3"
    assert env["LAYOUT_MODEL_DIR"] == str((tmp_path / "models/paddle").resolve())
    assert Path(env["LAYOUT_MODEL_DIR"]).is_absolute()


def test_without_a_model_folder_paddlex_uses_its_own_cache(monkeypatch):
    monkeypatch.setenv("LAYOUT_MODEL_DIR", "/stale/value")  # e.g. exported from .env: the setting decides
    monkeypatch.setattr(get_settings(), "layout_model_dir", "")
    assert "LAYOUT_MODEL_DIR" not in layout.server_env()


def test_a_layout_server_timeout_says_so():
    import pytest

    with pytest.raises(RuntimeError, match=r"timed out \(the call took longer than LAYOUT_TIMEOUT = 300 s\)"):
        layout._parse({"error": "MCP tool execution failed: Request 'tools/call' timed out"})

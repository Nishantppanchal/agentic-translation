"""Page layout through the layout MCP server (PP-DocLayoutV3): the pictures on a page, and the regions the
chat editor inspects.

The server (../layout-server) runs in its own environment and is spawned over
stdio by ADK's `McpToolset` on first use. The same toolset can be handed to any
LlmAgent (`tools=[layout_toolset()]`); the pipeline calls the tools directly, so
reading a page stays deterministic.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters

from ..config import get_settings

log = logging.getLogger(__name__)

TOOL = "detect_layout"

_toolset: McpToolset | None = None
_tools: dict[str, object] = {}
_failed = False  # don't retry a server that failed to start on every page


def _server_dir() -> Path | None:
    raw = get_settings().layout_server_dir
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    return path if (path / "server.py").exists() else None


def available() -> bool:
    return not _failed and _server_dir() is not None and shutil.which("uv") is not None


def server_env() -> dict[str, str]:
    """The layout server's environment: which model, and where its files are (absolute, wherever it runs)."""
    settings = get_settings()
    env = {**os.environ, "LAYOUT_MODEL": settings.layout_model}
    env.pop("LAYOUT_MODEL_DIR", None)
    if settings.layout_model_dir:
        env["LAYOUT_MODEL_DIR"] = str(Path(settings.layout_model_dir).expanduser().resolve())
    return env


def layout_toolset() -> McpToolset | None:
    """The PP-DocLayout MCP toolset (exposes `detect_layout`), or None if not configured."""
    global _toolset
    if _toolset is None and available():
        server = _server_dir()
        settings = get_settings()
        _toolset = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="uv",
                    args=["run", "--quiet", "--project", str(server), "python", str(server / "server.py")],
                    env=server_env(),
                ),
                # For stdio this is also the per-call timeout: allow the first model load/download.
                timeout=settings.layout_timeout,
            ),
            tool_filter=[TOOL],
        )
    return _toolset


def _parse(result: Any) -> dict:
    if not isinstance(result, dict):
        raise RuntimeError(f"Unexpected layout result: {type(result).__name__}")
    if isinstance(result.get("error"), str):  # ADK's MCP tool reports a failed call (e.g. a timeout) this way
        hint = ""
        if "timed out" in result["error"]:
            hint = f" (the call took longer than LAYOUT_TIMEOUT = {get_settings().layout_timeout:g} s)"
        raise RuntimeError(f"Layout server: {result['error']}{hint}")
    if result.get("isError") or result.get("is_error"):
        texts = [c.get("text", "") for c in result.get("content") or []]
        raise RuntimeError("Layout server error: " + " ".join(texts)[:1500])
    structured = result.get("structuredContent") or result.get("structured_content")
    if isinstance(structured, dict):
        return structured.get("result", structured) if "regions" not in structured else structured
    for item in result.get("content") or []:
        if item.get("type") == "text":
            return json.loads(item["text"])
    raise RuntimeError("Layout server returned no content")


async def _call(name: str, args: dict, tool_context=None) -> dict | None:
    """Call a layout-server tool → its result, or None if the server is unavailable or the call failed."""
    global _failed
    toolset = layout_toolset()
    if toolset is None:
        return None
    try:
        if name not in _tools:
            _tools.update({t.name: t for t in await toolset.get_tools()})
        if name not in _tools:
            log.warning("Layout server does not expose %s.", name)
            _failed = True
            return None
        return _parse(await _tools[name].run_async(args=args, tool_context=tool_context))
    except Exception:
        log.exception("Layout server call %s failed; falling back.", name)
    return None


def thresholds() -> dict[str, float]:
    """Minimum confidence per layout class ("default" for the rest)."""
    s = get_settings()
    return {"default": s.layout_threshold, **s.layout_thresholds}


async def detect_layout(png: bytes, tool_context=None) -> dict | None:
    """Run PP-DocLayout on a page image. Returns {width, height, regions: [{label, score, box}]} or None if
    unavailable/failed. Which regions are pictures is decided in ocr/figures.py."""
    args = {"image_base64": base64.b64encode(png).decode(), "threshold": thresholds()}
    return await _call(TOOL, args, tool_context)


async def close() -> None:
    global _toolset
    if _toolset is not None:
        await _toolset.close()
    _toolset = None
    _tools.clear()

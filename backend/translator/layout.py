"""Layout detection through the PP-DocLayout MCP server.

The server (../layout-server) runs in its own environment and is spawned over
stdio by ADK's `McpToolset` on first use. The same toolset can be handed to any
LlmAgent (`tools=[layout_toolset()]`); the pipeline calls the tool directly, so
figure detection stays deterministic.
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

from .config import get_settings

log = logging.getLogger(__name__)

TOOL = "detect_layout"
OCR_TOOL = "ocr_lines"
FIGURE_LABELS = {"image", "chart", "seal"}

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
                    env={**os.environ, "LAYOUT_MODEL": settings.layout_model},
                ),
                # For stdio this is also the per-call timeout: allow the first model load/download.
                timeout=settings.layout_timeout,
            ),
            tool_filter=[TOOL, OCR_TOOL],
        )
    return _toolset


def _parse(result: Any) -> dict:
    if not isinstance(result, dict):
        raise RuntimeError(f"Unexpected layout result: {type(result).__name__}")
    if result.get("isError") or result.get("is_error"):
        texts = [c.get("text", "") for c in result.get("content") or []]
        raise RuntimeError("Layout server error: " + " ".join(texts)[:300])
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
            if name == TOOL:
                _failed = True
            return None
        return _parse(await _tools[name].run_async(args=args, tool_context=tool_context))
    except Exception:
        log.exception("Layout server call %s failed; falling back.", name)
    return None


async def detect_layout(png: bytes, tool_context=None) -> dict | None:
    """Run PP-DocLayout on a page image. Returns {width, height, regions} or None if unavailable/failed."""
    args = {"image_base64": base64.b64encode(png).decode(), "threshold": get_settings().layout_threshold}
    return await _call(TOOL, args, tool_context)


async def ocr_lines(png: bytes, script: str = "latin", tool_context=None) -> dict | None:
    """Text lines on a page image (PP-OCRv5): {width, height, lines: [{box, text, score, words}]}, or None."""
    result = await _call(OCR_TOOL, {"image_base64": base64.b64encode(png).decode(), "script": script}, tool_context)
    return result if result and "lines" in result else None


async def figure_boxes(png: bytes, tool_context) -> list[tuple[float, float, float, float]] | None:
    """Pixel boxes of figure-like regions (image/chart/seal), or None when layout detection is unavailable."""
    layout = await detect_layout(png, tool_context)
    if layout is None:
        return None
    return [tuple(r["box"]) for r in layout["regions"] if r["label"] in FIGURE_LABELS]


async def close() -> None:
    global _toolset
    if _toolset is not None:
        await _toolset.close()
    _toolset = None
    _tools.clear()

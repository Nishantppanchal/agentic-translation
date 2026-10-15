"""PP-DocLayoutV3 layout detection, exposed as an MCP tool.

Runs in its own environment (PaddlePaddle is heavy) and speaks MCP over stdio,
so the translator backend spawns it on demand and any MCP client (ADK agents,
Claude Code, ...) can use the same tool.

    uv run --project layout-server python layout-server/server.py

Tool:
  detect_layout  regions (text, title, table, image, chart, seal, header, footer…): the translator weighs the
                 pictures, charts and seals against the text regions to find the figures, and the chat editor
                 inspects pages with it

Env:
  LAYOUT_MODEL      default PP-DocLayoutV3
  LAYOUT_MODEL_DIR  where the model files are: a folder of model folders by name, like PaddleX's
                    ~/.paddlex/official_models (PP-DocLayoutV3/, …), or the model's own folder. Blank, or a
                    model it doesn't hold: PaddleX downloads it to its cache.
"""

from __future__ import annotations

import base64
import os
import sys
import threading
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import cv2  # noqa: E402  (installed with paddlex)
import numpy as np  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402  (MCP SDK 2.x; was FastMCP in 1.x)
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402  (its message reaches the client; others don't)

MODEL_NAME = os.environ.get("LAYOUT_MODEL", "PP-DocLayoutV3")
MODEL_DIR = os.environ.get("LAYOUT_MODEL_DIR", "")

mcp = MCPServer("layout")
_model = None
_lock = threading.Lock()  # one Paddle predictor, used from the server's worker threads


def _local(name: str) -> str | None:
    """The model's folder under LAYOUT_MODEL_DIR, or None (PaddleX then downloads it to its cache).
    Logged to stderr, which the backend shows, so it's clear where the model came from."""
    if not MODEL_DIR:
        return None
    root = Path(MODEL_DIR).expanduser()
    if (root / "inference.yml").exists():  # the model's own folder (PaddleX checks it is LAYOUT_MODEL)
        folder = root
    else:
        folder = root / name if (root / name / "inference.yml").exists() else None
    if folder is None:
        print(f"layout server: {name} is not in LAYOUT_MODEL_DIR ({root}); PaddleX will download it", file=sys.stderr)
        return None
    print(f"layout server: loading {name} from {folder}", file=sys.stderr)
    return str(folder)


def _get_model():
    global _model
    if _model is None:
        from paddleocr import LayoutDetection

        _model = LayoutDetection(model_name=MODEL_NAME, model_dir=_local(MODEL_NAME))
    return _model


def _threshold(threshold: float | dict[str, float]) -> float | dict[int, float]:
    """PaddleX wants a float, or {class id: float} with every class (a missing one falls back to 0.5)."""
    if not isinstance(threshold, dict):
        return float(threshold)
    labels = _get_model().paddlex_predictor.config["label_list"]
    default = float(threshold.get("default", 0.5))
    return {i: float(threshold.get(label, default)) for i, label in enumerate(labels)}


@mcp.tool()
def detect_layout(image_base64: str, threshold: float | dict[str, float] = 0.5) -> dict:
    """Detect the layout of a document page image with PP-DocLayout.

    Finds regions such as doc_title, paragraph_title, text, table, image, chart, seal,
    display_formula, header, footer, number (page number) and figure_title (caption).

    Args:
      image_base64: The page image (PNG or JPEG), base64-encoded.
      threshold: Minimum confidence (0-1) for a region to be returned: one number, or per class
        ({"image": 0.55, "default": 0.3}).

    Returns:
      {"model", "width", "height", "regions": [{"label", "score", "box": [x0, y0, x1, y1]}]},
      boxes in pixels of the given image, sorted top-to-bottom.
    """
    data = np.frombuffer(base64.b64decode(image_base64), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ToolError("Could not decode the image.")
    with _lock:
        results = list(_get_model().predict(image, batch_size=1, layout_nms=True, threshold=_threshold(threshold)))
    boxes = results[0].json["res"]["boxes"] if results else []
    regions = [
        {"label": b["label"], "score": round(float(b["score"]), 3), "box": [round(float(c), 1) for c in b["coordinate"]]}
        for b in boxes
    ]
    regions.sort(key=lambda r: (r["box"][1], r["box"][0]))
    return {"model": MODEL_NAME, "width": int(image.shape[1]), "height": int(image.shape[0]), "regions": regions}


if __name__ == "__main__":
    mcp.run()  # stdio

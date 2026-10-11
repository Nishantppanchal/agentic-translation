"""PP-DocLayout layout detection and PP-OCRv5 text lines, exposed as MCP tools.

Runs in its own environment (PaddlePaddle is heavy) and speaks MCP over stdio,
so the translator backend spawns it on demand and any MCP client (ADK agents,
Claude Code, ...) can use the same tool.

    uv run --project layout-server python layout-server/server.py

Tools:
  detect_layout  regions (text, title, table, image, chart, seal, header, footer…)
  ocr_lines      text lines with their recognised text and word boxes — lets the translator put a
                 translation back onto a scanned page (no text layer to read positions from)

Env: LAYOUT_MODEL (default PP-DocLayout_plus-L; also PP-DocLayoutV3, PP-DocLayout-L/M/S).
"""

from __future__ import annotations

import base64
import os
import threading

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import cv2  # noqa: E402  (installed with paddlex)
import numpy as np  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402  (MCP SDK 2.x; was FastMCP in 1.x)

MODEL_NAME = os.environ.get("LAYOUT_MODEL", "PP-DocLayout_plus-L")

mcp = MCPServer("layout")
_model = None
_lock = threading.Lock()  # one Paddle predictor, used from the server's worker threads


# PP-OCRv5 recognition models by script (the detection model is shared).
OCR_DET = "PP-OCRv5_mobile_det"
OCR_REC = {
    "latin": "latin_PP-OCRv5_mobile_rec",  # German, French, Spanish, … (accents and umlauts)
    "cjk": "PP-OCRv5_mobile_rec",  # Chinese, Japanese, plus English
    "korean": "korean_PP-OCRv5_mobile_rec",
    "cyrillic": "cyrillic_PP-OCRv5_mobile_rec",
}
_ocr: dict[str, object] = {}


def _get_ocr(script: str):
    if script not in OCR_REC:
        raise ValueError(f"Unknown script {script!r}; use one of {', '.join(OCR_REC)}.")
    if script not in _ocr:
        from paddleocr import PaddleOCR

        _ocr[script] = PaddleOCR(
            use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
            text_detection_model_name=OCR_DET, text_recognition_model_name=OCR_REC[script], return_word_box=True,
        )
    return _ocr[script]


def _get_model():
    global _model
    if _model is None:
        from paddleocr import LayoutDetection

        _model = LayoutDetection(model_name=MODEL_NAME)
    return _model


@mcp.tool()
def detect_layout(image_base64: str, threshold: float = 0.5) -> dict:
    """Detect the layout of a document page image with PP-DocLayout.

    Finds regions such as doc_title, paragraph_title, text, table, image, chart, seal,
    formula, header, footer, number (page number) and figure_title (caption).

    Args:
      image_base64: The page image (PNG or JPEG), base64-encoded.
      threshold: Minimum confidence (0-1) for a region to be returned.

    Returns:
      {"model", "width", "height", "regions": [{"label", "score", "box": [x0, y0, x1, y1]}]},
      boxes in pixels of the given image, sorted top-to-bottom.
    """
    data = np.frombuffer(base64.b64decode(image_base64), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode the image.")
    with _lock:
        results = list(_get_model().predict(image, batch_size=1, layout_nms=True, threshold=threshold))
    boxes = results[0].json["res"]["boxes"] if results else []
    regions = [
        {"label": b["label"], "score": round(float(b["score"]), 3), "box": [round(float(c), 1) for c in b["coordinate"]]}
        for b in boxes
    ]
    regions.sort(key=lambda r: (r["box"][1], r["box"][0]))
    return {"model": MODEL_NAME, "width": int(image.shape[1]), "height": int(image.shape[0]), "regions": regions}


@mcp.tool()
def ocr_lines(image_base64: str, script: str = "latin") -> dict:
    """Find the text lines on a page image with PP-OCRv5: position, recognised text and word boxes.

    Args:
      image_base64: The page image (PNG or JPEG), base64-encoded.
      script: Recognition model: latin (default), cjk (Chinese/Japanese), korean or cyrillic.

    Returns:
      {"width", "height", "lines": [{"box": [x0, y0, x1, y1], "text", "score", "words": [{"box", "text"}]}]},
      boxes in pixels of the given image, in reading order (top to bottom, then left to right).
    """
    data = np.frombuffer(base64.b64decode(image_base64), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode the image.")
    with _lock:
        results = list(_get_ocr(script).predict(image))
    res = results[0].json["res"] if results else {}
    lines = []
    for i, (box, text, score) in enumerate(zip(res.get("rec_boxes", []), res.get("rec_texts", []), res.get("rec_scores", []))):
        if not text.strip():
            continue
        words = [
            {"box": [round(float(c), 1) for c in wb], "text": wt}
            for wb, wt in zip((res.get("text_word_boxes") or [[]] * (i + 1))[i], (res.get("text_word") or [[]] * (i + 1))[i])
            if wt.strip()
        ]
        lines.append({"box": [round(float(c), 1) for c in box], "text": text.strip(), "score": round(float(score), 3), "words": words})
    lines.sort(key=lambda ln: (round(ln["box"][1] / 8), ln["box"][0]))
    return {"width": int(image.shape[1]), "height": int(image.shape[0]), "lines": lines}


if __name__ == "__main__":
    mcp.run()  # stdio

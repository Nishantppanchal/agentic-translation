# Layout server

PP-DocLayout layout detection as an MCP tool (`detect_layout`), kept in its own environment because PaddlePaddle is large.

```bash
uv sync                                  # install
uv run python server.py                  # MCP over stdio (the backend spawns this automatically)
LAYOUT_MODEL=PP-DocLayoutV3 uv run python server.py
```

`detect_layout(image_base64, threshold=0.5)` returns `{model, width, height, regions: [{label, score, box: [x0, y0, x1, y1]}]}`, with boxes in pixels sorted top to bottom.

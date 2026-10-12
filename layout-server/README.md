# Layout server

Layout detection (PP-DocLayoutV3) as an MCP tool, kept in its own environment because PaddlePaddle is large. The backend starts it over stdio and passes it its settings; it finds the pictures on pages.

```bash
uv sync                                  # install (paddleocr 3.7.0 and PaddlePaddle)
uv run python server.py                  # MCP over stdio (the backend spawns this automatically)
```

- `detect_layout(image_base64, threshold=0.5)` → `{model, width, height, regions: [{label, score, box: [x0, y0, x1, y1]}]}`, boxes in pixels sorted top to bottom (`LAYOUT_MODEL`, default PP-DocLayoutV3). The translator uses the pictures, charts and seals as figures, and the chat editor's `inspect_page_layout` tool compares a page's regions with its segments.

Without this server (a blank `LAYOUT_SERVER_DIR` in `backend/.env`), figures come from the PDF's embedded images only.

## Model files

By default PaddleX downloads the model on first use into `~/.paddlex/official_models/`. To use model files you already have (e.g. on a machine without internet access), set `LAYOUT_MODEL_DIR` in `backend/.env`; the backend passes it to this server. It can be either:

- a folder of model folders by name, laid out like `~/.paddlex/official_models`:
  ```
  /models/paddle/
    PP-DocLayoutV3/               # detect_layout (LAYOUT_MODEL)
  ```
- or the model's own folder (`inference.yml`, `inference.json`, `inference.pdiparams`).

Each folder must hold the model its name says (PaddleX checks the name in `inference.yml`). The server prints where the model comes from on stderr, which shows up in the backend's log: `layout server: loading PP-DocLayoutV3 from /models/paddle/PP-DocLayoutV3`, or `… is not in LAYOUT_MODEL_DIR (…); PaddleX will download it`.

Run it by hand with the same variables: `LAYOUT_MODEL_DIR=/models/paddle uv run python server.py`.

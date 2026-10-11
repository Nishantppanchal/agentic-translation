"""Helpers for file downloads."""

from __future__ import annotations

import re
from urllib.parse import quote


def content_disposition(filename: str) -> str:
    """`attachment` header that works for non-ASCII names (e.g. 验收报告.md).

    HTTP headers are latin-1, so the real name goes in RFC 5987 `filename*` (UTF-8,
    percent-encoded) with an ASCII-only `filename` fallback for old clients.
    """
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_.") or "download"
    if "." in filename and "." not in fallback:
        fallback += "." + filename.rsplit(".", 1)[1]
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"

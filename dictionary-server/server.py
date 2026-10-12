"""A dummy dictionary service: the HTTP contract the translator calls (DICTIONARY_URL), backed by a small word
list of the terms in the samples. Replace it with any dictionary that answers the same contract — your own
service, or an adapter in front of IATE, Wiktionary, a commercial API… (see README.md).

    python3 dictionary-server/server.py                 # http://localhost:8200/lookup
    python3 dictionary-server/server.py --port 8300 --key secret   # require "Authorization: Bearer secret"

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TERMS = json.loads((Path(__file__).parent / "terms.json").read_text())  # [{lang, term, translation, definition, domain}]


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s-]", " ", unicodedata.normalize("NFKC", text).casefold()).split())


def _same_word(a: str, b: str) -> bool:
    """One word, allowing inflection: one is a prefix of the other (réception / réceptionnée), 4+ letters."""
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def lookup(term: str, lang: str) -> list[dict]:
    """Entries for a term in a language: exact, then inflected forms (same words, each a prefix of the other).
    CJK terms (no spaces) match exactly or as part of the term."""
    q = norm(term)
    out = []
    for e in TERMS:
        if lang and e["lang"] != lang.split("-")[0]:
            continue
        h = norm(e["term"])
        qw, hw = q.split(), h.split()
        cjk = not re.search(r"[a-zЀ-ӿ]", h)
        if q == h or (cjk and h and h in q) or (len(qw) == len(hw) and all(map(_same_word, qw, hw))):
            out.append({k: e[k] for k in ("term", "translation", "definition", "domain")} | {
                "source": "Dummy dictionary (demo data)", "url": None})
    return out


class Handler(BaseHTTPRequestHandler):
    key: str | None = None

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 — a health check
        self._send(200, {"ok": True, "entries": len(TERMS)})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/lookup":
            return self._send(404, {"error": "POST /lookup"})
        if self.key and self.headers.get("Authorization") != f"Bearer {self.key}":
            return self._send(401, {"error": "missing or wrong API key"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            terms, lang = body["terms"], body.get("source_lang", "")
            assert isinstance(terms, list) and all(isinstance(t, str) for t in terms)
        except (ValueError, KeyError, AssertionError):
            return self._send(400, {"error": 'expected {"terms": ["…"], "source_lang": "fr", "target_lang": "en"}'})
        self._send(200, {"results": {t: lookup(t, lang) for t in terms}})

    def log_message(self, fmt: str, *args) -> None:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--key", help="require this Bearer token")
    args = ap.parse_args()
    Handler.key = args.key
    print(f"dummy dictionary on http://{args.host}:{args.port}/lookup ({len(TERMS)} entries)")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()

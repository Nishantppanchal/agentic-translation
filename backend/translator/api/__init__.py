"""The HTTP API (run it with `uvicorn translator.api:app`)."""

from .main import app

__all__ = ["app"]

"""The FastAPI app: middleware and the routers (routes/), over the shared services (services.py)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..models import config as model_config
from ..models.llm import request_headers
from ..ocr import layout
from .routes import chat, documents, meta, projects, segments, source_check
from .services import editor_runner, ingest_runner, ops_runner, settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await ingest_runner.close()
    await editor_runner.close()
    await ops_runner.close()
    await layout.close()


class ForwardHeaders:
    """Passes the API request headers named in models.yaml `defaults.forward_headers` on to every model call the
    request makes, including those of the runs it starts (a run keeps the headers of the request that started it)."""

    def __init__(self, asgi_app) -> None:
        self.app = asgi_app

    async def __call__(self, scope, receive, send) -> None:
        names = model_config.current().forward_headers
        if scope["type"] != "http" or not names:
            return await self.app(scope, receive, send)
        incoming = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        with request_headers({n: incoming[n.lower()] for n in names if n.lower() in incoming}):
            await self.app(scope, receive, send)


app = FastAPI(title="Agentic Translator", lifespan=lifespan)
app.add_middleware(ForwardHeaders)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(meta.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(segments.router)
app.include_router(source_check.router)
app.include_router(projects.router)

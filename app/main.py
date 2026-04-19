"""
app/main.py  –  FastAPI application factory and entry point.

Startup sequence:
  1. Configure structured logging
  2. Connect to MongoDB, ensure indexes
  3. Warm up the embedding model
  4. Mount all API routers
  5. Expose health check endpoint
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api import api_router
from app.db.mongo import ensure_indexes, get_client
from app.services.logging_service import configure_structlog
from app.services.embedding_service import get_embedding_service

log = structlog.get_logger(__name__)
print(log)
settings = get_settings()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    configure_structlog(settings.log_level)
    log.info("starting_up", model=settings.ollama_model, db=settings.mongo_db)

    # MongoDB
    try:
        await get_client().admin.command("ping")
        log.info("mongodb_connected", uri=settings.mongo_uri)
    except Exception as exc:
        log.error("mongodb_connection_failed", error=str(exc))

    await ensure_indexes()
    log.info("mongodb_indexes_ensured")

    # Warm up embedding model (sentence-transformers downloads on first call)
    if settings.embed_backend == "sentence_transformers":
        try:
            svc = get_embedding_service()
            await svc.embed("warmup")
            log.info("embedding_model_warmed_up", model=settings.embed_st_model)
        except Exception as exc:
            log.warning("embedding_warmup_failed", error=str(exc))

    log.info("application_ready", host=settings.api_host, port=settings.api_port)
    yield

    # Shutdown
    from app.services.ollama_service import get_ollama
    await get_ollama().close()
    get_client().close()
    log.info("application_shutdown")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Retail AI Agent API",
        description=(
            "Multi-agent RAG + MongoDB query system with self-correction, "
            "streaming responses, and long-term memory."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],        # tighten in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request timing middleware ─────────────────────────────────────────────
    @app.middleware("http")
    async def add_process_time(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time-Ms"] = f"{elapsed:.1f}"
        return response

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        log.error("unhandled_exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error": str(exc)},
        )

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["system"])
    async def health():
        try:
            await get_client().admin.command("ping")
            mongo_ok = True
        except Exception:
            mongo_ok = False

        return {
            "status": "ok" if mongo_ok else "degraded",
            "mongodb": "connected" if mongo_ok else "disconnected",
            "model": settings.ollama_model,
            "embed_backend": settings.embed_backend,
        }

    # ── Mount API ─────────────────────────────────────────────────────────────
    app.include_router(api_router)

    return app


# ── Singleton ─────────────────────────────────────────────────────────────────
app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        workers=1,          # single worker: Motor + asyncio don't need multi-process
        log_config=None,    # let structlog handle everything
    )

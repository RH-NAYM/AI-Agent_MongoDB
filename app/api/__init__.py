"""
app/api/__init__.py  –  Aggregates all sub-routers into a single APIRouter.
"""
from fastapi import APIRouter

from app.api.routes.chat import router as chat_router
from app.api.routes.history import router as history_router
from app.api.routes.logs import router as logs_router
from app.api.routes.ingest import router as ingest_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(chat_router)
api_router.include_router(history_router)
api_router.include_router(logs_router)
api_router.include_router(ingest_router)

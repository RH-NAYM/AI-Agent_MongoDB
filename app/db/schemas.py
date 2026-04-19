"""
app/db/schemas.py  –  Pydantic v2 document models for MongoDB collections.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field
from ulid import ULID


def _ulid() -> str:
    return str(ULID())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Embeddings ───────────────────────────────────────────────────────────────
class EmbeddingDoc(BaseModel):
    id: str = Field(default_factory=_ulid, alias="_id")
    text: str
    vector: list[float]
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)

    model_config = {"populate_by_name": True}


# ── Conversation ─────────────────────────────────────────────────────────────
class MessageDoc(BaseModel):
    role: str                     # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = Field(default_factory=_now)


class ConversationDoc(BaseModel):
    id: str = Field(default_factory=_ulid, alias="_id")
    session_id: str
    messages: list[MessageDoc] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    model_config = {"populate_by_name": True}


# ── Log ──────────────────────────────────────────────────────────────────────
class ToolCallLog(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    result_summary: str
    success: bool


class LogDoc(BaseModel):
    id: str = Field(default_factory=_ulid, alias="_id")
    session_id: Optional[str] = None
    user_query: str
    agent_plan: Optional[str] = None
    tool_calls: list[ToolCallLog] = Field(default_factory=list)
    final_response: Optional[str] = None
    execution_time_ms: Optional[float] = None
    error: Optional[str] = None
    retry_count: int = 0
    created_at: datetime = Field(default_factory=_now)

    model_config = {"populate_by_name": True}


# ── Feedback ─────────────────────────────────────────────────────────────────
class FeedbackDoc(BaseModel):
    id: str = Field(default_factory=_ulid, alias="_id")
    session_id: str
    log_id: Optional[str] = None
    rating: int                   # 1-5
    comment: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)

    model_config = {"populate_by_name": True}

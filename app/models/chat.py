"""
app/models/chat.py  –  API request / response schemas.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# ── Chat ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000, description="User message")
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Unique session identifier (client-generated)",
    )
    stream: bool = Field(default=True, description="Whether to stream the response")

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be blank")
        return v.strip()


class ChatResponse(BaseModel):
    session_id: str
    response: str
    intent: Optional[str] = None


# ── History ───────────────────────────────────────────────────────────────────

class MessageOut(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[MessageOut]
    total: int


# ── Logs ─────────────────────────────────────────────────────────────────────

class ToolCallOut(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    result_summary: str
    success: bool


class LogOut(BaseModel):
    id: str
    session_id: Optional[str]
    user_query: str
    agent_plan: Optional[str]
    tool_calls: list[ToolCallOut]
    final_response: Optional[str]
    execution_time_ms: Optional[float]
    error: Optional[str]
    retry_count: int
    created_at: Optional[str]


class LogsResponse(BaseModel):
    logs: list[LogOut]
    total: int
    page: int
    page_size: int


# ── Feedback ──────────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    session_id: str
    log_id: Optional[str] = None
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


class FeedbackResponse(BaseModel):
    success: bool
    message: str


# ── Ingest ───────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    collection: str = Field(..., description="Target collection (e.g. 'main_data')")
    documents: list[dict[str, Any]] = Field(..., min_length=1, max_length=500)
    embed_field: Optional[str] = Field(
        default=None,
        description="Field to embed for RAG; if set, embeddings are generated",
    )


class IngestResponse(BaseModel):
    inserted: int
    embedded: int
    errors: list[str]

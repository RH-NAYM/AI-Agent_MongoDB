"""
app/api/routes/logs.py  –  GET /logs
                            POST /feedback
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query, HTTPException

from app.db.mongo import col_logs, col_feedback
from app.db.schemas import FeedbackDoc
from app.models.chat import LogsResponse, LogOut, ToolCallOut, FeedbackRequest, FeedbackResponse

router = APIRouter(tags=["observability"])


# ── GET /logs ─────────────────────────────────────────────────────────────────

@router.get(
    "/logs",
    response_model=LogsResponse,
    summary="Retrieve agent execution logs (paginated)",
)
async def get_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session_id: str | None = Query(default=None),
    errors_only: bool = Query(default=False, description="Filter to only errored requests"),
):
    skip = (page - 1) * page_size
    mongo_filter: dict = {}
    if session_id:
        mongo_filter["session_id"] = session_id
    if errors_only:
        mongo_filter["error"] = {"$ne": None}

    total = await col_logs().count_documents(mongo_filter)
    cursor = (
        col_logs()
        .find(mongo_filter, {"_id": 1, "session_id": 1, "user_query": 1,
                              "agent_plan": 1, "tool_calls": 1, "final_response": 1,
                              "execution_time_ms": 1, "error": 1, "retry_count": 1,
                              "created_at": 1})
        .sort("created_at", -1)
        .skip(skip)
        .limit(page_size)
    )
    docs = await cursor.to_list(length=page_size)

    logs_out = []
    for d in docs:
        tool_calls = [
            ToolCallOut(
                tool_name=tc.get("tool_name", ""),
                arguments=tc.get("arguments", {}),
                result_summary=tc.get("result_summary", ""),
                success=tc.get("success", False),
            )
            for tc in d.get("tool_calls", [])
        ]
        created = d.get("created_at")
        logs_out.append(
            LogOut(
                id=str(d.get("_id", "")),
                session_id=d.get("session_id"),
                user_query=d.get("user_query", ""),
                agent_plan=d.get("agent_plan"),
                tool_calls=tool_calls,
                final_response=d.get("final_response"),
                execution_time_ms=d.get("execution_time_ms"),
                error=d.get("error"),
                retry_count=d.get("retry_count", 0),
                created_at=created.isoformat() if isinstance(created, datetime) else str(created or ""),
            )
        )

    return LogsResponse(logs=logs_out, total=total, page=page, page_size=page_size)


# ── POST /feedback ────────────────────────────────────────────────────────────

@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    summary="Submit user feedback (RLHF-ready)",
)
async def submit_feedback(body: FeedbackRequest):
    doc = FeedbackDoc(
        session_id=body.session_id,
        log_id=body.log_id,
        rating=body.rating,
        comment=body.comment,
    )
    await col_feedback().insert_one(doc.model_dump(by_alias=True))
    return FeedbackResponse(success=True, message="Feedback recorded. Thank you!")

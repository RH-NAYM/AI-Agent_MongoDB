"""
app/api/routes/history.py  –  GET /history/{session_id}
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.agents.memory_agent import MemoryAgent
from app.models.chat import HistoryResponse, MessageOut

router = APIRouter(prefix="/history", tags=["history"])
_mem: MemoryAgent | None = None


def _get_mem() -> MemoryAgent:
    global _mem
    if _mem is None:
        _mem = MemoryAgent()
    return _mem


@router.get(
    "/{session_id}",
    response_model=HistoryResponse,
    summary="Retrieve conversation history for a session",
)
async def get_history(
    session_id: str,
    last_n: int = Query(default=50, ge=1, le=500, description="Max messages to return"),
):
    mem = _get_mem()
    messages = await mem.get_history(session_id, last_n=last_n)

    if not messages:
        # Not an error – could be a new session
        return HistoryResponse(session_id=session_id, messages=[], total=0)

    out = [
        MessageOut(
            role=m.get("role", ""),
            content=m.get("content", ""),
            timestamp=str(m.get("timestamp", "")),
        )
        for m in messages
    ]
    return HistoryResponse(session_id=session_id, messages=out, total=len(out))

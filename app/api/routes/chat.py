"""
app/api/routes/chat.py  –  POST /chat

Supports:
  - stream=true  → Server-Sent Events (SSE) with token-level streaming
  - stream=false → Full JSON response
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from app.agents.orchestrator import Orchestrator
from app.models.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])

# One orchestrator per event loop (stateless, all state in MongoDB)
_orchestrator: Orchestrator | None = None


def _get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


# ── POST /chat ────────────────────────────────────────────────────────────────

@router.post("", summary="Send a message and receive an AI-generated response")
async def chat(request: ChatRequest):
    orch = _get_orchestrator()

    if request.stream:
        return StreamingResponse(
            _sse_generator(orch, request.query, request.session_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        response_text = await orch.run(request.query, request.session_id)
        return ChatResponse(
            session_id=request.session_id,
            response=response_text,
        )


async def _sse_generator(orch: Orchestrator, query: str, session_id: str):
    """
    Yield Server-Sent Event formatted chunks.

    Format:
        data: <json_chunk>\n\n

    Final event:
        data: [DONE]\n\n
    """
    try:
        async for chunk in orch.stream_tokens(query, session_id):
            payload = json.dumps({"delta": chunk, "session_id": session_id})
            yield f"data: {payload}\n\n"
            await asyncio.sleep(0)   # yield to event loop between chunks
    except Exception as exc:
        error_payload = json.dumps({"error": str(exc), "session_id": session_id})
        yield f"data: {error_payload}\n\n"
    finally:
        yield "data: [DONE]\n\n"

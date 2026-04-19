"""
app/tools/memory_tools.py  –  memory_fetch_tool / memory_store_tool

Manages conversation memory in MongoDB `conversations` collection.

memory_store_tool  – appends a message to the session document
memory_fetch_tool  – retrieves last N messages for a session
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog

from app.config import get_settings
from app.db.mongo import col_conversations
from app.db.schemas import MessageDoc

log = structlog.get_logger(__name__)
settings = get_settings()


# ── Store ────────────────────────────────────────────────────────────────────

async def memory_store_tool(
    session_id: str,
    role: str,
    content: str,
) -> dict:
    """
    Upsert a conversation document and append a new message.

    Parameters
    ----------
    session_id : unique session identifier
    role       : "user" | "assistant" | "system"
    content    : message text

    Returns
    -------
    {"success": bool, "error": str | None}
    """
    try:
        msg = MessageDoc(role=role, content=content)
        now = datetime.now(timezone.utc)

        await col_conversations().update_one(
            {"session_id": session_id},
            {
                "$push": {"messages": msg.model_dump()},
                "$set": {"updated_at": now},
                "$setOnInsert": {
                    "session_id": session_id,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        log.debug("memory_store_tool_success", session_id=session_id, role=role)
        return {"success": True, "error": None}

    except Exception as exc:  # noqa: BLE001
        log.error("memory_store_tool_error", session_id=session_id, error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Fetch ────────────────────────────────────────────────────────────────────

async def memory_fetch_tool(
    session_id: str,
    last_n: Optional[int] = None,
) -> dict:
    """
    Retrieve conversation history for a session.

    Parameters
    ----------
    session_id : session identifier
    last_n     : only return the last N messages (default: settings.memory_window)

    Returns
    -------
    {
      "success": bool,
      "session_id": str,
      "messages": [{"role": ..., "content": ..., "timestamp": ...}, ...],
      "error": str | None
    }
    """
    window = last_n or settings.memory_window
    try:
        doc = await col_conversations().find_one(
            {"session_id": session_id},
            {"messages": {"$slice": -window}, "_id": 0},
        )

        if doc is None:
            return {
                "success": True,
                "session_id": session_id,
                "messages": [],
                "error": None,
            }

        messages = doc.get("messages", [])
        # Convert datetime to ISO string for serialization
        for m in messages:
            if isinstance(m.get("timestamp"), datetime):
                m["timestamp"] = m["timestamp"].isoformat()

        log.debug(
            "memory_fetch_tool_success",
            session_id=session_id,
            message_count=len(messages),
        )
        return {
            "success": True,
            "session_id": session_id,
            "messages": messages,
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        log.error("memory_fetch_tool_error", session_id=session_id, error=str(exc))
        return {"success": False, "session_id": session_id, "messages": [], "error": str(exc)}

"""
app/agents/memory_agent.py  –  Memory Agent

Manages all conversation memory operations:
  - store_message()          → persist user/assistant turns
  - get_history()            → retrieve last N messages
  - get_semantic_context()   → find past messages semantically similar
                               to the current query (useful for long sessions)
"""
from __future__ import annotations

from typing import Optional

import structlog

from app.config import get_settings
from app.tools.memory_tools import memory_store_tool, memory_fetch_tool
from app.services.embedding_service import get_embedding_service, rank_by_similarity
from app.db.mongo import col_conversations
from app.utils.helpers import build_context_from_messages

log = structlog.get_logger(__name__)
settings = get_settings()


class MemoryAgent:
    def __init__(self) -> None:
        self.embed_svc = get_embedding_service()

    async def store_message(self, session_id: str, role: str, content: str) -> None:
        """Persist a single message to the conversation history."""
        result = await memory_store_tool(session_id, role, content)
        if not result["success"]:
            log.warning(
                "memory_store_failed",
                session_id=session_id,
                error=result.get("error"),
            )

    async def get_history(
        self,
        session_id: str,
        last_n: Optional[int] = None,
    ) -> list[dict]:
        """Return the last N messages for a session."""
        result = await memory_fetch_tool(session_id, last_n)
        return result.get("messages", [])

    async def get_ollama_context(
        self,
        session_id: str,
    ) -> list[dict[str, str]]:
        """
        Return conversation history in Ollama message format
        (trimmed to the configured memory window).
        """
        messages = await self.get_history(session_id, last_n=settings.memory_window)
        return build_context_from_messages(messages, settings.memory_window)

    async def get_semantic_context(
        self,
        session_id: str,
        query: str,
        top_k: int = 3,
    ) -> list[dict]:
        """
        Find past messages that are semantically similar to the current query.
        Useful for very long sessions where full history would overflow context.

        Returns a list of message dicts with an added '_score' field.
        """
        # Fetch full history (up to 200 msgs for semantic scan)
        doc = await col_conversations().find_one(
            {"session_id": session_id},
            {"messages": {"$slice": -200}},
        )
        if not doc:
            return []

        messages = doc.get("messages", [])
        if not messages:
            return []

        # Embed each message's content
        try:
            query_vec = await self.embed_svc.embed(query)
            candidates = []
            for m in messages:
                vec = await self.embed_svc.embed(m.get("content", ""))
                candidates.append({**m, "vector": vec})

            ranked = rank_by_similarity(query_vec, candidates, top_k=top_k)
            return ranked

        except Exception as exc:  # noqa: BLE001
            log.warning("semantic_memory_error", error=str(exc))
            return []

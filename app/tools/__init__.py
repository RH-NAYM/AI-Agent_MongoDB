"""
app/tools/__init__.py  –  Tool registry.

The Executor agent calls `execute_tool(name, args)` to dispatch to
the correct tool function without needing to import each one explicitly.
"""
from __future__ import annotations

from typing import Any

from app.tools.mongo_find import mongo_find_tool
from app.tools.mongo_aggregate import mongo_aggregate_tool
from app.tools.vector_search import vector_search_tool
from app.tools.memory_tools import memory_fetch_tool, memory_store_tool

# ── Registry ──────────────────────────────────────────────────────────────────
_TOOLS: dict[str, Any] = {
    "mongo_find_tool": mongo_find_tool,
    "mongo_aggregate_tool": mongo_aggregate_tool,
    "vector_search_tool": vector_search_tool,
    "memory_fetch_tool": memory_fetch_tool,
    "memory_store_tool": memory_store_tool,
}

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "mongo_find_tool",
        "description": (
            "Execute a MongoDB find() query. Use for fetching specific records "
            "with filters. Returns up to 100 documents."
        ),
        "parameters": {
            "collection": "string – e.g. 'main_data'",
            "query_filter": "dict – MongoDB filter document",
            "projection": "dict | null – fields to include/exclude",
            "sort": "list[list] | null – [[field, direction], ...]",
            "limit": "int – max docs (default 20, max 100)",
        },
    },
    {
        "name": "mongo_aggregate_tool",
        "description": (
            "Execute a MongoDB aggregation pipeline. Use for grouping, "
            "summaries, trends, counts, averages."
        ),
        "parameters": {
            "collection": "string",
            "pipeline": "list[dict] – aggregation stages",
        },
    },
    {
        "name": "vector_search_tool",
        "description": (
            "Semantic similarity search over the embeddings collection. "
            "Use for question-answering over unstructured text."
        ),
        "parameters": {
            "query_text": "string – natural language query",
            "metadata_filter": "dict | null – e.g. {'metadata.outlet_id': 'O-42'}",
            "top_k": "int | null – results to return (default 5)",
        },
    },
    {
        "name": "memory_fetch_tool",
        "description": "Retrieve past conversation messages for a session.",
        "parameters": {
            "session_id": "string",
            "last_n": "int | null – last N messages",
        },
    },
    {
        "name": "memory_store_tool",
        "description": "Persist a message to conversation memory.",
        "parameters": {
            "session_id": "string",
            "role": "string – 'user' | 'assistant' | 'system'",
            "content": "string",
        },
    },
]


async def execute_tool(name: str, args: dict[str, Any]) -> Any:
    """Dispatch a tool call by name."""
    fn = _TOOLS.get(name)
    if fn is None:
        return {"success": False, "error": f"Unknown tool: {name!r}"}
    return await fn(**args)

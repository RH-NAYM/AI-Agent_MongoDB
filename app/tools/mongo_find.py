"""
app/tools/mongo_find.py  –  mongo_find_tool

Executes a MongoDB find() query against a specified collection.
Safety-checked before execution.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog

from app.db.mongo import get_db
from app.utils.safety import validate_filter, sanitize_projection, SafetyError

log = structlog.get_logger(__name__)

MAX_LIMIT = 100   # Hard cap to prevent accidental full-collection scans


async def mongo_find_tool(
    collection: str,
    query_filter: dict[str, Any],
    projection: Optional[dict[str, Any]] = None,
    sort: Optional[list[tuple[str, int]]] = None,
    limit: int = 20,
) -> dict[str, Any]:
    """
    Execute a safe MongoDB find query.

    Parameters
    ----------
    collection   : target collection name
    query_filter : MongoDB filter document
    projection   : optional field projection
    sort         : list of (field, direction) tuples e.g. [("date", -1)]
    limit        : maximum documents to return (capped at MAX_LIMIT)

    Returns
    -------
    {
      "success": bool,
      "count": int,
      "documents": [...],
      "error": str | None
    }
    """
    try:
        # ── Safety checks ────────────────────────────────────────────────────
        validate_filter(query_filter)
        clean_proj = sanitize_projection(projection)

        # ── Execute ──────────────────────────────────────────────────────────
        capped_limit = min(abs(limit), MAX_LIMIT)
        db = get_db()
        cursor = db[collection].find(query_filter, clean_proj)

        if sort:
            cursor = cursor.sort(sort)

        cursor = cursor.limit(capped_limit)
        docs = await cursor.to_list(length=capped_limit)

        # Stringify ObjectIds for JSON safety
        clean_docs = _stringify_ids(docs)

        log.info(
            "mongo_find_tool_success",
            collection=collection,
            filter_keys=list(query_filter.keys()),
            result_count=len(clean_docs),
        )

        return {"success": True, "count": len(clean_docs), "documents": clean_docs, "error": None}

    except SafetyError as exc:
        log.warning("mongo_find_tool_safety_violation", error=str(exc))
        return {"success": False, "count": 0, "documents": [], "error": f"SafetyError: {exc}"}

    except Exception as exc:  # noqa: BLE001
        log.error("mongo_find_tool_error", error=str(exc))
        return {"success": False, "count": 0, "documents": [], "error": str(exc)}


def _stringify_ids(docs: list[dict]) -> list[dict]:
    """Convert ObjectId / BSON types to strings for JSON serialization."""
    import json
    from bson import ObjectId
    from datetime import datetime

    def default(o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError

    raw = json.dumps(docs, default=default)
    return json.loads(raw)

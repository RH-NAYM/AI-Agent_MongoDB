"""
app/tools/mongo_aggregate.py  –  mongo_aggregate_tool

Executes an aggregation pipeline against a MongoDB collection.
Pipeline stages are validated against an allowlist before execution.
"""
from __future__ import annotations

from typing import Any

import structlog

from app.db.mongo import get_db
from app.utils.safety import validate_pipeline, SafetyError

log = structlog.get_logger(__name__)

MAX_RESULTS = 500


async def mongo_aggregate_tool(
    collection: str,
    pipeline: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Execute a safe MongoDB aggregation pipeline.

    Parameters
    ----------
    collection : target collection
    pipeline   : list of aggregation stage dicts

    Returns
    -------
    {
      "success": bool,
      "count": int,
      "results": [...],
      "error": str | None
    }
    """
    try:
        # ── Safety ───────────────────────────────────────────────────────────
        validate_pipeline(pipeline)

        # Ensure there's always a hard limit at the end to prevent OOM
        pipeline = _ensure_limit(pipeline, MAX_RESULTS)

        # ── Execute ──────────────────────────────────────────────────────────
        db = get_db()
        cursor = db[collection].aggregate(pipeline)
        results = await cursor.to_list(length=MAX_RESULTS)

        clean = _stringify_ids(results)

        log.info(
            "mongo_aggregate_tool_success",
            collection=collection,
            stages=[list(s.keys())[0] for s in pipeline],
            result_count=len(clean),
        )

        return {"success": True, "count": len(clean), "results": clean, "error": None}

    except SafetyError as exc:
        log.warning("mongo_aggregate_tool_safety_violation", error=str(exc))
        return {"success": False, "count": 0, "results": [], "error": f"SafetyError: {exc}"}

    except Exception as exc:  # noqa: BLE001
        log.error("mongo_aggregate_tool_error", error=str(exc))
        return {"success": False, "count": 0, "results": [], "error": str(exc)}


def _ensure_limit(pipeline: list[dict], max_n: int) -> list[dict]:
    """Append a $limit stage if the pipeline doesn't already have one."""
    stages_with_limit = [s for s in pipeline if "$limit" in s]
    if not stages_with_limit:
        pipeline = list(pipeline) + [{"$limit": max_n}]
    return pipeline


def _stringify_ids(docs: list[dict]) -> list[dict]:
    import json
    from bson import ObjectId
    from datetime import datetime

    def default(o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError

    return json.loads(json.dumps(docs, default=default))

"""
app/tools/vector_search.py  –  vector_search_tool

Hybrid retrieval:
  1. Embed the query text
  2. Apply metadata pre-filter in MongoDB (e.g., outlet_id, region)
  3. Load candidate embedding docs
  4. Rank by cosine similarity in-process
  5. Return top-K with text and metadata

NOTE: When Atlas Vector Search is available, replace the in-process
      ranking with a $vectorSearch aggregation stage.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog

from app.config import get_settings
from app.db.mongo import col_embeddings
from app.services.embedding_service import get_embedding_service, rank_by_similarity

log = structlog.get_logger(__name__)
settings = get_settings()

MAX_CANDIDATE_FETCH = 2000   # docs to load before in-process ranking


async def vector_search_tool(
    query_text: str,
    metadata_filter: Optional[dict[str, Any]] = None,
    top_k: Optional[int] = None,
) -> dict[str, Any]:
    """
    Hybrid vector + metadata search over the `embeddings` collection.

    Parameters
    ----------
    query_text      : the natural-language query to embed
    metadata_filter : optional pre-filter on metadata fields
                      e.g. {"metadata.outlet_id": "O-42"}
    top_k           : number of results to return (default: settings.vector_top_k)

    Returns
    -------
    {
      "success": bool,
      "results": [
          {"text": ..., "metadata": ..., "_score": float},
          ...
      ],
      "error": str | None
    }
    """
    k = top_k or settings.vector_top_k
    try:
        # ── Step 1: Embed query ───────────────────────────────────────────────
        embed_svc = get_embedding_service()
        query_vec = await embed_svc.embed(query_text)

        # ── Step 2: Fetch candidates with metadata pre-filter ─────────────────
        mongo_filter: dict[str, Any] = {}
        if metadata_filter:
            mongo_filter.update(metadata_filter)

        cursor = col_embeddings().find(
            mongo_filter,
            {"text": 1, "vector": 1, "metadata": 1, "_id": 0},
        ).limit(MAX_CANDIDATE_FETCH)

        candidates = await cursor.to_list(length=MAX_CANDIDATE_FETCH)

        if not candidates:
            log.info("vector_search_no_candidates", filter=metadata_filter)
            return {"success": True, "results": [], "error": None}

        # ── Step 3: In-process cosine ranking ─────────────────────────────────
        ranked = rank_by_similarity(query_vec, candidates, top_k=k)

        # Strip raw vectors from output (large, not needed downstream)
        results = [
            {"text": r.get("text", ""), "metadata": r.get("metadata", {}), "_score": r["_score"]}
            for r in ranked
        ]

        log.info(
            "vector_search_tool_success",
            query=query_text[:80],
            candidates=len(candidates),
            returned=len(results),
        )

        return {"success": True, "results": results, "error": None}

    except Exception as exc:  # noqa: BLE001
        log.error("vector_search_tool_error", error=str(exc))
        return {"success": False, "results": [], "error": str(exc)}

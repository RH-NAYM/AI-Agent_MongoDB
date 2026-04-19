"""
app/api/routes/ingest.py  –  POST /ingest

Allows batch insertion of documents into any allowed collection.
If embed_field is set, generates embeddings and stores them in the
`embeddings` collection for RAG retrieval.

Safety: only 'main_data' is allowed as target collection for ingest.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException

from app.db.mongo import col_embeddings, get_db
from app.db.schemas import EmbeddingDoc
from app.models.chat import IngestRequest, IngestResponse
from app.services.embedding_service import get_embedding_service

log = structlog.get_logger(__name__)
router = APIRouter(tags=["ingest"])

ALLOWED_INGEST_COLLECTIONS = {"main_data"}


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Bulk-insert documents and optionally generate embeddings",
)
async def ingest_documents(body: IngestRequest):
    if body.collection not in ALLOWED_INGEST_COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Collection '{body.collection}' is not allowed for ingest. "
                   f"Allowed: {ALLOWED_INGEST_COLLECTIONS}",
        )

    errors: list[str] = []
    inserted = 0
    embedded = 0

    # ── Insert into target collection ─────────────────────────────────────────
    try:
        db = get_db()
        result = await db[body.collection].insert_many(body.documents, ordered=False)
        inserted = len(result.inserted_ids)
        log.info("ingest_inserted", collection=body.collection, count=inserted)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Insert error: {exc}")
        log.error("ingest_insert_error", error=str(exc))

    # ── Generate embeddings ───────────────────────────────────────────────────
    if body.embed_field and inserted > 0:
        embed_svc = get_embedding_service()
        embed_tasks = []

        for doc in body.documents:
            text = str(doc.get(body.embed_field, "")).strip()
            if text:
                embed_tasks.append(_embed_and_store(embed_svc, text, doc))

        results = await asyncio.gather(*embed_tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                errors.append(f"Embed error: {r}")
            else:
                embedded += 1

    return IngestResponse(inserted=inserted, embedded=embedded, errors=errors)


async def _embed_and_store(embed_svc, text: str, source_doc: dict) -> None:
    """Generate embedding and store in the embeddings collection."""
    vector = await embed_svc.embed(text)
    # Build metadata from safe fields
    metadata: dict[str, Any] = {
        k: source_doc.get(k)
        for k in ("outlet_id", "region", "category", "date", "source_collection")
        if source_doc.get(k) is not None
    }
    metadata.setdefault("source_collection", "main_data")

    emb_doc = EmbeddingDoc(text=text, vector=vector, metadata=metadata)
    await col_embeddings().insert_one(emb_doc.model_dump(by_alias=True))

"""
app/services/embedding_service.py  –  Pluggable embedding backend.

Backends
--------
"ollama"               – calls Ollama /api/embeddings
"sentence_transformers" – runs SentenceTransformer locally (CPU-safe)

Cosine similarity helper is included for in-process vector search
(used when MongoDB Atlas vector search is unavailable).
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Sequence

import numpy as np
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()


# ── Cosine similarity ─────────────────────────────────────────────────────────
def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def rank_by_similarity(
    query_vec: list[float],
    candidates: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """
    candidates: list of dicts, each must have a 'vector' key.
    Returns top_k items sorted by cosine similarity descending,
    each augmented with '_score'.
    """
    scored = []
    for doc in candidates:
        vec = doc.get("vector", [])
        if vec:
            score = cosine_similarity(query_vec, vec)
            scored.append({**doc, "_score": score})
    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored[:top_k]


# ── Sentence-Transformers backend ─────────────────────────────────────────────
@lru_cache(maxsize=1)
def _load_st_model():
    from sentence_transformers import SentenceTransformer  # type: ignore
    log.info("loading_sentence_transformer_model", model=settings.embed_st_model)
    return SentenceTransformer(settings.embed_st_model)


def _st_embed_sync(text: str) -> list[float]:
    model = _load_st_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


async def _st_embed(text: str) -> list[float]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _st_embed_sync, text)


# ── Public interface ──────────────────────────────────────────────────────────
class EmbeddingService:
    def __init__(self) -> None:
        self.backend = settings.embed_backend.lower()
        log.info("embedding_backend_selected", backend=self.backend)

    async def embed(self, text: str) -> list[float]:
        """Return embedding vector for a single text."""
        if self.backend == "ollama":
            from app.services.ollama_service import get_ollama
            return await get_ollama().embed(text)
        else:
            return await _st_embed(text)

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a list of texts concurrently."""
        tasks = [self.embed(t) for t in texts]
        return await asyncio.gather(*tasks)


_embed_svc: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embed_svc
    if _embed_svc is None:
        _embed_svc = EmbeddingService()
    return _embed_svc

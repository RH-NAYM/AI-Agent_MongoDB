"""
app/db/mongo.py  –  Async Motor client with typed collection helpers.

Collections
-----------
main_data       – retail records (products, sales, outlets …)
embeddings      – text chunks + vector + metadata
conversations   – session memory
logs            – observability records
feedback        – RLHF-ready user ratings
"""
from __future__ import annotations

import motor.motor_asyncio as motor
from pymongo import IndexModel, ASCENDING, TEXT
from app.config import get_settings

settings = get_settings()

# ── Singleton client ────────────────────────────────────────────────────────
_client: motor.AsyncIOMotorClient | None = None


def get_client() -> motor.AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = motor.AsyncIOMotorClient(
            settings.mongo_uri,
            maxPoolSize=20,
            minPoolSize=2,
            serverSelectionTimeoutMS=5000,
        )
    return _client


def get_db() -> motor.AsyncIOMotorDatabase:
    return get_client()[settings.mongo_db]


# ── Collection helpers ──────────────────────────────────────────────────────
def col_main_data() -> motor.AsyncIOMotorCollection:
    return get_db()["main_data"]


def col_embeddings() -> motor.AsyncIOMotorCollection:
    return get_db()["embeddings"]


def col_conversations() -> motor.AsyncIOMotorCollection:
    return get_db()["conversations"]


def col_logs() -> motor.AsyncIOMotorCollection:
    return get_db()["logs"]


def col_feedback() -> motor.AsyncIOMotorCollection:
    return get_db()["feedback"]


# ── Index bootstrap ─────────────────────────────────────────────────────────
async def ensure_indexes() -> None:
    """Create all required indexes on startup (idempotent)."""

    # main_data – text search + common filter fields
    await col_main_data().create_indexes([
        IndexModel([("$**", TEXT)], name="main_data_text"),
        IndexModel([("outlet_id", ASCENDING)], name="outlet_id_idx"),
        IndexModel([("region", ASCENDING)], name="region_idx"),
        IndexModel([("category", ASCENDING)], name="category_idx"),
        IndexModel([("date", ASCENDING)], name="date_idx"),
    ])

    # embeddings – metadata filters + (Atlas-style vector search handled separately)
    await col_embeddings().create_indexes([
        IndexModel([("metadata.outlet_id", ASCENDING)], name="emb_outlet_idx"),
        IndexModel([("metadata.region", ASCENDING)], name="emb_region_idx"),
        IndexModel([("metadata.source_collection", ASCENDING)], name="emb_source_idx"),
    ])

    # conversations
    await col_conversations().create_indexes([
        IndexModel([("session_id", ASCENDING)], name="session_id_idx", unique=True),
        IndexModel([("updated_at", ASCENDING)], name="conv_updated_idx"),
    ])

    # logs
    await col_logs().create_indexes([
        IndexModel([("created_at", ASCENDING)], name="log_created_idx"),
        IndexModel([("session_id", ASCENDING)], name="log_session_idx"),
        IndexModel([("error", ASCENDING)], name="log_error_idx"),
    ])

    # feedback
    await col_feedback().create_indexes([
        IndexModel([("session_id", ASCENDING)], name="fb_session_idx"),
        IndexModel([("created_at", ASCENDING)], name="fb_created_idx"),
    ])

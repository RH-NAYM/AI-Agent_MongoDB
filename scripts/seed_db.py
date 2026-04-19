#!/usr/bin/env python3
"""
scripts/seed_db.py  –  Seed MongoDB with realistic retail sample data.

Run:
    python scripts/seed_db.py

This script:
  1. Inserts 200 retail transaction records into `main_data`
  2. Generates text descriptions for each record
  3. Embeds descriptions and stores them in `embeddings`

Requires the app to be importable (run from project root).
"""
import asyncio
import random
import sys
import os
from datetime import datetime, timedelta, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.mongo import get_db, ensure_indexes, col_embeddings
from app.db.schemas import EmbeddingDoc
from app.services.embedding_service import get_embedding_service

REGIONS = ["North", "South", "East", "West", "Central"]
CATEGORIES = ["Electronics", "Clothing", "Food & Beverage", "Home & Garden", "Sports", "Books"]
OUTLETS = [f"O-{i:02d}" for i in range(1, 16)]
PRODUCTS = {
    "Electronics": ["Smart TV 55\"", "Laptop Pro", "Bluetooth Speaker", "Wireless Headphones", "Tablet 10\""],
    "Clothing": ["Winter Jacket", "Running Shoes", "Casual T-Shirt", "Formal Trousers", "Summer Dress"],
    "Food & Beverage": ["Organic Coffee", "Green Tea Pack", "Protein Bar Box", "Mineral Water 24pk", "Fruit Juice 1L"],
    "Home & Garden": ["LED Desk Lamp", "Garden Hose 15m", "Storage Organizer", "Scented Candle Set", "Plant Pot L"],
    "Sports": ["Yoga Mat", "Resistance Bands", "Football", "Tennis Racket", "Cycling Gloves"],
    "Books": ["Python Mastery", "Data Science Guide", "Business Strategy", "Fiction Bestseller", "History Atlas"],
}

PRICE_RANGES = {
    "Electronics": (200, 1500),
    "Clothing": (20, 200),
    "Food & Beverage": (5, 50),
    "Home & Garden": (15, 120),
    "Sports": (10, 180),
    "Books": (8, 60),
}


def make_record(i: int) -> dict:
    category = random.choice(CATEGORIES)
    product = random.choice(PRODUCTS[category])
    price_min, price_max = PRICE_RANGES[category]
    unit_price = round(random.uniform(price_min, price_max), 2)
    quantity = random.randint(1, 20)
    revenue = round(unit_price * quantity, 2)
    outlet = random.choice(OUTLETS)
    region = random.choice(REGIONS)
    date = datetime.now(timezone.utc) - timedelta(days=random.randint(0, 365))

    return {
        "record_id": f"REC-{i:05d}",
        "outlet_id": outlet,
        "region": region,
        "category": category,
        "product_name": product,
        "unit_price": unit_price,
        "quantity": quantity,
        "revenue": revenue,
        "customer_id": f"C-{random.randint(1000, 9999)}",
        "date": date.strftime("%Y-%m-%d"),
        "month": date.month,
        "year": date.year,
        "created_at": date,
    }


def make_description(record: dict) -> str:
    return (
        f"Outlet {record['outlet_id']} in the {record['region']} region sold "
        f"{record['quantity']} unit(s) of {record['product_name']} "
        f"(category: {record['category']}) on {record['date']} "
        f"generating revenue of ${record['revenue']:.2f}."
    )


async def seed():
    print("🌱 Seeding retail_agent_db …")
    await ensure_indexes()
    db = get_db()

    # Clear existing seed data
    await db["main_data"].delete_many({"record_id": {"$regex": "^REC-"}})
    await col_embeddings().delete_many({"metadata.source_collection": "main_data"})
    print("  Cleared existing seed records.")

    # Generate records
    records = [make_record(i) for i in range(1, 201)]
    result = await db["main_data"].insert_many(records)
    print(f"  ✅ Inserted {len(result.inserted_ids)} records into main_data")

    # Generate embeddings
    embed_svc = get_embedding_service()
    batch_size = 20
    total_embedded = 0

    for i in range(0, len(records), batch_size):
        batch = records[i: i + batch_size]
        texts = [make_description(r) for r in batch]
        vectors = await embed_svc.embed_many(texts)

        emb_docs = []
        for r, text, vec in zip(batch, texts, vectors):
            emb_docs.append(
                EmbeddingDoc(
                    text=text,
                    vector=vec,
                    metadata={
                        "source_collection": "main_data",
                        "outlet_id": r["outlet_id"],
                        "region": r["region"],
                        "category": r["category"],
                        "record_id": r["record_id"],
                    },
                ).model_dump(by_alias=True)
            )

        await col_embeddings().insert_many(emb_docs)
        total_embedded += len(emb_docs)
        print(f"  Embedded {total_embedded}/{len(records)} …", end="\r")

    print(f"\n  ✅ Stored {total_embedded} embedding documents")
    print("🎉 Seeding complete!")


if __name__ == "__main__":
    asyncio.run(seed())

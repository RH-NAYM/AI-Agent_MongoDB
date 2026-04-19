# 🤖 Retail AI Agent System with MongoDB

[![main branch](https://img.shields.io/badge/branch-main-red?style=flat&logo=git&logoColor=white)](https://github.com/RH-NAYM/AI-Agent_MongoDB/tree/main)

<p align="center">
  <a href="https://opencv.org/" target="_blank">
    <img src="https://img.shields.io/badge/OpenCV-Computer%20Vision-green?logo=opencv&logoColor=white" alt="OpenCV">
  </a>
  <a href="https://pytorch.org/" target="_blank">
    <img src="https://img.shields.io/badge/PyTorch-Deep%20Learning-red?logo=pytorch&logoColor=white" alt="PyTorch">
  </a>
  <a href="https://github.com/cvg/LightGlue" target="_blank">
    <img src="https://img.shields.io/badge/LightGlue-Feature%20Matching-purple" alt="LightGlue">
  </a>
  <a href="https://jupyter.org/" target="_blank">
    <img src="https://img.shields.io/badge/Jupyter-Notebook-orange?logo=jupyter&logoColor=white" alt="Jupyter">
  </a>
</p>

A production-grade **multi-agent AI chatbot** built with Python, FastAPI, MongoDB, and Ollama (`qwen2.5`).

---

## Architecture

```
User Request
     │
     ▼
┌──────────────────────────────────────────────────────┐
│                    Orchestrator                       │
│                                                      │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │   Planner   │→ │   Executor   │→ │   Critic    │ │
│  │   Agent     │  │   Agent      │  │   Agent     │ │
│  └─────────────┘  └──────────────┘  └─────────────┘ │
│         │               │                  │         │
│         ▼               ▼                  ▼         │
│  ┌─────────────────────────────────────────────────┐ │
│  │                  Tool Registry                  │ │
│  │  mongo_find │ mongo_aggregate │ vector_search   │ │
│  │  memory_fetch │ memory_store                   │ │
│  └─────────────────────────────────────────────────┘ │
│         │               │                            │
│         ▼               ▼                            │
│  ┌────────────┐  ┌──────────────┐                   │
│  │  MongoDB   │  │    Ollama    │                   │
│  │(Motor async│  │  (qwen2.5)  │                   │
│  └────────────┘  └──────────────┘                   │
└──────────────────────────────────────────────────────┘
```

### Agent Roles

| Agent | Responsibility |
|-------|---------------|
| **Planner** | Analyzes query → picks strategy (RAG / find / aggregate / direct) |
| **Executor** | Generates & runs tool calls (LLM → MongoDB query → results) |
| **Critic** | Validates response quality → triggers retry if needed |
| **Memory** | Reads/writes conversation history from MongoDB |

### Self-Correction Loop

```
Planner → Executor → Draft Response → Critic
                                         │
                          ┌──── passed? ─┘
                          │
                     NO   ▼              YES
              Improved Query → retry    Return response
              (up to 3 times)
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI (async) |
| Database | MongoDB via Motor (async) |
| LLM | Ollama – `qwen2.5` |
| Embeddings | Ollama `nomic-embed-text` or `sentence-transformers` |
| Schema | Pydantic v2 |
| Logging | structlog (JSON) |

---

## Project Structure

```
ai_agent_system/
├── app/
│   ├── main.py                 # FastAPI app factory + lifespan
│   ├── config.py               # Settings via pydantic-settings
│   ├── api/
│   │   ├── __init__.py         # Router aggregator
│   │   └── routes/
│   │       ├── chat.py         # POST /chat (SSE streaming)
│   │       ├── history.py      # GET /history/{session_id}
│   │       ├── logs.py         # GET /logs + POST /feedback
│   │       └── ingest.py       # POST /ingest
│   ├── agents/
│   │   ├── orchestrator.py     # Master pipeline + retry loop
│   │   ├── planner.py          # Query intent classification
│   │   ├── executor.py         # Tool dispatch + query generation
│   │   ├── critic.py           # Output quality validation
│   │   └── memory_agent.py     # Conversation memory R/W
│   ├── tools/
│   │   ├── __init__.py         # Tool registry + execute_tool()
│   │   ├── mongo_find.py       # Safe find() executor
│   │   ├── mongo_aggregate.py  # Safe aggregation executor
│   │   ├── vector_search.py    # Hybrid semantic search
│   │   └── memory_tools.py     # memory_fetch + memory_store
│   ├── db/
│   │   ├── mongo.py            # Motor client + collection helpers
│   │   └── schemas.py          # MongoDB document Pydantic models
│   ├── services/
│   │   ├── ollama_service.py   # Async Ollama client (chat + embed)
│   │   ├── embedding_service.py# Pluggable embed backend
│   │   └── logging_service.py  # Async LogSession context manager
│   ├── models/
│   │   └── chat.py             # API request/response Pydantic models
│   └── utils/
│       ├── safety.py           # Allowlist safety guard
│       └── helpers.py          # JSON parsing, text formatting
├── scripts/
│   └── seed_db.py              # Seed 200 retail records + embeddings
├── .env.example
├── requirements.txt
└── README.md
```

---

## MongoDB Collections

### `main_data` – Retail Records
```json
{
  "record_id": "REC-00042",
  "outlet_id": "O-07",
  "region": "North",
  "category": "Electronics",
  "product_name": "Smart TV 55\"",
  "unit_price": 849.99,
  "quantity": 2,
  "revenue": 1699.98,
  "customer_id": "C-4521",
  "date": "2024-03-15",
  "month": 3,
  "year": 2024,
  "created_at": "2024-03-15T10:30:00Z"
}
```

### `embeddings` – Vector Store
```json
{
  "_id": "01HXYZ...",
  "text": "Outlet O-07 in North region sold 2 Smart TV 55\" on 2024-03-15...",
  "vector": [0.021, -0.043, ...],
  "metadata": {
    "source_collection": "main_data",
    "outlet_id": "O-07",
    "region": "North",
    "category": "Electronics"
  },
  "created_at": "2024-03-15T10:30:01Z"
}
```

### `conversations` – Session Memory
```json
{
  "session_id": "user-session-abc123",
  "messages": [
    {"role": "user", "content": "What sold best last month?", "timestamp": "..."},
    {"role": "assistant", "content": "Electronics led with...", "timestamp": "..."}
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

### `logs` – Observability
```json
{
  "session_id": "user-session-abc123",
  "user_query": "Show me top outlets by revenue",
  "agent_plan": "Use aggregation to group by outlet_id",
  "tool_calls": [
    {
      "tool_name": "mongo_aggregate_tool",
      "arguments": {"collection": "main_data", "pipeline": [...]},
      "result_summary": "5 results returned",
      "success": true
    }
  ],
  "final_response": "The top outlets by revenue are...",
  "execution_time_ms": 1243.5,
  "retry_count": 0,
  "error": null,
  "created_at": "..."
}
```

---

## Setup (Arch Linux)

### 1. Prerequisites

```bash
# MongoDB
yay -S mongodb-bin
sudo systemctl start mongodb

# Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5
ollama pull nomic-embed-text   # for embeddings
```

### 2. Pythonf Environment

```bash
cd ai_agent_system
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration

```bash
cp .env.example .env
# Edit .env if needed (defaults work out of the box)
```

### 4. Seed the Database

```bash
python scripts/seed_db.py
```

### 5. Run the Server

```bash
python -m app.main
# or
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API docs: **http://localhost:8000/docs**

---

## API Reference

### POST /api/v1/chat – Chat (Streaming)

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Which region had the highest revenue last year?",
    "session_id": "demo-session-001",
    "stream": true
  }'
```

**SSE Response:**
```
data: {"delta": "Based", "session_id": "demo-session-001"}
data: {"delta": " on the aggregated data,", "session_id": "demo-session-001"}
data: {"delta": " the North region led...", "session_id": "demo-session-001"}
data: [DONE]
```

### POST /api/v1/chat – Chat (Non-streaming)

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show me Electronics sales for outlet O-07",
    "session_id": "demo-session-001",
    "stream": false
  }'
```

### GET /api/v1/history/{session_id}

```bash
curl http://localhost:8000/api/v1/history/demo-session-001?last_n=20
```

### GET /api/v1/logs

```bash
curl "http://localhost:8000/api/v1/logs?page=1&page_size=10&errors_only=false"
```

### POST /api/v1/feedback

```bash
curl -X POST http://localhost:8000/api/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"session_id": "demo-session-001", "rating": 5, "comment": "Perfect answer!"}'
```

### POST /api/v1/ingest

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "collection": "main_data",
    "embed_field": "product_name",
    "documents": [
      {
        "outlet_id": "O-99",
        "region": "West",
        "category": "Sports",
        "product_name": "Premium Yoga Mat with carry strap",
        "unit_price": 45.99,
        "quantity": 10,
        "revenue": 459.90,
        "date": "2025-01-10"
      }
    ]
  }'
```

---

## Example Queries to Try

| Query | Expected Agent Behavior |
|-------|------------------------|
| "What is the total revenue by category?" | `mongo_aggregate` → GROUP BY category |
| "Show all Electronics sales from outlet O-07" | `mongo_find` → filter by category + outlet_id |
| "What are the top 5 products by quantity sold?" | `mongo_aggregate` → GROUP + SORT + LIMIT |
| "Tell me about our best performing region" | `hybrid` → aggregate + RAG context |
| "What yoga products do we sell?" | `vector_search` → semantic similarity |
| "Hello, how are you?" | `direct_answer` → no DB call |

---

## Safety Rules

The system **never** allows:
- `delete_many`, `deleteMany`
- `drop_collection`, `dropCollection`
- `drop_database`, `dropDatabase`
- `$where` (arbitrary JS)
- `eval`, `mapReduce`, `system.js`

Any LLM-generated query containing these keywords is **rejected before execution**.

---

## Extending the System

### Add a new tool
1. Create `app/tools/my_tool.py` with an async function
2. Register it in `app/tools/__init__.py` (`_TOOLS` dict + `TOOL_SCHEMAS` list)
3. Update the Planner's system prompt to mention the tool

### Switch LLM
Change `OLLAMA_MODEL` in `.env`. Any Ollama-compatible model works.

### Use Atlas Vector Search
Replace the in-process cosine ranking in `vector_search.py` with a
`$vectorSearch` aggregation stage (requires MongoDB Atlas M10+).

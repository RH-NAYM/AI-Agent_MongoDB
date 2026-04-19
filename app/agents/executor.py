"""
app/agents/executor.py  –  Executor Agent

Responsibility: given a plan produced by the Planner,
  1. For DB steps: ask the LLM to generate the concrete query arguments
  2. Execute the tool
  3. Collect all results and return structured output

The executor handles both:
  - mongo_find_tool   → LLM generates filter/projection/sort/limit
  - mongo_aggregate_tool → LLM generates pipeline
  - vector_search_tool → passes query text + metadata filter directly
  - memory tools       → handled by MemoryAgent directly
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import structlog

from app.config import get_settings
from app.services.ollama_service import get_ollama
from app.tools import execute_tool
from app.utils.helpers import safe_json_parse, truncate, mongo_docs_to_text
from app.utils.safety import validate_raw_string

log = structlog.get_logger(__name__)
settings = get_settings()

# ── Prompt for generating find args ──────────────────────────────────────────
_FIND_PROMPT = """You are a MongoDB expert. Given the user query, generate a MongoDB find() call.

User query: {query}

Available collection: {collection}
Sample schema: {schema_hint}

Respond ONLY with a valid JSON object, no prose:
{{
  "query_filter": {{}},
  "projection": null,
  "sort": null,
  "limit": 20
}}
"""

# ── Prompt for generating aggregate pipeline ──────────────────────────────────
_AGG_PROMPT = """You are a MongoDB expert. Generate an aggregation pipeline for the query below.

User query: {query}
Collection: {collection}
Sample schema: {schema_hint}

Allowed stages: $match, $group, $sort, $limit, $skip, $project, $unwind, $lookup, $count, $addFields, $facet.

Respond ONLY with a valid JSON array of pipeline stages, no prose. Example:
[
  {{ "$match": {{ "region": "North" }} }},
  {{ "$group": {{ "_id": "$category", "total": {{ "$sum": "$revenue" }} }} }},
  {{ "$sort": {{ "total": -1 }} }},
  {{ "$limit": 10 }}
]
"""

# ── Schema hints ──────────────────────────────────────────────────────────────
_SCHEMA_HINTS: dict[str, str] = {
    "main_data": (
        '{"outlet_id": "O-42", "region": "North", "category": "Electronics", '
        '"product_name": "TV-55", "date": "2024-01-15", "revenue": 1200.50, '
        '"quantity": 3, "customer_id": "C-99"}'
    ),
    "embeddings": '{"text": "...", "metadata": {"outlet_id": "O-42", "region": "South"}}',
}


class ExecutorAgent:
    def __init__(self) -> None:
        self.ollama = get_ollama()

    async def execute_plan(
        self,
        query: str,
        plan: dict[str, Any],
        log_session=None,
    ) -> dict[str, Any]:
        """
        Execute all steps in the plan and accumulate results.

        Returns:
          {
            "tool_results": [...],
            "context_text": str   ← formatted text passed to the final LLM call
          }
        """
        tool_results = []
        context_chunks: list[str] = []

        for step in plan.get("steps", []):
            tool_name = step.get("tool")
            if not tool_name or tool_name == "none":
                continue

            result = await self._execute_step(query, step, tool_name)
            tool_results.append({"tool": tool_name, "result": result})

            if log_session:
                log_session.add_tool_call(
                    tool_name=tool_name,
                    arguments={"step": step},
                    result_summary=truncate(str(result), 200),
                    success=result.get("success", False),
                )

            # Format result as text for final LLM prompt
            chunk = _format_result_chunk(tool_name, result)
            if chunk:
                context_chunks.append(chunk)

        context_text = "\n\n".join(context_chunks) if context_chunks else "No data retrieved."

        return {"tool_results": tool_results, "context_text": context_text}

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _execute_step(
        self, query: str, step: dict, tool_name: str
    ) -> dict[str, Any]:
        """Dispatch a single plan step to the appropriate tool."""

        collection = step.get("collection") or "main_data"
        schema_hint = _SCHEMA_HINTS.get(collection, "")

        try:
            if tool_name == "mongo_find_tool":
                args = await self._gen_find_args(query, collection, schema_hint)
                return await execute_tool("mongo_find_tool", {**args, "collection": collection})

            elif tool_name == "mongo_aggregate_tool":
                pipeline = await self._gen_pipeline(query, collection, schema_hint)
                return await execute_tool("mongo_aggregate_tool", {
                    "collection": collection,
                    "pipeline": pipeline,
                })

            elif tool_name == "vector_search_tool":
                return await execute_tool("vector_search_tool", {
                    "query_text": query,
                    "metadata_filter": step.get("metadata_filter") or None,
                })

            else:
                log.warning("executor_unknown_tool", tool=tool_name)
                return {"success": False, "error": f"Unknown tool: {tool_name}"}

        except Exception as exc:  # noqa: BLE001
            log.error("executor_step_error", tool=tool_name, error=str(exc))
            return {"success": False, "error": str(exc)}

    async def _gen_find_args(
        self, query: str, collection: str, schema_hint: str
    ) -> dict[str, Any]:
        """Ask LLM to generate mongo_find_tool arguments."""
        prompt = _FIND_PROMPT.format(
            query=query, collection=collection, schema_hint=schema_hint
        )
        raw = await self.ollama.generate(prompt)
        validate_raw_string(raw)   # safety scan before parse
        try:
            args = safe_json_parse(raw)
            # Ensure required keys
            args.setdefault("query_filter", {})
            args.setdefault("projection", None)
            args.setdefault("sort", None)
            args.setdefault("limit", 20)
            return args
        except Exception:
            log.warning("executor_find_args_parse_error", raw=truncate(raw, 200))
            return {"query_filter": {}, "projection": None, "sort": None, "limit": 20}

    async def _gen_pipeline(
        self, query: str, collection: str, schema_hint: str
    ) -> list[dict]:
        """Ask LLM to generate an aggregation pipeline."""
        prompt = _AGG_PROMPT.format(
            query=query, collection=collection, schema_hint=schema_hint
        )
        raw = await self.ollama.generate(prompt)
        validate_raw_string(raw)
        try:
            pipeline = safe_json_parse(raw)
            if not isinstance(pipeline, list):
                raise ValueError("Expected a JSON array")
            return pipeline
        except Exception:
            log.warning("executor_pipeline_parse_error", raw=truncate(raw, 200))
            return [{"$limit": 20}]   # fallback: return first 20 docs


# ── Result formatter ──────────────────────────────────────────────────────────

def _format_result_chunk(tool_name: str, result: dict) -> str:
    """Convert tool output to LLM-readable text."""
    if not result.get("success"):
        return f"[{tool_name}] Error: {result.get('error', 'unknown')}"

    if tool_name == "mongo_find_tool":
        docs = result.get("documents", [])
        if not docs:
            return f"[{tool_name}] No matching records found."
        return f"[Database Records – {len(docs)} found]\n{mongo_docs_to_text(docs)}"

    elif tool_name == "mongo_aggregate_tool":
        results = result.get("results", [])
        if not results:
            return f"[{tool_name}] Aggregation returned no results."
        return f"[Aggregation Results]\n{json.dumps(results[:50], indent=2, default=str)}"

    elif tool_name == "vector_search_tool":
        hits = result.get("results", [])
        if not hits:
            return "[Knowledge Base] No relevant documents found."
        chunks = [f"[Score: {h['_score']:.3f}] {h['text']}" for h in hits]
        return "[Knowledge Base Context]\n" + "\n---\n".join(chunks)

    return str(result)

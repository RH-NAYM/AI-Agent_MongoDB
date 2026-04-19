"""
app/agents/planner.py  –  Planner Agent

Responsibility: given a user query + conversation history, decide
the execution strategy and produce a structured plan.

Plan schema (JSON the LLM returns):
{
  "intent": "rag | mongo_find | mongo_aggregate | direct_answer | hybrid",
  "reasoning": "...",
  "steps": [
    {
      "tool": "mongo_find_tool | mongo_aggregate_tool | vector_search_tool | none",
      "description": "...",
      "collection": "...",        // if applicable
      "metadata_filter": {...}    // for vector search
    }
  ],
  "direct_answer": "..."          // only when intent == "direct_answer"
}
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from app.config import get_settings
from app.services.ollama_service import get_ollama
from app.tools import TOOL_SCHEMAS
from app.utils.helpers import safe_json_parse, truncate

log = structlog.get_logger(__name__)
settings = get_settings()

_SYSTEM_PROMPT = """You are the Planner Agent in a multi-agent AI system that answers questions \
about a retail business stored in MongoDB.

Your sole job is to analyze the user's question and output a structured JSON plan.
Do NOT answer the question yourself – only plan how to answer it.

Available tools:
{tool_schemas}

Collections available:
- main_data      : retail records (products, sales, outlet_id, region, category, date, revenue, quantity)
- embeddings     : vector store for semantic search

Respond ONLY with a valid JSON object. No markdown, no prose.

JSON schema:
{{
  "intent": "rag | mongo_find | mongo_aggregate | direct_answer | hybrid",
  "reasoning": "<short explanation>",
  "steps": [
    {{
      "tool": "<tool_name>",
      "description": "<what this step does>",
      "collection": "<collection_name or null>",
      "metadata_filter": {{}} 
    }}
  ],
  "direct_answer": "<only if intent == direct_answer, else null>"
}}

Rules:
- Use 'mongo_find'      for specific record lookups with clear filter criteria
- Use 'mongo_aggregate' for grouping, trends, totals, averages, rankings
- Use 'rag'             for open-ended questions about concepts, policies, descriptions
- Use 'hybrid'          when both structured query AND semantic context are needed
- Use 'direct_answer'   for greetings, clarifications, or questions with no data needed
"""


class PlannerAgent:
    def __init__(self) -> None:
        self.ollama = get_ollama()

    async def plan(
        self,
        query: str,
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        """
        Produce an execution plan for the given user query.

        Returns a parsed plan dict. On parse failure, returns a safe fallback.
        """
        tool_schema_text = json.dumps(
            [{"name": t["name"], "description": t["description"]} for t in TOOL_SCHEMAS],
            indent=2,
        )
        system = _SYSTEM_PROMPT.format(tool_schemas=tool_schema_text)

        # Build a short context window for the planner
        context_msgs = history[-4:] if history else []  # last 2 exchanges
        messages = context_msgs + [{"role": "user", "content": query}]

        log.info("planner_agent_start", query=truncate(query, 120))

        raw = await self.ollama.chat(messages=messages, system=system)

        log.debug("planner_agent_raw_output", raw=truncate(raw, 300))

        try:
            plan = safe_json_parse(raw)
            plan.setdefault("intent", "rag")
            plan.setdefault("reasoning", "")
            plan.setdefault("steps", [])
            plan.setdefault("direct_answer", None)
            log.info("planner_agent_success", intent=plan["intent"])
            return plan
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning(
                "planner_agent_parse_error",
                error=str(exc),
                raw=truncate(raw, 200),
            )
            # Fallback: treat as RAG
            return {
                "intent": "rag",
                "reasoning": "Parse error – defaulting to RAG",
                "steps": [
                    {
                        "tool": "vector_search_tool",
                        "description": "Semantic search for the query",
                        "collection": None,
                        "metadata_filter": {},
                    }
                ],
                "direct_answer": None,
            }

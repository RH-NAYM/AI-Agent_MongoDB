"""
app/utils/helpers.py  –  Shared utility functions.
"""
from __future__ import annotations

import json
import re
from typing import Any


def truncate(text: str, max_chars: int = 500) -> str:
    """Truncate a string for log summaries."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def extract_json_block(text: str) -> str:
    """
    Extract a JSON object or array from LLM output that may contain
    markdown code fences or explanatory prose.
    """
    # Try ```json ... ``` first
    md_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", text)
    if md_match:
        return md_match.group(1).strip()

    # Fallback: first { } or [ ] block
    for pattern in (r"(\{[\s\S]*\})", r"(\[[\s\S]*\])"):
        m = re.search(pattern, text)
        if m:
            return m.group(1).strip()

    return text.strip()


def safe_json_parse(text: str) -> Any:
    """Parse JSON from LLM output, stripping code fences if needed."""
    cleaned = extract_json_block(text)
    return json.loads(cleaned)


def mongo_docs_to_text(docs: list[dict], max_docs: int = 10) -> str:
    """Serialize a list of Mongo documents into a readable text block."""
    subset = docs[:max_docs]
    lines = []
    for i, doc in enumerate(subset, 1):
        # Remove internal Mongo _id for cleaner display
        display = {k: v for k, v in doc.items() if k != "_id"}
        lines.append(f"[{i}] {json.dumps(display, default=str)}")
    if len(docs) > max_docs:
        lines.append(f"… and {len(docs) - max_docs} more records.")
    return "\n".join(lines)


def format_aggregation_result(result: list[dict]) -> str:
    """Pretty-print aggregation results."""
    if not result:
        return "No results returned."
    return json.dumps(result, indent=2, default=str)


def build_context_from_messages(
    messages: list[dict], window: int = 10
) -> list[dict[str, str]]:
    """
    Trim conversation history to the last `window` exchanges
    and return as Ollama-compatible message list.
    """
    relevant = messages[-window:]
    return [{"role": m["role"], "content": m["content"]} for m in relevant]

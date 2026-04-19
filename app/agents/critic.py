"""
app/agents/critic.py  –  Critic Agent (Self-Correction Loop)

The Critic evaluates the quality of:
  1. Tool execution results (did they return useful data?)
  2. The draft response (is it grounded, coherent, useful?)

If quality is below threshold:
  - Returns a critique + improved query hint
  - The orchestrator will retry (up to MAX_RETRY_ATTEMPTS)

Critic output JSON schema:
{
  "passed": true | false,
  "confidence": 0.0–1.0,
  "issues": ["..."],
  "improved_query": "..." | null   ← rewritten query for retry
}
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from app.config import get_settings
from app.services.ollama_service import get_ollama
from app.utils.helpers import safe_json_parse, truncate

log = structlog.get_logger(__name__)
settings = get_settings()

_CRITIC_SYSTEM = """You are the Critic Agent in a multi-agent AI system.
Your job is to evaluate whether a response is accurate, grounded in the retrieved data, and useful.

Respond ONLY with a valid JSON object:
{
  "passed": true | false,
  "confidence": <float 0.0-1.0>,
  "issues": ["<list any problems found>"],
  "improved_query": "<rewritten user query for retry if not passed, else null>"
}

Rules:
- passed=false if the response says "I don't know" or "no data found" but context WAS provided
- passed=false if the response contains hallucinated numbers not present in the context
- passed=false if the context shows an error and the response ignores it
- confidence < 0.5 triggers a retry recommendation
- improved_query should rephrase the original query to be more precise
"""


class CriticAgent:
    def __init__(self) -> None:
        self.ollama = get_ollama()

    async def evaluate(
        self,
        original_query: str,
        context_text: str,
        draft_response: str,
        tool_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Evaluate the draft response against the retrieved context.

        Returns a critique dict.
        """
        # Check for tool-level failures first
        hard_failure = self._detect_hard_failure(tool_results)

        prompt = f"""
Original user query: {original_query}

Retrieved context:
{truncate(context_text, 1000)}

Draft response:
{truncate(draft_response, 800)}

Tool execution summary:
{self._summarize_tools(tool_results)}

Hard failure detected: {hard_failure}

Evaluate and respond with JSON.
"""
        raw = await self.ollama.generate(prompt=prompt, system=_CRITIC_SYSTEM)

        log.debug("critic_agent_raw", raw=truncate(raw, 300))

        try:
            critique = safe_json_parse(raw)
            critique.setdefault("passed", True)
            critique.setdefault("confidence", 0.8)
            critique.setdefault("issues", [])
            critique.setdefault("improved_query", None)

            # Override: if all tools failed, force fail
            if hard_failure:
                critique["passed"] = False
                critique["confidence"] = 0.1
                if "All tools returned errors" not in critique["issues"]:
                    critique["issues"].insert(0, "All tools returned errors or empty results")

            log.info(
                "critic_agent_result",
                passed=critique["passed"],
                confidence=critique["confidence"],
                issues=critique["issues"],
            )
            return critique

        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("critic_agent_parse_error", error=str(exc))
            # Conservative: assume pass to avoid infinite loops
            return {
                "passed": True,
                "confidence": 0.6,
                "issues": [f"Critic parse error: {exc}"],
                "improved_query": None,
            }

    def _detect_hard_failure(self, tool_results: list[dict]) -> bool:
        """Return True if every tool call failed or returned empty."""
        if not tool_results:
            return False
        return all(
            not r.get("result", {}).get("success", True)
            or (
                r.get("result", {}).get("count", 1) == 0
                and r.get("result", {}).get("results", [1]) == []
                and r.get("result", {}).get("documents", [1]) == []
            )
            for r in tool_results
        )

    def _summarize_tools(self, tool_results: list[dict]) -> str:
        lines = []
        for r in tool_results:
            tool = r.get("tool", "?")
            res = r.get("result", {})
            success = res.get("success", False)
            count = res.get("count", res.get("results") and len(res.get("results", [])))
            lines.append(f"  {tool}: success={success}, result_count={count}")
        return "\n".join(lines) or "  (no tools called)"

"""
app/agents/orchestrator.py  –  Master Orchestrator

Drives the full request lifecycle:

  1. Memory Agent  → load history
  2. Planner Agent → produce execution plan
  3. Executor Agent → run tools, collect context
  4. Ollama         → generate draft response
  5. Critic Agent  → evaluate quality
  6. Retry loop    → up to MAX_RETRY_ATTEMPTS if critic rejects
  7. Memory Agent  → store final exchange
  8. LogSession    → persist observability record

Exposes both:
  - run()          → returns full response string
  - stream()       → async generator of text chunks
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Optional

import structlog

from app.config import get_settings
from app.agents.planner import PlannerAgent
from app.agents.executor import ExecutorAgent
from app.agents.critic import CriticAgent
from app.agents.memory_agent import MemoryAgent
from app.services.ollama_service import get_ollama
from app.services.logging_service import LogSession
from app.utils.helpers import truncate

log = structlog.get_logger(__name__)
settings = get_settings()

# ── Final synthesis prompt ────────────────────────────────────────────────────
_SYNTHESIS_SYSTEM = """You are a helpful retail analytics AI assistant.
You have access to structured sales data, product records, and a knowledge base.

Answer the user's question accurately using ONLY the provided context data.
If the context is insufficient, say so clearly instead of guessing.
Be concise, factual, and format numbers and tables clearly when relevant.
"""

_SYNTHESIS_PROMPT = """Conversation history is provided as context.

Retrieved data context:
{context}

User question: {query}

Answer based strictly on the context above:"""


class Orchestrator:
    def __init__(self) -> None:
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.critic = CriticAgent()
        self.memory = MemoryAgent()
        self.ollama = get_ollama()

    # ── Public: full response ────────────────────────────────────────────────

    async def run(
        self,
        query: str,
        session_id: str,
    ) -> str:
        """Execute the full pipeline, return the final answer string."""
        full_response = ""
        async for chunk in self._pipeline(query, session_id, stream=False):
            full_response += chunk
        return full_response

    # ── Public: streaming ────────────────────────────────────────────────────

    async def stream(
        self,
        query: str,
        session_id: str,
    ) -> AsyncIterator[str]:
        """Stream the final answer chunk-by-chunk."""
        async for chunk in self._pipeline(query, session_id, stream=True):
            yield chunk

    # ── Core pipeline ─────────────────────────────────────────────────────────

    async def _pipeline(
        self,
        query: str,
        session_id: str,
        stream: bool,
    ) -> AsyncIterator[str]:
        async with LogSession(session_id, query) as ls:

            # ── 1. Load memory ────────────────────────────────────────────────
            history = await self.memory.get_ollama_context(session_id)

            # ── 2. Persist user message ───────────────────────────────────────
            await self.memory.store_message(session_id, "user", query)

            # ── 3. Plan ───────────────────────────────────────────────────────
            plan = await self.planner.plan(query, history)
            ls.set_plan(plan.get("reasoning", ""))

            log.info(
                "orchestrator_plan",
                session_id=session_id,
                intent=plan.get("intent"),
            )

            # ── 4. Short-circuit: direct answer ──────────────────────────────
            if plan.get("intent") == "direct_answer" and plan.get("direct_answer"):
                answer = plan["direct_answer"]
                ls.set_response(answer)
                await self.memory.store_message(session_id, "assistant", answer)
                if stream:
                    yield answer
                else:
                    yield answer
                return

            # ── 5. Execute plan (with retry loop) ────────────────────────────
            attempt = 0
            active_query = query
            context_text = ""
            tool_results: list[dict] = []

            while attempt < settings.max_retry_attempts:
                attempt += 1
                log.info(
                    "orchestrator_attempt",
                    session_id=session_id,
                    attempt=attempt,
                )

                if attempt > 1:
                    ls.increment_retry()
                    # Re-plan with the improved query from the Critic
                    plan = await self.planner.plan(active_query, history)

                exec_result = await self.executor.execute_plan(
                    active_query, plan, log_session=ls
                )
                context_text = exec_result["context_text"]
                tool_results = exec_result["tool_results"]

                # ── 6. Generate draft response ────────────────────────────────
                synthesis_prompt = _SYNTHESIS_PROMPT.format(
                    context=context_text,
                    query=active_query,
                )
                messages = history + [{"role": "user", "content": synthesis_prompt}]

                draft = await self.ollama.chat(
                    messages=messages,
                    system=_SYNTHESIS_SYSTEM,
                )

                # ── 7. Critic evaluation ──────────────────────────────────────
                critique = await self.critic.evaluate(
                    original_query=active_query,
                    context_text=context_text,
                    draft_response=draft,
                    tool_results=tool_results,
                )

                if critique["passed"] or attempt >= settings.max_retry_attempts:
                    # Accept this response
                    final_response = draft
                    ls.set_response(final_response)
                    await self.memory.store_message(
                        session_id, "assistant", final_response
                    )

                    if stream:
                        # Re-stream from a cached full response
                        # (true token streaming happens in stream_pipeline)
                        yield final_response
                    else:
                        yield final_response
                    return
                else:
                    # Critic rejected: improve query and retry
                    improved = critique.get("improved_query") or active_query
                    log.info(
                        "orchestrator_retry",
                        session_id=session_id,
                        issues=critique.get("issues"),
                        improved_query=truncate(improved, 120),
                    )
                    active_query = improved

            # Should not reach here but just in case
            yield "I'm sorry, I couldn't generate a confident answer. Please rephrase your question."

    # ── True streaming pipeline (token-level) ─────────────────────────────────

    async def stream_tokens(
        self,
        query: str,
        session_id: str,
    ) -> AsyncIterator[str]:
        """
        Token-level streaming.

        Strategy:
          - Run planner + executor fully (non-streaming, fast)
          - Stream only the final synthesis step token-by-token
          - Run critic AFTER full response is accumulated (non-blocking to user)
        """
        async with LogSession(session_id, query) as ls:

            history = await self.memory.get_ollama_context(session_id)
            await self.memory.store_message(session_id, "user", query)

            plan = await self.planner.plan(query, history)
            ls.set_plan(plan.get("reasoning", ""))

            if plan.get("intent") == "direct_answer" and plan.get("direct_answer"):
                answer = plan["direct_answer"]
                ls.set_response(answer)
                await self.memory.store_message(session_id, "assistant", answer)
                yield answer
                return

            active_query = query
            for attempt in range(1, settings.max_retry_attempts + 1):
                if attempt > 1:
                    ls.increment_retry()
                    plan = await self.planner.plan(active_query, history)

                exec_result = await self.executor.execute_plan(
                    active_query, plan, log_session=ls
                )
                context_text = exec_result["context_text"]
                tool_results = exec_result["tool_results"]

                synthesis_prompt = _SYNTHESIS_PROMPT.format(
                    context=context_text, query=active_query
                )
                messages = history + [{"role": "user", "content": synthesis_prompt}]

                # ── Stream tokens ─────────────────────────────────────────────
                accumulated = ""
                async for chunk in self.ollama.stream_chat(
                    messages=messages, system=_SYNTHESIS_SYSTEM
                ):
                    accumulated += chunk
                    yield chunk

                # ── Post-stream critic (background, does not block user) ───────
                critique = await self.critic.evaluate(
                    original_query=active_query,
                    context_text=context_text,
                    draft_response=accumulated,
                    tool_results=tool_results,
                )

                if critique["passed"] or attempt >= settings.max_retry_attempts:
                    ls.set_response(accumulated)
                    await self.memory.store_message(session_id, "assistant", accumulated)
                    return
                else:
                    improved = critique.get("improved_query") or active_query
                    log.info(
                        "orchestrator_stream_retry",
                        session_id=session_id,
                        attempt=attempt,
                        improved_query=truncate(improved, 120),
                    )
                    active_query = improved
                    # Signal retry to client
                    yield "\n\n[Refining answer…]\n\n"

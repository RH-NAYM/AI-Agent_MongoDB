"""
app/services/logging_service.py  –  Async observability layer.

Writes structured log documents to MongoDB `logs` collection.
Also configures structlog for JSON console output.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import structlog

from app.db.mongo import col_logs
from app.db.schemas import LogDoc, ToolCallLog

log = structlog.get_logger(__name__)


def configure_structlog(level: str = "INFO") -> None:
    import logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
    )


class LogSession:
    """
    Collects all events for a single request and persists them atomically.

    Usage::

        async with LogSession(session_id, user_query) as ls:
            ls.set_plan("Step 1: ...")
            ls.add_tool_call("mongo_find_tool", {...}, "12 docs", True)
            ls.set_response("Here is your answer …")
    """

    def __init__(self, session_id: Optional[str], user_query: str) -> None:
        self._doc = LogDoc(session_id=session_id, user_query=user_query)
        self._start = time.perf_counter()

    def set_plan(self, plan: str) -> None:
        self._doc.agent_plan = plan

    def add_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result_summary: str,
        success: bool,
    ) -> None:
        self._doc.tool_calls.append(
            ToolCallLog(
                tool_name=tool_name,
                arguments=arguments,
                result_summary=result_summary,
                success=success,
            )
        )

    def set_response(self, response: str) -> None:
        self._doc.final_response = response

    def set_error(self, error: str) -> None:
        self._doc.error = error

    def increment_retry(self) -> None:
        self._doc.retry_count += 1

    async def _save(self) -> None:
        self._doc.execution_time_ms = (time.perf_counter() - self._start) * 1000
        doc = self._doc.model_dump(by_alias=True)
        # Convert datetime objects – Motor handles them natively
        try:
            await col_logs().insert_one(doc)
        except Exception as exc:  # noqa: BLE001
            log.error("log_persist_failed", error=str(exc))

    async def __aenter__(self) -> "LogSession":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_val:
            self.set_error(str(exc_val))
        await self._save()
        return False   # don't suppress exceptions

"""
app/services/ollama_service.py  –  Async Ollama client.

Provides:
  - generate()           → full completion (returns str)
  - stream_generate()    → async generator of text chunks
  - chat()               → multi-turn completion
  - stream_chat()        → streamed multi-turn
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Any

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class OllamaService:
    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    # ── Internal ────────────────────────────────────────────────────────────

    async def _post_stream(self, endpoint: str, payload: dict) -> AsyncIterator[dict]:
        url = f"{self.base_url}/{endpoint}"
        async with self._client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    yield json.loads(line)

    async def _post_json(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.base_url}/{endpoint}"
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # ── Public API ───────────────────────────────────────────────────────────

    async def generate(self, prompt: str, system: str = "", **kwargs: Any) -> str:
        """Single-shot generation; returns full response string."""
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        payload.update(kwargs)
        data = await self._post_json("api/generate", payload)
        return data.get("response", "")

    async def stream_generate(
        self, prompt: str, system: str = "", **kwargs: Any
    ) -> AsyncIterator[str]:
        """Yield text chunks as they arrive."""
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
        }
        if system:
            payload["system"] = system
        payload.update(kwargs)
        async for chunk in self._post_stream("api/generate", payload):
            if text := chunk.get("response"):
                yield text

    async def chat(
        self,
        messages: list[dict[str, str]],
        system: str = "",
        **kwargs: Any,
    ) -> str:
        """Multi-turn chat; returns full assistant message."""
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": all_messages,
            "stream": False,
        }
        payload.update(kwargs)
        data = await self._post_json("api/chat", payload)
        return data.get("message", {}).get("content", "")

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        system: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield text chunks from multi-turn chat."""
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": all_messages,
            "stream": True,
        }
        payload.update(kwargs)
        async for chunk in self._post_stream("api/chat", payload):
            if text := chunk.get("message", {}).get("content"):
                yield text

    async def embed(self, text: str) -> list[float]:
        """Generate embedding via Ollama (requires pull of embed model)."""
        payload = {"model": settings.ollama_embed_model, "prompt": text}
        data = await self._post_json("api/embeddings", payload)
        return data.get("embedding", [])

    async def close(self) -> None:
        await self._client.aclose()


# ── Singleton ────────────────────────────────────────────────────────────────
_ollama: OllamaService | None = None


def get_ollama() -> OllamaService:
    global _ollama
    if _ollama is None:
        _ollama = OllamaService()
    return _ollama

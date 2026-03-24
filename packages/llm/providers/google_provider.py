"""Google provider adapter (Gemini models).

Install: pip install google-genai
This module is optional — if google-genai is not installed, the provider
simply won't register and Gemini models won't be available.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from packages.llm.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Pricing per million tokens (as of March 2026)
_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-pro":    {"input": 1.25, "output": 10.0},
    "gemini-2.5-flash":  {"input": 0.15, "output": 0.60},
    "gemini-2.0-flash":  {"input": 0.10, "output": 0.40},
}


class GoogleProvider(LLMProvider):
    """Calls Google's Gemini API via the official SDK."""

    def __init__(self) -> None:
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai
            self._client = genai.Client(
                api_key=os.environ.get("GOOGLE_API_KEY"),
            )
        return self._client

    @staticmethod
    def _strip_prefix(model: str) -> str:
        """'google/gemini-2.5-flash' → 'gemini-2.5-flash'"""
        return model.split("/", 1)[1] if "/" in model else model

    @staticmethod
    def _to_gemini_messages(messages: list[dict[str, str]]) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert OpenAI-style messages to Gemini format."""
        system = None
        contents = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            elif msg["role"] == "user":
                contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
            elif msg["role"] == "assistant":
                contents.append({"role": "model", "parts": [{"text": msg["content"]}]})
        return system, contents

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4000,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> LLMResponse:
        from google.genai import types

        client = self._get_client()
        api_model = self._strip_prefix(model)
        system, contents = self._to_gemini_messages(messages)

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        if system:
            config.system_instruction = system

        response = client.models.generate_content(
            model=api_model,
            contents=contents,
            config=config,
        )

        content = response.text or ""
        usage_meta = response.usage_metadata
        usage = {
            "prompt_tokens": getattr(usage_meta, "prompt_token_count", 0) or 0,
            "completion_tokens": getattr(usage_meta, "candidates_token_count", 0) or 0,
            "total_tokens": getattr(usage_meta, "total_token_count", 0) or 0,
        }
        cost = self.estimate_cost(api_model, usage["prompt_tokens"], usage["completion_tokens"])

        return LLMResponse(content=content, model=model, usage=usage, cost=cost, raw=response)

    async def acomplete(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4000,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> LLMResponse:
        from google.genai import types

        client = self._get_client()
        api_model = self._strip_prefix(model)
        system, contents = self._to_gemini_messages(messages)

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        if system:
            config.system_instruction = system

        response = await client.aio.models.generate_content(
            model=api_model,
            contents=contents,
            config=config,
        )

        content = response.text or ""
        usage_meta = response.usage_metadata
        usage = {
            "prompt_tokens": getattr(usage_meta, "prompt_token_count", 0) or 0,
            "completion_tokens": getattr(usage_meta, "candidates_token_count", 0) or 0,
            "total_tokens": getattr(usage_meta, "total_token_count", 0) or 0,
        }
        cost = self.estimate_cost(api_model, usage["prompt_tokens"], usage["completion_tokens"])

        return LLMResponse(content=content, model=model, usage=usage, cost=cost, raw=response)

    @staticmethod
    def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        clean = model.replace("google/", "")
        pricing = _PRICING.get(clean, {"input": 0.15, "output": 0.60})
        return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


# Auto-register (only if google-genai is installed)
try:
    import google.genai  # noqa: F401
    from packages.llm.providers import register_provider
    register_provider("google", GoogleProvider)
except ImportError:
    pass  # google-genai not installed — Gemini not available

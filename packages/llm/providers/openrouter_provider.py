"""OpenRouter provider adapter (Qwen, Llama, Mixtral, etc. via OpenAI-compatible API)."""

from __future__ import annotations

import logging
import os
from typing import Any

from packages.llm.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Pricing per million tokens (OpenRouter, as of April 2026)
_PRICING: dict[str, dict[str, float]] = {
    "qwen/qwen3.5-397b-a17b":  {"input": 0.39, "output": 0.90},
    "qwen/qwen3.5-122b-a10b":  {"input": 0.26, "output": 2.08},
    "qwen/qwen3.5-plus":       {"input": 0.26, "output": 1.56},
    "qwen/qwen3.5-35b-a3b":    {"input": 0.163, "output": 0.90},
    "qwen/qwen3.5-27b":        {"input": 0.195, "output": 0.90},
    "qwen/qwen3.5-flash":      {"input": 0.065, "output": 0.26},
    "qwen/qwen3.5-9b":         {"input": 0.04, "output": 0.15},
}

_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    """Calls OpenRouter's OpenAI-compatible API."""

    def __init__(self) -> None:
        self._client = None
        self._async_client = None

    def _get_client(self) -> Any:
        if self._client is None:
            import openai
            self._client = openai.OpenAI(
                api_key=os.environ.get("OPENROUTER_API_KEY"),
                base_url=_BASE_URL,
            )
        return self._client

    def _get_async_client(self) -> Any:
        if self._async_client is None:
            import openai
            self._async_client = openai.AsyncOpenAI(
                api_key=os.environ.get("OPENROUTER_API_KEY"),
                base_url=_BASE_URL,
            )
        return self._async_client

    @staticmethod
    def _strip_prefix(model: str) -> str:
        """'openrouter/qwen/qwen3.5-397b-a17b' → 'qwen/qwen3.5-397b-a17b'"""
        if model.startswith("openrouter/"):
            return model[len("openrouter/"):]
        return model

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4000,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> LLMResponse:
        client = self._get_client()
        api_model = self._strip_prefix(model)

        call_kwargs: dict[str, Any] = {
            "model": api_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # Forward extra kwargs (e.g. tools, tool_choice)
        call_kwargs.update(kwargs)

        response = client.chat.completions.create(**call_kwargs)

        choice = response.choices[0]
        content = choice.message.content or ""
        usage = {
            "prompt_tokens": response.usage.prompt_tokens or 0,
            "completion_tokens": response.usage.completion_tokens or 0,
            "total_tokens": response.usage.total_tokens or 0,
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
        client = self._get_async_client()
        api_model = self._strip_prefix(model)

        call_kwargs: dict[str, Any] = {
            "model": api_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        call_kwargs.update(kwargs)

        response = await client.chat.completions.create(**call_kwargs)

        choice = response.choices[0]
        content = choice.message.content or ""
        usage = {
            "prompt_tokens": response.usage.prompt_tokens or 0,
            "completion_tokens": response.usage.completion_tokens or 0,
            "total_tokens": response.usage.total_tokens or 0,
        }
        cost = self.estimate_cost(api_model, usage["prompt_tokens"], usage["completion_tokens"])

        return LLMResponse(content=content, model=model, usage=usage, cost=cost, raw=response)

    @staticmethod
    def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        clean = model.replace("openrouter/", "")
        pricing = _PRICING.get(clean, {"input": 0.39, "output": 0.90})
        return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


# Auto-register
from packages.llm.providers import register_provider
register_provider("openrouter", OpenRouterProvider)

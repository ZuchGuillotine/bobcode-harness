"""OpenAI provider adapter (GPT models)."""

from __future__ import annotations

import logging
import os
from typing import Any

from packages.llm.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Pricing per million tokens (as of March 2026)
_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.4-mini":  {"input": 0.15, "output": 0.60},
    "gpt-5.4":       {"input": 2.50, "output": 10.0},
    "gpt-4o":        {"input": 2.50, "output": 10.0},
    "gpt-4o-mini":   {"input": 0.15, "output": 0.60},
}


class OpenAIProvider(LLMProvider):
    """Calls OpenAI's Chat Completions API via the official SDK."""

    def __init__(self) -> None:
        self._client = None
        self._async_client = None

    def _get_client(self) -> Any:
        if self._client is None:
            import openai
            self._client = openai.OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
            )
        return self._client

    def _get_async_client(self) -> Any:
        if self._async_client is None:
            import openai
            self._async_client = openai.AsyncOpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
            )
        return self._async_client

    @staticmethod
    def _strip_prefix(model: str) -> str:
        """'openai/gpt-5.4-mini' → 'gpt-5.4-mini'"""
        return model.split("/", 1)[1] if "/" in model else model

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
        # Forward extra kwargs (e.g. tools, tool_choice) to the OpenAI API
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
        # Forward extra kwargs (e.g. tools, tool_choice) to the OpenAI API
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
        clean = model.replace("openai/", "")
        pricing = _PRICING.get(clean, {"input": 0.15, "output": 0.60})
        return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


# Auto-register
from packages.llm.providers import register_provider
register_provider("openai", OpenAIProvider)

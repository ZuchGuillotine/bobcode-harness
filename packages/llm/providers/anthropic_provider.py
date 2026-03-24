"""Anthropic provider adapter (Claude models)."""

from __future__ import annotations

import logging
import os
from typing import Any

from packages.llm.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Pricing per million tokens (as of March 2026)
_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6":   {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5":  {"input": 0.80, "output": 4.0},
}


class AnthropicProvider(LLMProvider):
    """Calls Anthropic's Messages API directly via the official SDK."""

    def __init__(self) -> None:
        self._client = None
        self._async_client = None

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
            )
        return self._client

    def _get_async_client(self) -> Any:
        if self._async_client is None:
            import anthropic
            self._async_client = anthropic.AsyncAnthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
            )
        return self._async_client

    @staticmethod
    def _strip_prefix(model: str) -> str:
        """'anthropic/claude-sonnet-4-6' → 'claude-sonnet-4-6'"""
        return model.split("/", 1)[1] if "/" in model else model

    @staticmethod
    def _extract_system(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
        """Anthropic requires system as a separate param, not in messages."""
        system = ""
        filtered = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                filtered.append(msg)
        return system, filtered

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
        system, filtered_messages = self._extract_system(messages)

        call_kwargs: dict[str, Any] = {
            "model": api_model,
            "messages": filtered_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            call_kwargs["system"] = system
        # Forward extra kwargs (e.g. tools, tool_choice) to the Anthropic API
        call_kwargs.update(kwargs)

        response = client.messages.create(**call_kwargs)

        content = ""
        for block in (response.content or []):
            if getattr(block, "text", None):
                content = block.text
                break
        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
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
        system, filtered_messages = self._extract_system(messages)

        call_kwargs: dict[str, Any] = {
            "model": api_model,
            "messages": filtered_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            call_kwargs["system"] = system
        # Forward extra kwargs (e.g. tools, tool_choice) to the Anthropic API
        call_kwargs.update(kwargs)

        response = await client.messages.create(**call_kwargs)

        content = ""
        for block in (response.content or []):
            if getattr(block, "text", None):
                content = block.text
                break
        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }
        cost = self.estimate_cost(api_model, usage["prompt_tokens"], usage["completion_tokens"])

        return LLMResponse(content=content, model=model, usage=usage, cost=cost, raw=response)

    @staticmethod
    def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        clean = model.replace("anthropic/", "")
        pricing = _PRICING.get(clean, {"input": 3.0, "output": 15.0})
        return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


# Auto-register
from packages.llm.providers import register_provider
register_provider("anthropic", AnthropicProvider)

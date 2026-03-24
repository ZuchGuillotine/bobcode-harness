"""Abstract base for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    """Normalized response from any provider."""
    content: str
    model: str
    usage: dict[str, int]  # prompt_tokens, completion_tokens, total_tokens
    cost: float  # estimated USD
    raw: Any = None  # original provider response


class LLMProvider(ABC):
    """Interface that every provider adapter must implement."""

    @abstractmethod
    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4000,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> LLMResponse:
        """Synchronous completion call."""
        ...

    @abstractmethod
    async def acomplete(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 4000,
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> LLMResponse:
        """Async completion call."""
        ...

    @staticmethod
    def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost in USD. Override per provider for accuracy."""
        return 0.0

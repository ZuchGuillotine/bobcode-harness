"""LLM router that maps agent roles to models via pluggable providers.

Replaces litellm with direct provider SDKs (anthropic, openai, google-genai)
for zero supply-chain risk. Add new providers by dropping a module in
packages/llm/providers/.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import yaml

from packages.llm.providers import get_provider, list_providers
from packages.llm.providers.base import LLMResponse

logger = logging.getLogger(__name__)


class LLMRouter:
    """Route LLM calls to the correct model based on agent role."""

    # Retry settings for rate-limited requests
    MAX_RETRIES = 5
    INITIAL_BACKOFF_SECS = 2.0
    MAX_BACKOFF_SECS = 60.0
    BACKOFF_MULTIPLIER = 2.0

    def __init__(
        self,
        config_path: str = "config/model_routing.yaml",
        sqlite_store: Any | None = None,
    ) -> None:
        self._config = self._load_config(config_path)
        self._store = sqlite_store
        self._usage: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(path: str) -> dict[str, Any]:
        config_file = Path(path)
        if not config_file.is_file():
            logger.warning(
                "Model routing config not found at %s; using empty config", path
            )
            return {}
        with config_file.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _resolve_role_config(self, role: str) -> dict[str, Any]:
        """Return the full config block for *role*."""
        routing = self._config.get("routing", {})
        return routing.get(role, {})

    def _resolve_model(self, role: str) -> tuple[str, list[str]]:
        """Return ``(primary_model, fallback_models)`` for *role*."""
        role_cfg = self._resolve_role_config(role)
        primary = role_cfg.get("model", "openai/gpt-5.4-mini")
        fallback = role_cfg.get("fallback")
        fallbacks = [fallback] if fallback else []
        return primary, fallbacks

    # ------------------------------------------------------------------
    # Rate limit detection and retry
    # ------------------------------------------------------------------

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        exc_str = str(exc).lower()
        return "rate_limit" in exc_str or "429" in exc_str or "too many requests" in exc_str

    def _call_with_retry(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        **kwargs: Any,
    ) -> LLMResponse:
        """Call provider with exponential backoff on rate limits."""
        provider = get_provider(model)
        backoff = self.INITIAL_BACKOFF_SECS

        for attempt in range(self.MAX_RETRIES):
            try:
                return provider.complete(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )
            except Exception as exc:
                if self._is_rate_limit_error(exc) and attempt < self.MAX_RETRIES - 1:
                    logger.warning(
                        "Rate limited on %s (attempt %d/%d) — backing off %.1fs",
                        model, attempt + 1, self.MAX_RETRIES, backoff,
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * self.BACKOFF_MULTIPLIER, self.MAX_BACKOFF_SECS)
                    continue
                raise

        raise RuntimeError(f"Exhausted {self.MAX_RETRIES} retries for {model}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call(
        self,
        role: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send *messages* to the model mapped to *role*.

        Tries the primary model first with exponential backoff on rate
        limits, then each fallback in order.
        """
        role_cfg = self._resolve_role_config(role)
        primary, fallbacks = self._resolve_model(role)
        models_to_try = [primary] + fallbacks

        # Merge role-level defaults with caller overrides
        max_tokens = kwargs.pop("max_tokens", role_cfg.get("max_tokens", 4000))
        temperature = kwargs.pop("temperature", role_cfg.get("temperature", 0.2))

        last_err: Exception | None = None
        for model in models_to_try:
            try:
                t0 = time.monotonic()
                response = self._call_with_retry(
                    model, messages, max_tokens, temperature, **kwargs,
                )
                duration = time.monotonic() - t0

                self._track_usage(model, response.usage, response.cost)

                return {
                    "content": response.content,
                    "model": response.model,
                    "usage": response.usage,
                    "cost": response.cost,
                    "duration_secs": round(duration, 3),
                }
            except Exception as exc:
                logger.warning("Model %s failed for role %s: %s", model, role, exc)
                last_err = exc
                continue

        raise RuntimeError(
            f"All models exhausted for role '{role}'. "
            f"Tried: {models_to_try}. "
            f"Available providers: {list_providers()}. "
            f"Last error: {last_err}"
        )

    # ------------------------------------------------------------------
    # Usage tracking
    # ------------------------------------------------------------------

    def _track_usage(
        self, model: str, usage: dict[str, int], cost: float
    ) -> None:
        if model not in self._usage:
            self._usage[model] = {
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost": 0.0,
                "calls": 0,
            }
        entry = self._usage[model]
        entry["total_tokens"] += usage.get("total_tokens", 0)
        entry["prompt_tokens"] += usage.get("prompt_tokens", 0)
        entry["completion_tokens"] += usage.get("completion_tokens", 0)
        entry["cost"] += cost
        entry["calls"] += 1

        if self._store is not None:
            try:
                self._store.record_skill_usage(
                    task_id="__global__",
                    skill_id=f"llm:{model}",
                    total_tokens=usage.get("total_tokens", 0),
                    total_cost=cost,
                )
            except Exception:
                logger.debug("Failed to persist LLM usage to SQLite", exc_info=True)

    def get_usage_summary(self) -> dict[str, Any]:
        """Return aggregate usage: total tokens, cost by model."""
        total_tokens = sum(m["total_tokens"] for m in self._usage.values())
        total_cost = sum(m["cost"] for m in self._usage.values())
        total_calls = sum(m["calls"] for m in self._usage.values())
        return {
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 6),
            "total_calls": total_calls,
            "by_model": {k: dict(v) for k, v in self._usage.items()},
        }

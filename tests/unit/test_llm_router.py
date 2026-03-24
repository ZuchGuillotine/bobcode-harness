"""Unit tests for packages.llm.router.LLMRouter."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from packages.llm.router import LLMRouter
from packages.llm.providers.base import LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "model_routing.yaml"
)


def _mock_provider() -> MagicMock:
    """Build a mock LLM provider that returns canned responses."""
    provider = MagicMock()
    provider.complete.return_value = LLMResponse(
        content="mocked response",
        model="mock/model",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        cost=0.003,
    )
    return provider


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestLoadConfig:
    """Tests for LLMRouter configuration loading."""

    def test_load_config(self) -> None:
        """Router loads model_routing.yaml and exposes routing entries."""
        router = LLMRouter(config_path=_CONFIG_PATH)
        config = router._config
        assert "routing" in config
        assert "planner" in config["routing"]
        assert "worker" in config["routing"]
        assert "reviewer" in config["routing"]
        assert "lightweight" in config["routing"]

    def test_load_config_missing_file(self, tmp_path) -> None:
        """Router handles missing config gracefully with empty config."""
        router = LLMRouter(config_path=str(tmp_path / "nonexistent.yaml"))
        assert router._config == {}


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

class TestResolveModel:
    """Tests for model resolution based on agent role."""

    @pytest.fixture(autouse=True)
    def _setup_router(self) -> None:
        self.router = LLMRouter(config_path=_CONFIG_PATH)

    def test_resolve_model_planner(self) -> None:
        primary, fallbacks = self.router._resolve_model("planner")
        assert primary == "anthropic/claude-opus-4-6"
        assert "openai/gpt-5.4-mini" in fallbacks

    def test_resolve_model_worker(self) -> None:
        primary, fallbacks = self.router._resolve_model("worker")
        assert primary == "anthropic/claude-sonnet-4-6"
        assert "openai/gpt-5.4-mini" in fallbacks

    def test_resolve_model_lightweight(self) -> None:
        primary, fallbacks = self.router._resolve_model("lightweight")
        assert primary == "openai/gpt-5.4-mini"
        assert fallbacks == []

    def test_resolve_model_unknown_role_uses_default(self) -> None:
        primary, fallbacks = self.router._resolve_model("unknown_role")
        assert primary == "openai/gpt-5.4-mini"
        assert fallbacks == []


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------

class TestGetUsageSummary:
    """Tests for LLMRouter.get_usage_summary."""

    def test_get_usage_summary(self) -> None:
        """Usage summary aggregates across calls."""
        mock = _mock_provider()

        with patch("packages.llm.router.get_provider", return_value=mock):
            router = LLMRouter(config_path=_CONFIG_PATH)
            router.call("planner", [{"role": "user", "content": "plan a task"}])
            router.call("worker", [{"role": "user", "content": "implement the plan"}])

        summary = router.get_usage_summary()
        assert summary["total_calls"] == 2
        assert summary["total_tokens"] == 300
        assert summary["total_cost"] == pytest.approx(0.006)
        assert "by_model" in summary

    def test_get_usage_summary_empty(self) -> None:
        """Usage summary is zeros when no calls have been made."""
        router = LLMRouter(config_path=_CONFIG_PATH)
        summary = router.get_usage_summary()
        assert summary["total_calls"] == 0
        assert summary["total_tokens"] == 0
        assert summary["total_cost"] == 0.0

    def test_call_uses_correct_model(self) -> None:
        """Verify the router passes the correct model to the provider."""
        mock = _mock_provider()

        with patch("packages.llm.router.get_provider", return_value=mock):
            router = LLMRouter(config_path=_CONFIG_PATH)
            router.call("planner", [{"role": "user", "content": "test"}])

        call_args = mock.complete.call_args
        assert call_args.kwargs.get("model") == "anthropic/claude-opus-4-6"

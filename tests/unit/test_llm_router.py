"""Unit tests for packages.llm.router.LLMRouter."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from packages.llm.router import LLMRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "model_routing.yaml"
)


def _build_mock_litellm() -> MagicMock:
    """Build a fake litellm module that returns canned completion responses."""
    mock = MagicMock()

    mock_choice = MagicMock()
    mock_choice.message.content = "mocked response"

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 50
    mock_usage.total_tokens = 150

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock.completion.return_value = mock_response
    mock.completion_cost.return_value = 0.003

    return mock


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestLoadConfig:
    """Tests for LLMRouter configuration loading."""

    def test_load_config(self) -> None:
        """Router loads model_routing.yaml and exposes routing entries."""
        with patch("packages.llm.router._get_litellm", return_value=_build_mock_litellm()):
            router = LLMRouter(config_path=_CONFIG_PATH)

        # The config should have a 'routing' key with known roles
        config = router._config
        assert "routing" in config
        assert "planner" in config["routing"]
        assert "worker" in config["routing"]
        assert "reviewer" in config["routing"]
        assert "lightweight" in config["routing"]

    def test_load_config_missing_file(self, tmp_path) -> None:
        """Router handles missing config gracefully with empty config."""
        with patch("packages.llm.router._get_litellm", return_value=_build_mock_litellm()):
            router = LLMRouter(config_path=str(tmp_path / "nonexistent.yaml"))

        assert router._config == {}


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

class TestResolveModel:
    """Tests for model resolution based on agent role."""

    @pytest.fixture(autouse=True)
    def _setup_router(self) -> None:
        with patch("packages.llm.router._get_litellm", return_value=_build_mock_litellm()):
            self.router = LLMRouter(config_path=_CONFIG_PATH)

    def test_resolve_model_planner(self) -> None:
        """Planner role resolves to anthropic/claude-opus-4-6."""
        primary, fallbacks = self.router._resolve_model("planner")
        assert primary == "anthropic/claude-opus-4-6"
        assert "openai/gpt-5.4-mini" in fallbacks

    def test_resolve_model_worker(self) -> None:
        """Worker role resolves to anthropic/claude-sonnet-4-6."""
        primary, fallbacks = self.router._resolve_model("worker")
        assert primary == "anthropic/claude-sonnet-4-6"
        assert "openai/gpt-5.4-mini" in fallbacks

    def test_resolve_model_lightweight(self) -> None:
        """Lightweight role resolves to openai/gpt-5.4-mini."""
        primary, fallbacks = self.router._resolve_model("lightweight")
        assert primary == "openai/gpt-5.4-mini"
        assert fallbacks == []  # lightweight has no fallback

    def test_resolve_model_unknown_role_uses_default(self) -> None:
        """An unknown role falls back to the default model (openai/gpt-5.4-mini)."""
        primary, fallbacks = self.router._resolve_model("unknown_role")
        assert primary == "openai/gpt-5.4-mini"  # default in _resolve_model
        assert fallbacks == []


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------

class TestGetUsageSummary:
    """Tests for LLMRouter.get_usage_summary."""

    def test_get_usage_summary(self) -> None:
        """Usage summary aggregates across calls."""
        mock_litellm = _build_mock_litellm()

        with patch("packages.llm.router._get_litellm", return_value=mock_litellm):
            router = LLMRouter(config_path=_CONFIG_PATH)

            # Make two calls to different roles
            router.call("planner", [{"role": "user", "content": "plan a task"}])
            router.call("worker", [{"role": "user", "content": "implement the plan"}])

        summary = router.get_usage_summary()

        assert summary["total_calls"] == 2
        assert summary["total_tokens"] == 300  # 150 per call * 2
        assert summary["total_cost"] == pytest.approx(0.006)
        assert "by_model" in summary

    def test_get_usage_summary_empty(self) -> None:
        """Usage summary is zeros when no calls have been made."""
        with patch("packages.llm.router._get_litellm", return_value=_build_mock_litellm()):
            router = LLMRouter(config_path=_CONFIG_PATH)

        summary = router.get_usage_summary()
        assert summary["total_calls"] == 0
        assert summary["total_tokens"] == 0
        assert summary["total_cost"] == 0.0

    def test_call_uses_correct_model(self) -> None:
        """Verify the router passes the correct model to litellm.completion."""
        mock_litellm = _build_mock_litellm()

        with patch("packages.llm.router._get_litellm", return_value=mock_litellm):
            router = LLMRouter(config_path=_CONFIG_PATH)
            router.call("planner", [{"role": "user", "content": "test"}])

        # Verify the completion was called with the planner model
        call_args = mock_litellm.completion.call_args
        assert call_args.kwargs.get("model") == "anthropic/claude-opus-4-6" or \
               call_args[1].get("model") == "anthropic/claude-opus-4-6" or \
               (len(call_args[0]) > 0 and call_args[0][0] == "anthropic/claude-opus-4-6") or \
               call_args.kwargs.get("model", call_args[1].get("model")) == "anthropic/claude-opus-4-6"

"""LLM provider registry — add new providers by dropping in a module."""

from __future__ import annotations

from typing import Any

from packages.llm.providers.base import LLMProvider

# ---------------------------------------------------------------------------
# Provider registry — maps prefix to provider class
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[LLMProvider]] = {}


def register_provider(prefix: str, cls: type[LLMProvider]) -> None:
    """Register a provider class for a model prefix (e.g. 'anthropic')."""
    _PROVIDERS[prefix] = cls


def get_provider(model: str) -> LLMProvider:
    """Return a provider instance for *model* (e.g. 'anthropic/claude-sonnet-4-6').

    Matches on the prefix before the first '/'.
    Falls back to 'openai' if no prefix match.
    """
    prefix = model.split("/")[0] if "/" in model else "openai"
    cls = _PROVIDERS.get(prefix)
    if cls is None:
        raise ValueError(
            f"No provider registered for prefix '{prefix}'. "
            f"Available: {list(_PROVIDERS.keys())}. "
            f"Add a provider module in packages/llm/providers/"
        )
    return cls()


def list_providers() -> list[str]:
    """Return registered provider prefixes."""
    return list(_PROVIDERS.keys())


# ---------------------------------------------------------------------------
# Auto-register built-in providers on import
# ---------------------------------------------------------------------------

def _auto_register() -> None:
    """Import built-in provider modules so they self-register."""
    # Each module calls register_provider() at import time
    try:
        from packages.llm.providers import anthropic_provider  # noqa: F401
    except ImportError:
        pass
    try:
        from packages.llm.providers import openai_provider  # noqa: F401
    except ImportError:
        pass
    try:
        from packages.llm.providers import google_provider  # noqa: F401
    except ImportError:
        pass
    try:
        from packages.llm.providers import openrouter_provider  # noqa: F401
    except ImportError:
        pass


_auto_register()

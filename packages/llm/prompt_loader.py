"""Load and compose agent prompts from the prompts/ directory."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PromptLoader:
    """Load role-based prompt components from the filesystem.

    Expected directory layout::

        {prompts_dir}/{role}/identity.md
        {prompts_dir}/{role}/policy.md
        {prompts_dir}/{role}/procedure.md
        {prompts_dir}/{role}/output_contract.json
    """

    def __init__(self, prompts_dir: str = "prompts") -> None:
        self._base = Path(prompts_dir).resolve()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, agent_role: str) -> dict[str, Any]:
        """Return all prompt components for *agent_role*.

        Returns a dict with keys ``identity``, ``policy``, ``procedure``,
        and ``output_contract``.  Missing files yield ``None``.
        """
        role_dir = self._base / agent_role

        identity = self._read_text(role_dir / "identity.md")
        policy = self._read_text(role_dir / "policy.md")
        procedure = self._read_text(role_dir / "procedure.md")
        output_contract = self._read_json(role_dir / "output_contract.json")

        return {
            "identity": identity,
            "policy": policy,
            "procedure": procedure,
            "output_contract": output_contract,
        }

    def compose_system_prompt(self, agent_role: str) -> str:
        """Combine identity + policy + procedure into a single system message.

        Sections are separated by markdown horizontal rules so the model
        can easily distinguish them.
        """
        parts = self.load(agent_role)
        sections: list[str] = []

        if parts["identity"]:
            sections.append(f"# Identity\n\n{parts['identity']}")
        if parts["policy"]:
            sections.append(f"# Policy\n\n{parts['policy']}")
        if parts["procedure"]:
            sections.append(f"# Procedure\n\n{parts['procedure']}")

        if not sections:
            logger.warning(
                "No prompt files found for role '%s' in %s",
                agent_role,
                self._base,
            )
            return f"You are an AI agent performing the role: {agent_role}."

        return "\n\n---\n\n".join(sections)

    def get_output_contract(self, agent_role: str) -> dict[str, Any]:
        """Return the parsed JSON schema for the role's expected output."""
        path = self._base / agent_role / "output_contract.json"
        contract = self._read_json(path)
        return contract if contract is not None else {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_text(path: Path) -> str | None:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8").strip() or None

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to parse %s: %s", path, exc)
            return None

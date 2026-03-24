"""Parser for AGENTS.md repository configuration files."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Section heading pattern: ## Section Name
_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)

# Mapping from normalised heading text to dict key
_SECTION_KEY_MAP: dict[str, str] = {
    "project": "project",
    "language": "language",
    "languages": "language",
    "build": "build_cmd",
    "build command": "build_cmd",
    "test": "test_cmd",
    "test command": "test_cmd",
    "lint": "lint_cmd",
    "lint command": "lint_cmd",
    "architecture": "architecture",
    "boundaries": "boundaries",
    "conventions": "conventions",
    "coding conventions": "conventions",
    "style": "conventions",
}


class AgentsMdParser:
    """Parse an ``AGENTS.md`` file from a repository root."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, repo_path: str) -> dict[str, Any]:
        """Read *repo_path*/AGENTS.md and return structured config.

        Returns a dict with keys:
            project, language, build_cmd, test_cmd, lint_cmd,
            architecture, boundaries, conventions

        Missing sections default to ``None``.
        """
        agents_file = Path(repo_path) / "AGENTS.md"
        if not agents_file.is_file():
            logger.info("No AGENTS.md found at %s", agents_file)
            return self._empty()

        text = agents_file.read_text(encoding="utf-8", errors="replace")
        return self._parse_text(text)

    def inject_context(self, task_state: dict[str, Any], repo_path: str) -> dict[str, Any]:
        """Parse AGENTS.md and merge the result into *task_state* under
        the ``repo_context`` key.  Returns the updated *task_state*.
        """
        parsed = self.parse(repo_path)
        task_state["repo_context"] = parsed
        return task_state

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "project": None,
            "language": None,
            "build_cmd": None,
            "test_cmd": None,
            "lint_cmd": None,
            "architecture": None,
            "boundaries": None,
            "conventions": None,
        }

    def _parse_text(self, text: str) -> dict[str, Any]:
        result = self._empty()

        # Split into (heading, body) pairs
        sections = self._split_sections(text)

        for heading, body in sections:
            key = self._normalise_heading(heading)
            mapped = _SECTION_KEY_MAP.get(key)
            if mapped is None:
                logger.debug("Ignoring unknown AGENTS.md section: %s", heading)
                continue

            body_stripped = body.strip()

            # For command sections, try to extract a single-line command
            if mapped.endswith("_cmd"):
                result[mapped] = self._extract_command(body_stripped)
            elif mapped in ("boundaries", "conventions"):
                # Store as list of bullet points
                result[mapped] = self._extract_bullets(body_stripped)
            else:
                result[mapped] = body_stripped if body_stripped else None

        return result

    @staticmethod
    def _split_sections(text: str) -> list[tuple[str, str]]:
        """Return list of ``(heading_text, body_text)`` pairs."""
        headings = list(_HEADING_RE.finditer(text))
        if not headings:
            return []

        sections: list[tuple[str, str]] = []
        for i, match in enumerate(headings):
            heading_text = match.group(1).strip()
            body_start = match.end()
            body_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            body = text[body_start:body_end]
            sections.append((heading_text, body))
        return sections

    @staticmethod
    def _normalise_heading(heading: str) -> str:
        return heading.lower().strip()

    @staticmethod
    def _extract_command(body: str) -> str | None:
        """Try to pull a code-fenced command, falling back to the first non-empty line."""
        # Look for ```...``` fenced block
        fence_match = re.search(r"```[^\n]*\n(.+?)```", body, re.DOTALL)
        if fence_match:
            return fence_match.group(1).strip()
        # Fall back to first non-empty line
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped
        return None

    @staticmethod
    def _extract_bullets(body: str) -> list[str]:
        """Extract markdown bullet points from *body*."""
        bullets: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith(("- ", "* ", "+ ")):
                bullets.append(stripped.lstrip("-*+ ").strip())
        return bullets if bullets else [body] if body else []

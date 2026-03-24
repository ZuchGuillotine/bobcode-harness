"""Adapter wrapping the codegraph CLI/MCP for repository intelligence."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class CodegraphAdapter:
    """Wraps the codegraph CLI to provide symbol-level repo intelligence."""

    def __init__(self, codegraph_bin: str = "codegraph") -> None:
        self._bin = codegraph_bin
        self._available: bool | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_available(self) -> bool:
        """Check whether the codegraph binary is on $PATH."""
        if self._available is None:
            self._available = shutil.which(self._bin) is not None
            if not self._available:
                logger.warning(
                    "codegraph CLI not found on PATH. "
                    "Repo-intel features will return empty results."
                )
        return self._available

    def _run(self, *args: str, timeout: int = 60) -> dict[str, Any]:
        """Run a codegraph sub-command, parse JSON stdout, return dict.

        Returns an empty dict (and logs a warning) when codegraph is
        missing or the command fails.
        """
        if not self._is_available():
            return {}

        cmd = [self._bin, *args, "--json"]
        logger.debug("Running: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "codegraph %s exited %d: %s",
                    args[0] if args else "?",
                    result.returncode,
                    result.stderr.strip(),
                )
                return {}
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except subprocess.TimeoutExpired:
            logger.error("codegraph timed out after %ds", timeout)
            return {}
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse codegraph JSON output: %s", exc)
            return {}
        except FileNotFoundError:
            self._available = False
            logger.warning("codegraph binary disappeared from PATH")
            return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def locate_symbol(self, symbol: str) -> dict[str, Any]:
        """Return ``{file, line, kind}`` for *symbol*.

        Example return::

            {"file": "src/foo.py", "line": 42, "kind": "function"}
        """
        raw = self._run("locate", symbol)
        return {
            "file": raw.get("file", ""),
            "line": raw.get("line", 0),
            "kind": raw.get("kind", "unknown"),
        }

    def get_context(self, symbol: str, depth: int = 2) -> dict[str, Any]:
        """Return callers, callees, and imports for *symbol*.

        Example return::

            {"callers": [...], "callees": [...], "imports": [...]}
        """
        raw = self._run("context", symbol, "--depth", str(depth))
        return {
            "callers": raw.get("callers", []),
            "callees": raw.get("callees", []),
            "imports": raw.get("imports", []),
        }

    def get_impact(self, diff_path: str) -> dict[str, Any]:
        """Analyse a diff/patch file and return blast-radius info.

        Example return::

            {"affected_symbols": [...], "affected_tests": [...], "blast_radius": 12}
        """
        raw = self._run("impact", diff_path)
        return {
            "affected_symbols": raw.get("affected_symbols", []),
            "affected_tests": raw.get("affected_tests", []),
            "blast_radius": raw.get("blast_radius", 0),
        }

    def get_cochange(self, symbol: str) -> list[dict[str, Any]]:
        """Return symbols that historically co-change with *symbol*.

        Each entry is a dict like ``{"symbol": "...", "frequency": 5}``.
        """
        raw = self._run("cochange", symbol)
        return raw.get("cochanges", [])

    def get_boundary_violations(self, diff_path: str) -> list[dict[str, Any]]:
        """Check a diff for architectural boundary violations.

        Each entry is a dict like::

            {"source": "...", "target": "...", "rule": "..."}
        """
        raw = self._run("boundaries", "--diff", diff_path)
        return raw.get("violations", [])

    def get_candidate_tests(self, symbols: list[str]) -> list[str]:
        """Return test file/function identifiers relevant to *symbols*."""
        raw = self._run("tests", *symbols)
        return raw.get("tests", [])

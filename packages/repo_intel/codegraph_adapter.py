"""Adapter wrapping the optave/codegraph CLI for repository intelligence."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


class CodegraphAdapter:
    """Wraps the optave codegraph CLI (v3.x) for symbol-level repo intelligence.

    All queries are local SQLite lookups — zero API calls, zero tokens.
    Requires ``codegraph build`` to have been run in the target repo.
    """

    def __init__(self, codegraph_bin: str = "codegraph", repo_path: str = ".") -> None:
        self._bin = codegraph_bin
        self._repo_path = repo_path
        self._available: bool | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_available(self) -> bool:
        if self._available is None:
            self._available = shutil.which(self._bin) is not None
            if not self._available:
                logger.warning(
                    "codegraph CLI not found on PATH. "
                    "Repo-intel features will return empty results."
                )
        return self._available

    def _run(self, *args: str, timeout: int = 30) -> dict[str, Any] | list[Any]:
        """Run a codegraph sub-command with --json, return parsed output."""
        if not self._is_available():
            return {}

        cmd = [self._bin, *args, "--json"]
        logger.debug("Running: %s (cwd=%s)", " ".join(cmd), self._repo_path)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._repo_path,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "codegraph %s exited %d: %s",
                    args[0] if args else "?",
                    result.returncode,
                    result.stderr.strip()[:200],
                )
                return {}

            stdout = result.stdout.strip()
            if not stdout:
                return {}
            return json.loads(stdout)
        except subprocess.TimeoutExpired:
            logger.error("codegraph timed out after %ds", timeout)
            return {}
        except json.JSONDecodeError:
            # Some commands return non-JSON text; return as raw string
            logger.debug("codegraph output not JSON, returning raw")
            return {"raw": result.stdout.strip()[:2000]}
        except FileNotFoundError:
            self._available = False
            logger.warning("codegraph binary disappeared from PATH")
            return {}

    def _run_text(self, *args: str, timeout: int = 30) -> str:
        """Run a codegraph sub-command and return raw text output."""
        if not self._is_available():
            return ""

        cmd = [self._bin, *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._repo_path,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Public API — mapped to optave codegraph v3.x commands
    # ------------------------------------------------------------------

    def locate_symbol(self, symbol: str) -> dict[str, Any]:
        """Find where a symbol is defined and used.

        Maps to: ``codegraph where <name> --json``
        """
        raw = self._run("where", symbol)
        if isinstance(raw, dict) and raw.get("raw"):
            return {"symbol": symbol, "locations": [], "raw": raw["raw"]}
        if isinstance(raw, list) and raw:
            first = raw[0] if raw else {}
            return {
                "file": first.get("file", ""),
                "line": first.get("line", 0),
                "kind": first.get("kind", "unknown"),
                "symbol": symbol,
                "locations": raw,
            }
        if isinstance(raw, dict):
            results = raw.get("results", raw.get("definitions", []))
            first = results[0] if results else {}
            return {
                "file": first.get("file", raw.get("file", "")),
                "line": first.get("line", raw.get("line", 0)),
                "kind": first.get("kind", raw.get("kind", "unknown")),
                "symbol": symbol,
                "locations": results or [raw] if raw.get("file") else [],
            }
        return {"symbol": symbol, "file": "", "line": 0, "kind": "unknown", "locations": []}

    def get_context(self, symbol: str, depth: int = 2) -> dict[str, Any]:
        """Full context for a function: source, deps, callers, tests.

        Maps to: ``codegraph context <name> --json``
        """
        raw = self._run("context", symbol)
        if isinstance(raw, dict):
            return {
                "symbol": symbol,
                "callers": raw.get("callers", []),
                "callees": raw.get("callees", raw.get("deps", [])),
                "source": raw.get("source", ""),
                "file": raw.get("file", ""),
                "tests": raw.get("tests", []),
            }
        return {"symbol": symbol, "callers": [], "callees": [], "source": "", "file": ""}

    def get_impact(self, target: str) -> dict[str, Any]:
        """Function-level or file-level impact analysis.

        Maps to: ``codegraph fn-impact <name> --json`` for symbols,
        or ``codegraph impact <file> --json`` for files.
        """
        # Try fn-impact first (function level), fall back to file impact
        if "." in target and "/" in target:
            # Looks like a file path
            raw = self._run("impact", target)
        else:
            raw = self._run("fn-impact", target)

        if isinstance(raw, dict):
            results = raw.get("results", [])
            return {
                "target": target,
                "affected_symbols": [r.get("name", "") for r in results] if results else [],
                "total_dependents": raw.get("totalDependents", len(results)),
                "results": results,
            }
        return {"target": target, "affected_symbols": [], "total_dependents": 0}

    def get_cochange(self, file_path: str) -> list[dict[str, Any]]:
        """Files that historically change together.

        Maps to: ``codegraph co-change <file> --json``
        """
        raw = self._run("co-change", file_path)
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            return raw.get("results", raw.get("pairs", []))
        return []

    def get_boundary_violations(self, diff_path: str) -> list[dict[str, Any]]:
        """Check for architectural boundary violations via diff impact.

        Maps to: ``codegraph diff-impact --json``
        """
        raw = self._run("diff-impact")
        if isinstance(raw, dict):
            return raw.get("violations", raw.get("changes", []))
        if isinstance(raw, list):
            return raw
        return []

    def get_candidate_tests(self, symbols: list[str]) -> list[str]:
        """Find tests related to given symbols via context queries."""
        tests: list[str] = []
        for symbol in symbols[:5]:  # Limit to avoid slowness
            ctx = self.get_context(symbol)
            tests.extend(ctx.get("tests", []))
        return list(set(tests))

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Semantic search: find functions by natural language description.

        Maps to: ``codegraph search "<query>" --json``
        """
        raw = self._run("search", query)
        if isinstance(raw, list):
            return raw[:limit]
        if isinstance(raw, dict):
            return raw.get("results", [])[:limit]
        return []

    def get_complexity(self, target: str | None = None) -> list[dict[str, Any]]:
        """Per-function complexity metrics.

        Maps to: ``codegraph complexity [target] --json``
        """
        args = ["complexity"]
        if target:
            args.append(target)
        raw = self._run(*args)
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            return raw.get("functions", raw.get("results", []))
        return []

    def get_stats(self) -> dict[str, Any]:
        """Graph health overview.

        Maps to: ``codegraph stats --json``
        """
        raw = self._run("stats")
        return raw if isinstance(raw, dict) else {}

    def get_deps(self, file_path: str) -> dict[str, Any]:
        """File-level dependency info: imports and importers.

        Maps to: ``codegraph deps <file> --json``
        """
        raw = self._run("deps", file_path)
        return raw if isinstance(raw, dict) else {"imports": [], "importers": []}

    def get_dataflow(self, symbol: str) -> dict[str, Any]:
        """Data flow analysis for a function.

        Maps to: ``codegraph dataflow <name> --json``
        """
        raw = self._run("dataflow", symbol)
        return raw if isinstance(raw, dict) else {}

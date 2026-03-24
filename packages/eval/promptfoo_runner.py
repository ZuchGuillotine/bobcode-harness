"""PromptfooRunner — wrapper around the `npx promptfoo` CLI for running eval suites."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PromptfooRunnerError(Exception):
    """Raised when a promptfoo invocation fails."""


class PromptfooRunner:
    """Wraps the ``npx promptfoo`` CLI to run eval suites programmatically.

    Parameters
    ----------
    config_dir:
        Root directory containing promptfoo YAML configs (e.g. ``evals/``).
    output_dir:
        Directory for writing eval result JSON files.
    timeout_seconds:
        Maximum wall-clock time for a single ``promptfoo eval`` invocation.
    """

    def __init__(
        self,
        config_dir: str | None = None,
        output_dir: str | None = None,
        timeout_seconds: int | None = None,
        project_name: str | None = None,
        repo_path: str | None = None,
    ) -> None:
        from packages.config import get_harness_root, get_project_paths, load_eval_config

        promptfoo_cfg = load_eval_config().get("eval", {}).get("promptfoo", {})
        harness_root = get_harness_root()
        project_paths = get_project_paths(project_name=project_name, repo_path=repo_path)

        config_value = config_dir or promptfoo_cfg.get("config_dir") or "evals"
        output_value = output_dir or promptfoo_cfg.get("output_dir")

        self._config_dir = self._resolve_path(str(config_value), harness_root)
        self._output_dir = self._resolve_output_dir(
            output_value,
            project_paths.eval_output_dir,
            harness_root,
        )
        self._output_dir.mkdir(parents=True, exist_ok=True)
        configured_timeout = promptfoo_cfg.get("timeout_seconds")
        self._timeout = timeout_seconds or int(configured_timeout or 120)
        self._npx_path = self._resolve_npx()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_path(value: str, base: Path) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (base / path).resolve()

    @classmethod
    def _resolve_output_dir(
        cls,
        configured_output: str | None,
        project_output_dir: Path,
        harness_root: Path,
    ) -> Path:
        if not configured_output:
            return project_output_dir

        normalized = configured_output.strip().rstrip("/")
        if normalized in {".harness/eval_outputs", "./.harness/eval_outputs"}:
            logger.info(
                "Ignoring legacy promptfoo output_dir=%s; using project eval output dir %s",
                configured_output,
                project_output_dir,
            )
            return project_output_dir

        return cls._resolve_path(configured_output, harness_root)

    @staticmethod
    def _resolve_npx() -> str | None:
        """Return the path to ``npx`` or None if not found."""
        return shutil.which("npx")

    def _ensure_npx(self) -> str:
        """Raise a clear error if npx is not available."""
        if self._npx_path is None:
            raise PromptfooRunnerError(
                "npx is not installed or not on PATH. "
                "Install Node.js (https://nodejs.org) and ensure npx is available, "
                "then run: npm install -g promptfoo"
            )
        return self._npx_path

    def _run_command(self, args: list[str], output_path: Path | None = None) -> str:
        """Execute a promptfoo CLI command via subprocess.

        Returns the raw stdout.
        """
        npx = self._ensure_npx()

        cmd = [npx, "promptfoo"] + args
        if output_path is not None:
            cmd.extend(["-o", str(output_path), "--output-format", "json"])

        logger.info("Running: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=str(self._config_dir.parent) if self._config_dir.parent != Path(".") else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise PromptfooRunnerError(
                f"promptfoo command timed out after {self._timeout}s: {' '.join(cmd)}"
            ) from exc
        except FileNotFoundError as exc:
            raise PromptfooRunnerError(
                f"Failed to execute npx. Is Node.js installed? Error: {exc}"
            ) from exc

        if result.returncode != 0:
            stderr_snippet = (result.stderr or "")[:500]
            logger.warning(
                "promptfoo exited with code %d: %s", result.returncode, stderr_snippet
            )
            # promptfoo may still produce useful output on non-zero exit
            # (e.g. some tests failed) so we don't raise here unconditionally.

        return result.stdout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_suite(self, suite_name: str, output_format: str = "json") -> dict[str, Any]:
        """Run a promptfoo eval suite.

        Parameters
        ----------
        suite_name:
            Name or relative path of the YAML config inside *config_dir*.
            Examples: ``regressions/test_review_diff.yaml``,
            ``adversarial/red_team.yaml``.
        output_format:
            Desired output format (``json`` or ``html``).  Defaults to ``json``.

        Returns
        -------
        dict
            Parsed JSON results from promptfoo.
        """
        config_path = self._config_dir / suite_name
        if not config_path.is_file():
            raise PromptfooRunnerError(
                f"Suite config not found: {config_path}. "
                f"Available suites: {self.list_suites()}"
            )

        output_file = self._output_dir / f"{Path(suite_name).stem}_results.json"

        self._run_command(
            ["eval", "-c", str(config_path)],
            output_path=output_file,
        )

        return self.get_results(str(output_file))

    def run_regression(self, skill_id: str) -> dict[str, Any]:
        """Run the regression suite for a specific skill.

        Maps *skill_id* to a YAML file under ``<config_dir>/regressions/``.
        Convention: ``skill_id`` like ``review_diff`` maps to
        ``regressions/test_review_diff.yaml``.
        """
        # Normalise skill_id to a filename
        clean_name = skill_id.replace("-", "_").replace(" ", "_").lower()
        # Try common naming patterns
        candidates = [
            f"regressions/test_{clean_name}.yaml",
            f"regressions/{clean_name}.yaml",
            f"regressions/test_{clean_name}.yml",
            f"regressions/{clean_name}.yml",
        ]

        for candidate in candidates:
            config_path = self._config_dir / candidate
            if config_path.is_file():
                return self.run_suite(candidate)

        raise PromptfooRunnerError(
            f"No regression config found for skill '{skill_id}'. "
            f"Searched: {candidates}. Available suites: {self.list_suites()}"
        )

    def run_red_team(self) -> dict[str, Any]:
        """Run the adversarial red-team evaluation suite."""
        red_team_path = "adversarial/red_team.yaml"
        return self.run_suite(red_team_path)

    def get_results(self, output_path: str) -> dict[str, Any]:
        """Parse a promptfoo JSON output file.

        Returns
        -------
        dict
            The parsed results.  Returns a dict with an ``error`` key if the
            file is missing or unparseable.
        """
        path = Path(output_path)
        if not path.is_file():
            return {
                "error": f"Output file not found: {output_path}",
                "results": [],
                "stats": {},
            }

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            # promptfoo sometimes emits a top-level list
            return {"results": data}
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse promptfoo output %s: %s", output_path, exc)
            return {
                "error": f"JSON parse error: {exc}",
                "raw_output_path": output_path,
                "results": [],
            }

    def list_suites(self) -> list[str]:
        """List available YAML eval configs under *config_dir*.

        Returns paths relative to *config_dir*.
        """
        if not self._config_dir.is_dir():
            logger.warning("Config directory does not exist: %s", self._config_dir)
            return []

        suites: list[str] = []
        for ext in ("*.yaml", "*.yml"):
            for path in sorted(self._config_dir.rglob(ext)):
                suites.append(str(path.relative_to(self._config_dir)))

        return suites

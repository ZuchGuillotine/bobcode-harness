"""Helpers for provisioning and tracking codegraph builds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess


@dataclass(frozen=True)
class CodegraphBuildResult:
    """Result of a codegraph build attempt."""

    available: bool
    success: bool
    repo_path: Path
    artifact_path: Path
    message: str


def codegraph_artifact_path(repo_path: str | Path) -> Path:
    """Return the expected repo-local codegraph SQLite path."""
    repo = Path(repo_path).expanduser().resolve()
    return repo / ".codegraph" / "graph.db"


def build_codegraph(repo_path: str | Path, timeout_seconds: int = 120) -> CodegraphBuildResult:
    """Run ``codegraph build`` for a repository."""
    repo = Path(repo_path).expanduser().resolve()
    artifact_path = codegraph_artifact_path(repo)

    if shutil.which("codegraph") is None:
        return CodegraphBuildResult(
            available=False,
            success=False,
            repo_path=repo,
            artifact_path=artifact_path,
            message="codegraph CLI not found — install with: npm install -g @optave/codegraph",
        )

    try:
        result = subprocess.run(
            ["codegraph", "build"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CodegraphBuildResult(
            available=True,
            success=False,
            repo_path=repo,
            artifact_path=artifact_path,
            message=f"Codegraph build timed out after {timeout_seconds}s",
        )

    if result.returncode == 0:
        message = _summarize_success(result.stdout, result.stderr)
        return CodegraphBuildResult(
            available=True,
            success=True,
            repo_path=repo,
            artifact_path=artifact_path,
            message=message,
        )

    stderr_snippet = (result.stderr or result.stdout or "").strip()[:300]
    message = stderr_snippet or f"codegraph build failed with exit code {result.returncode}"
    return CodegraphBuildResult(
        available=True,
        success=False,
        repo_path=repo,
        artifact_path=artifact_path,
        message=message,
    )


def _summarize_success(stdout: str, stderr: str) -> str:
    for line in (stderr.splitlines() + stdout.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if "Graph built" in stripped or "nodes" in stripped:
            return stripped
    return "Codegraph built successfully"

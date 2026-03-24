"""Centralised runtime path and project resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Iterator

import yaml


def get_harness_root() -> Path:
    """Return the harness installation root."""
    root = os.environ.get("HARNESS_HOME")
    if root:
        return Path(root).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _resolve_path(value: str | None, base: Path) -> Path:
    if not value:
        return base
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def get_config_dir() -> Path:
    """Return the active config directory."""
    root = get_harness_root()
    env_value = os.environ.get("HARNESS_CONFIG")
    if env_value:
        return _resolve_path(env_value, root)
    return root / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_harness_config() -> dict[str, Any]:
    """Load the top-level harness config."""
    return _load_yaml(get_config_dir() / "harness.yaml")


def load_eval_config() -> dict[str, Any]:
    """Load the eval configuration."""
    return _load_yaml(get_config_dir() / "eval_config.yaml")


def get_data_dir() -> Path:
    """Return the active data directory."""
    root = get_harness_root()
    env_value = os.environ.get("HARNESS_DATA")
    if env_value:
        return _resolve_path(env_value, root)

    cfg = load_harness_config()
    configured = cfg.get("harness", {}).get("data_dir")
    return _resolve_path(configured, root / "data")


def get_community_dir() -> Path:
    """Return the harness-level community feedback directory."""
    return get_data_dir() / "community"


def _projects_config_dir() -> Path:
    return get_config_dir() / "projects"


def _load_project_file(project_name: str) -> dict[str, Any]:
    return _load_yaml(_projects_config_dir() / f"{project_name}.yaml")


def iter_registered_projects() -> Iterator[tuple[str, Path]]:
    """Yield registered projects as ``(name, repo_path)`` pairs."""
    seen: set[str] = set()
    projects_dir = _projects_config_dir()

    if projects_dir.is_dir():
        for path in sorted(projects_dir.glob("*.yaml")):
            cfg = _load_yaml(path)
            project = cfg.get("project", {})
            name = project.get("name") or path.stem
            repo_path = project.get("repo_path")
            if name and repo_path:
                seen.add(name)
                yield name, Path(repo_path).expanduser().resolve()

    harness_projects = load_harness_config().get("projects", {})
    if isinstance(harness_projects, dict):
        for name, repo_path in sorted(harness_projects.items()):
            if name in seen or not repo_path:
                continue
            yield name, Path(str(repo_path)).expanduser().resolve()


@dataclass(frozen=True)
class ProjectPaths:
    project_name: str | None
    repo_path: Path | None
    project_dir: Path
    tasks_dir: Path
    db_path: Path
    counter_file: Path
    learning_dir: Path
    skills_dir: Path
    worktree_base: Path
    eval_output_dir: Path
    legacy_mode: bool = False

    def ensure_dirs(self) -> None:
        """Create the standard directory tree for the project."""
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.worktree_base.mkdir(parents=True, exist_ok=True)
        self.eval_output_dir.mkdir(parents=True, exist_ok=True)


def get_project_paths(
    project_name: str | None = None,
    repo_path: str | None = None,
) -> ProjectPaths:
    """Resolve the runtime paths for a registered project or legacy mode."""
    data_dir = get_data_dir()

    if project_name:
        registered = dict(iter_registered_projects())
        if project_name not in registered:
            raise ValueError(f"Unknown project: {project_name}")
        repo = registered[project_name]
        project_dir = data_dir / "projects" / project_name
        return ProjectPaths(
            project_name=project_name,
            repo_path=repo,
            project_dir=project_dir,
            tasks_dir=project_dir / "tasks",
            db_path=project_dir / "sqlite" / "harness.db",
            counter_file=project_dir / ".task_counter",
            learning_dir=project_dir / "learning",
            skills_dir=project_dir / "skills",
            worktree_base=project_dir / "worktrees",
            eval_output_dir=project_dir / "eval_outputs",
            legacy_mode=False,
        )

    resolved_repo = repo_path or os.environ.get("HARNESS_REPO_PATH")
    if resolved_repo:
        repo = Path(resolved_repo).expanduser().resolve()
        inferred_name = repo.name
        project_dir = data_dir / "projects" / inferred_name
        return ProjectPaths(
            project_name=inferred_name,
            repo_path=repo,
            project_dir=project_dir,
            tasks_dir=project_dir / "tasks",
            db_path=project_dir / "sqlite" / "harness.db",
            counter_file=project_dir / ".task_counter",
            learning_dir=project_dir / "learning",
            skills_dir=project_dir / "skills",
            worktree_base=project_dir / "worktrees",
            eval_output_dir=project_dir / "eval_outputs",
            legacy_mode=False,
        )

    legacy_dir = get_harness_root() / ".harness"
    return ProjectPaths(
        project_name=None,
        repo_path=None,
        project_dir=legacy_dir,
        tasks_dir=legacy_dir / "tasks",
        db_path=legacy_dir / "harness.db",
        counter_file=legacy_dir / ".task_counter",
        learning_dir=legacy_dir / "learning",
        skills_dir=legacy_dir / "skills",
        worktree_base=legacy_dir / "worktrees",
        eval_output_dir=legacy_dir / "eval_outputs",
        legacy_mode=True,
    )


def find_task_dir(task_id: str, project_name: str | None = None) -> tuple[str | None, Path] | None:
    """Locate a task directory across registered projects or legacy mode."""
    search: list[tuple[str | None, ProjectPaths]] = []

    if project_name:
        paths = get_project_paths(project_name=project_name)
        search.append((project_name, paths))
    else:
        for name, _repo in iter_registered_projects():
            search.append((name, get_project_paths(project_name=name)))
        search.append((None, get_project_paths()))

    for name, paths in search:
        task_dir = paths.tasks_dir / task_id
        if task_dir.is_dir():
            return name, task_dir

    return None

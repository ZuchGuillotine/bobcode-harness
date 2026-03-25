"""Unit tests for harness-level learning feedback helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.eval.promptfoo_runner import PromptfooRunner
from packages.learning.community_feedback import append_feedback_event, build_feedback_event


def test_promptfoo_runner_defaults_to_project_eval_output_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    projects_dir = harness_root / "config" / "projects"
    projects_dir.mkdir(parents=True)
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    (harness_root / "config" / "harness.yaml").write_text(
        "harness:\n  data_dir: data\n",
        encoding="utf-8",
    )
    (harness_root / "config" / "eval_config.yaml").write_text(
        "eval:\n  promptfoo:\n    config_dir: evals\n    timeout_seconds: 90\n",
        encoding="utf-8",
    )
    (projects_dir / "demo.yaml").write_text(
        f"project:\n  name: demo\n  repo_path: {repo_path}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    runner = PromptfooRunner(project_name="demo")

    assert runner._config_dir == harness_root / "evals"
    assert runner._output_dir == harness_root / "data" / "projects" / "demo" / "eval_outputs"
    assert runner._timeout == 90


def test_promptfoo_runner_ignores_legacy_repo_local_output_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    (harness_root / "config").mkdir(parents=True)
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    (harness_root / "config" / "harness.yaml").write_text(
        "harness:\n  data_dir: data\n",
        encoding="utf-8",
    )
    (harness_root / "config" / "eval_config.yaml").write_text(
        "eval:\n  promptfoo:\n    config_dir: evals\n    output_dir: .harness/eval_outputs\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    runner = PromptfooRunner(repo_path=str(repo_path))

    assert runner._output_dir == harness_root / "data" / "projects" / "demo-repo" / "eval_outputs"


def test_promptfoo_runner_resolves_marketing_suite_by_skill_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    (harness_root / "config").mkdir(parents=True)
    (harness_root / "evals" / "marketing").mkdir(parents=True)
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    (harness_root / "config" / "harness.yaml").write_text(
        "harness:\n  data_dir: data\n",
        encoding="utf-8",
    )
    (harness_root / "config" / "eval_config.yaml").write_text(
        "eval:\n  promptfoo:\n    config_dir: evals\n",
        encoding="utf-8",
    )
    (harness_root / "evals" / "marketing" / "test_seo_content.yaml").write_text(
        "description: test\nprompts: ['x']\nproviders: []\ntests: []\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    runner = PromptfooRunner(repo_path=str(repo_path))

    called: dict[str, str] = {}

    def fake_run_suite(suite_name: str, output_format: str = "json") -> dict[str, str]:
        called["suite_name"] = suite_name
        called["output_format"] = output_format
        return {"suite_name": suite_name}

    monkeypatch.setattr(runner, "run_suite", fake_run_suite)

    result = runner.run_regression("seo_content")

    assert result["suite_name"] == "marketing/test_seo_content.yaml"
    assert called["suite_name"] == "marketing/test_seo_content.yaml"


def test_build_feedback_event_excludes_repo_specific_fields() -> None:
    state = {
        "task_type": "code_change",
        "project_name": "secret-project",
        "repo_path": "/private/repo",
        "plan": {
            "selected_skill": "safe_refactor",
            "confidence": 0.42,
            "estimated_budget_tokens": 1200,
        },
        "retries": 1,
        "max_retries": 3,
    }
    eval_results = {
        "tests_passed": False,
        "local_issues": [
            {
                "severity": "critical",
                "check": "out_of_scope_change",
                "path": "src/private.py",
            }
        ],
        "deterministic_verdict": {"passed": False},
        "review_verdict": {"verdict": "rejected", "confidence": 0.2},
    }

    event = build_feedback_event(state, eval_results, "retry")

    assert "project_name" not in event
    assert "repo_path" not in event
    assert event["failure_class"] == "boundary_violation"
    assert event["local_issue_checks"] == ["out_of_scope_change"]
    assert event["critical_issue_count"] == 1


def test_append_feedback_event_writes_jsonl(tmp_path: Path) -> None:
    output_dir = tmp_path / "community"

    output_path = append_feedback_event({"task_type": "code_change"}, output_dir=output_dir)

    assert output_path == output_dir / "feedback_events.jsonl"
    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["task_type"] == "code_change"

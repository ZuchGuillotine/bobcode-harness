"""Unit tests for community feedback consent and export helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.learning.community_exchange import (
    build_feedback_export,
    summarize_feedback_status,
    write_feedback_export,
)


def test_feedback_status_counts_pending_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    community_dir = harness_root / "data" / "community"
    community_dir.mkdir(parents=True)
    (harness_root / "config").mkdir(parents=True)
    (harness_root / "config" / "harness.yaml").write_text(
        "\n".join([
            "harness:",
            "  data_dir: data",
            "community_feedback:",
            "  consent: anonymized_export",
        ]) + "\n",
        encoding="utf-8",
    )
    (community_dir / "feedback_events.jsonl").write_text(
        '{"task_type":"code_change"}\n{"task_type":"marketing_campaign"}\n',
        encoding="utf-8",
    )
    (community_dir / "export_state.json").write_text(
        '{"last_exported_line": 1, "last_exported_at": "2026-03-24T00:00:00+00:00"}',
        encoding="utf-8",
    )

    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    status = summarize_feedback_status()

    assert status["consent"] == "anonymized_export"
    assert status["total_events"] == 2
    assert status["pending_events"] == 1


def test_build_feedback_export_uses_only_pending_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    community_dir = harness_root / "data" / "community"
    community_dir.mkdir(parents=True)
    (harness_root / "config").mkdir(parents=True)
    (harness_root / "config" / "harness.yaml").write_text(
        "\n".join([
            "harness:",
            "  data_dir: data",
            "community_feedback:",
            "  consent: anonymized_export",
        ]) + "\n",
        encoding="utf-8",
    )
    (community_dir / "feedback_events.jsonl").write_text(
        '{"task_type":"code_change"}\n{"task_type":"marketing_campaign"}\n',
        encoding="utf-8",
    )
    (community_dir / "export_state.json").write_text(
        '{"last_exported_line": 1, "last_exported_at": null}',
        encoding="utf-8",
    )

    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    bundle = build_feedback_export()

    assert bundle["event_count"] == 1
    assert bundle["line_range"] == [2, 2]
    assert bundle["events"][0]["task_type"] == "marketing_campaign"


def test_write_feedback_export_updates_export_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_root = tmp_path / "harness"
    (harness_root / "config").mkdir(parents=True)
    (harness_root / "config" / "harness.yaml").write_text(
        "\n".join([
            "harness:",
            "  data_dir: data",
            "community_feedback:",
            "  consent: anonymized_export",
        ]) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HARNESS_HOME", str(harness_root))

    bundle = {
        "generated_at": "2026-03-24T10:00:00+00:00",
        "line_range": [1, 2],
        "event_count": 2,
        "events": [{"task_type": "code_change"}],
    }
    output_path = write_feedback_export(bundle)

    assert output_path.is_file()
    exported = json.loads(output_path.read_text(encoding="utf-8"))
    assert exported["event_count"] == 2

    state_path = harness_root / "data" / "community" / "export_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["last_exported_line"] == 2
    assert state["last_exported_at"] == "2026-03-24T10:00:00+00:00"


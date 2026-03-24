"""Consent and export helpers for harness community feedback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from packages.config import get_community_dir, get_harness_root, load_harness_config

_SUPPORTED_CONSENT = {"local_only", "anonymized_export"}


@dataclass(frozen=True)
class CommunityFeedbackSettings:
    """Resolved community feedback configuration."""

    consent: str
    export_dir: Path
    state_file: Path
    updated_at: str | None = None
    updated_by: str | None = None

    @property
    def export_enabled(self) -> bool:
        return self.consent == "anonymized_export"


def get_feedback_log_path() -> Path:
    """Return the harness-local feedback event log path."""
    return get_community_dir() / "feedback_events.jsonl"


def get_feedback_settings(config: dict[str, Any] | None = None) -> CommunityFeedbackSettings:
    """Resolve community feedback settings from harness config."""
    cfg = config or load_harness_config()
    feedback_cfg = cfg.get("community_feedback", {})
    community_dir = get_community_dir()

    consent = str(feedback_cfg.get("consent", "local_only"))
    if consent not in _SUPPORTED_CONSENT:
        consent = "local_only"

    return CommunityFeedbackSettings(
        consent=consent,
        export_dir=_resolve_path(feedback_cfg.get("export_dir"), community_dir / "exports"),
        state_file=_resolve_path(feedback_cfg.get("state_file"), community_dir / "export_state.json"),
        updated_at=feedback_cfg.get("updated_at"),
        updated_by=feedback_cfg.get("updated_by"),
    )


def load_feedback_events(log_path: Path | None = None) -> list[dict[str, Any]]:
    """Load feedback events from the JSONL log."""
    path = log_path or get_feedback_log_path()
    if not path.is_file():
        return []

    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        events.append(json.loads(stripped))
    return events


def load_export_state(state_file: Path) -> dict[str, Any]:
    """Load export progress state."""
    if not state_file.is_file():
        return {
            "last_exported_line": 0,
            "last_exported_at": None,
        }
    return json.loads(state_file.read_text(encoding="utf-8"))


def save_export_state(state_file: Path, state: dict[str, Any]) -> None:
    """Persist export progress state."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def summarize_feedback_status() -> dict[str, Any]:
    """Return current feedback consent and export counters."""
    settings = get_feedback_settings()
    events = load_feedback_events()
    state = load_export_state(settings.state_file)
    total = len(events)
    exported = min(int(state.get("last_exported_line", 0) or 0), total)
    pending = max(total - exported, 0)
    return {
        "consent": settings.consent,
        "export_enabled": settings.export_enabled,
        "total_events": total,
        "pending_events": pending,
        "exported_events": exported,
        "log_path": str(get_feedback_log_path()),
        "export_dir": str(settings.export_dir),
        "state_file": str(settings.state_file),
        "consent_updated_at": settings.updated_at,
        "consent_updated_by": settings.updated_by,
        "last_exported_at": state.get("last_exported_at"),
    }


def build_feedback_export(
    include_all: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Build an export bundle payload and metadata."""
    settings = get_feedback_settings()
    events = load_feedback_events()
    state = load_export_state(settings.state_file)

    start_index = 0 if include_all else int(state.get("last_exported_line", 0) or 0)
    indexed_events = list(enumerate(events, start=1))
    selected = indexed_events[start_index:]
    if limit is not None:
        selected = selected[:limit]

    selected_events = [event for _line_no, event in selected]
    last_line = selected[-1][0] if selected else start_index

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "consent": settings.consent,
        "event_count": len(selected_events),
        "line_range": [selected[0][0], last_line] if selected else [],
        "events": selected_events,
        "summary": summarize_feedback_status(),
    }


def write_feedback_export(
    bundle: dict[str, Any],
    output_path: str | Path | None = None,
    advance_state: bool = True,
) -> Path:
    """Write a feedback export bundle and optionally advance export state."""
    settings = get_feedback_settings()
    settings.export_dir.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = settings.export_dir / f"feedback_export_{timestamp}.json"
    else:
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    if advance_state and bundle.get("line_range"):
        state = load_export_state(settings.state_file)
        state["last_exported_line"] = bundle["line_range"][1]
        state["last_exported_at"] = bundle["generated_at"]
        save_export_state(settings.state_file, state)

    return target


def validate_consent_level(consent: str) -> str:
    """Validate a consent level value."""
    if consent not in _SUPPORTED_CONSENT:
        raise ValueError(
            f"Unsupported consent level: {consent}. "
            f"Expected one of: {', '.join(sorted(_SUPPORTED_CONSENT))}"
        )
    return consent


def _resolve_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    root = get_harness_root()
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (root / path).resolve()

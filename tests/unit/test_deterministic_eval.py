"""Unit tests for packages.eval.deterministic.DeterministicEvaluator."""

from __future__ import annotations

from typing import Any

import pytest

from packages.eval.deterministic import DeterministicEvaluator, EvalResult


@pytest.fixture()
def evaluator() -> DeterministicEvaluator:
    """Return a fresh DeterministicEvaluator."""
    return DeterministicEvaluator()


# ---------------------------------------------------------------------------
# Output schema validation
# ---------------------------------------------------------------------------

class TestValidateOutputSchema:
    """Tests for DeterministicEvaluator.validate_output_schema."""

    def test_validate_output_schema_valid(self, evaluator: DeterministicEvaluator) -> None:
        """A valid output passes schema validation."""
        schema: dict[str, Any] = {
            "type": "object",
            "required": ["result", "confidence"],
            "properties": {
                "result": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        }
        output = {"result": "success", "confidence": 0.95}

        result = evaluator.validate_output_schema(output, schema)
        assert result.passed is True
        assert result.check_name == "output_schema"
        assert result.score == 1.0

    def test_validate_output_schema_invalid(self, evaluator: DeterministicEvaluator) -> None:
        """An output missing required fields fails validation."""
        schema: dict[str, Any] = {
            "type": "object",
            "required": ["result", "confidence"],
            "properties": {
                "result": {"type": "string"},
                "confidence": {"type": "number"},
            },
        }
        output = {"result": "success"}  # missing 'confidence'

        result = evaluator.validate_output_schema(output, schema)
        assert result.passed is False
        assert result.check_name == "output_schema"
        assert result.score == 0.0
        assert "confidence" in result.details

    def test_validate_output_schema_wrong_type(self, evaluator: DeterministicEvaluator) -> None:
        """An output with the wrong type for a field fails validation."""
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
        }
        output = {"count": "not-a-number"}

        result = evaluator.validate_output_schema(output, schema)
        assert result.passed is False
        assert "not-a-number" in result.details or "type" in result.details.lower()


# ---------------------------------------------------------------------------
# Test pass/fail detection
# ---------------------------------------------------------------------------

class TestCheckTestsPassed:
    """Tests for DeterministicEvaluator.check_tests_passed."""

    def test_check_tests_passed(self, evaluator: DeterministicEvaluator) -> None:
        """Output containing 'passed' is treated as success."""
        result = evaluator.check_tests_passed("===== 12 passed in 3.45s =====")
        assert result.passed is True
        assert result.check_name == "tests_passed"
        assert result.score == 1.0

    def test_check_tests_failed(self, evaluator: DeterministicEvaluator) -> None:
        """Output containing '2 failed' is treated as failure."""
        result = evaluator.check_tests_passed(
            "===== 2 failed, 10 passed in 5.67s ====="
        )
        assert result.passed is False
        assert result.check_name == "tests_passed"
        assert result.score == 0.0

    def test_check_tests_ambiguous(self, evaluator: DeterministicEvaluator) -> None:
        """Ambiguous output (no clear signal) is treated as failure."""
        result = evaluator.check_tests_passed("Building project... done.")
        assert result.passed is False
        assert "Could not determine" in result.details


# ---------------------------------------------------------------------------
# Boundary violations
# ---------------------------------------------------------------------------

class TestCheckBoundaryViolations:
    """Tests for DeterministicEvaluator.check_boundary_violations."""

    def test_check_boundary_violations_none(self, evaluator: DeterministicEvaluator) -> None:
        """No violations passes the check."""
        result = evaluator.check_boundary_violations([])
        assert result.passed is True
        assert result.check_name == "boundary_violations"
        assert result.score == 1.0

    def test_check_boundary_violations_found(self, evaluator: DeterministicEvaluator) -> None:
        """Violations cause the check to fail."""
        violations = [
            {"file": "src/database/models.py", "rule": "out_of_scope"},
            {"file": "src/auth/config.py", "rule": "out_of_scope"},
        ]
        result = evaluator.check_boundary_violations(violations)
        assert result.passed is False
        assert result.check_name == "boundary_violations"
        assert result.score == 0.0
        assert "2 boundary violation" in result.details


# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------

class TestCheckBlastRadius:
    """Tests for DeterministicEvaluator.check_blast_radius."""

    def test_check_blast_radius_under_threshold(
        self, evaluator: DeterministicEvaluator
    ) -> None:
        """Blast radius within threshold passes."""
        impact = {"blast_radius": 25}
        result = evaluator.check_blast_radius(impact, threshold=50)
        assert result.passed is True
        assert result.check_name == "blast_radius"
        assert result.score == 1.0
        assert "within" in result.details

    def test_check_blast_radius_at_threshold(
        self, evaluator: DeterministicEvaluator
    ) -> None:
        """Blast radius exactly at threshold passes (<=)."""
        impact = {"blast_radius": 50}
        result = evaluator.check_blast_radius(impact, threshold=50)
        assert result.passed is True

    def test_check_blast_radius_over_threshold(
        self, evaluator: DeterministicEvaluator
    ) -> None:
        """Blast radius over threshold fails."""
        impact = {"blast_radius": 80}
        result = evaluator.check_blast_radius(impact, threshold=50)
        assert result.passed is False
        assert result.check_name == "blast_radius"
        assert "above" in result.details
        # Score should be degraded but >= 0
        assert 0.0 <= result.score < 1.0

    def test_check_blast_radius_zero(self, evaluator: DeterministicEvaluator) -> None:
        """Zero blast radius always passes."""
        impact = {"blast_radius": 0}
        result = evaluator.check_blast_radius(impact, threshold=50)
        assert result.passed is True
        assert result.score == 1.0

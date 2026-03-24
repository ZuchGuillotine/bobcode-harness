"""Deterministic (non-LLM) evaluators for task outputs."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import jsonschema  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    """Result of a single deterministic evaluation check."""

    passed: bool
    check_name: str
    details: str = ""
    score: float = 0.0


class DeterministicEvaluator:
    """Suite of deterministic checks that run without an LLM."""

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def validate_output_schema(
        self, output: dict[str, Any], contract: dict[str, Any]
    ) -> EvalResult:
        """Validate *output* against a JSON-schema *contract*."""
        try:
            jsonschema.validate(instance=output, schema=contract)
            return EvalResult(
                passed=True,
                check_name="output_schema",
                details="Output matches the contract schema.",
                score=1.0,
            )
        except jsonschema.ValidationError as exc:
            return EvalResult(
                passed=False,
                check_name="output_schema",
                details=f"Schema validation failed: {exc.message}",
                score=0.0,
            )
        except jsonschema.SchemaError as exc:
            return EvalResult(
                passed=False,
                check_name="output_schema",
                details=f"Invalid contract schema: {exc.message}",
                score=0.0,
            )

    def check_tests_passed(self, test_output: str) -> EvalResult:
        """Heuristically determine whether test output indicates all tests passed.

        Looks for common test-framework patterns (pytest, jest, go test, etc.).
        """
        lower = test_output.lower()

        # Explicit failure signals
        failure_patterns = [
            r"\d+ failed",
            r"FAIL",
            r"FAILURES",
            r"AssertionError",
            r"Error:",
            r"FAILED",
        ]
        for pat in failure_patterns:
            if re.search(pat, test_output):
                return EvalResult(
                    passed=False,
                    check_name="tests_passed",
                    details=f"Test output contains failure indicator matching '{pat}'.",
                    score=0.0,
                )

        # Explicit success signals
        success_patterns = [
            r"passed",
            r"ok\b",
            r"PASS",
            r"All \d+ tests passed",
            r"0 failures",
        ]
        for pat in success_patterns:
            if re.search(pat, test_output, re.IGNORECASE):
                return EvalResult(
                    passed=True,
                    check_name="tests_passed",
                    details="Test output indicates success.",
                    score=1.0,
                )

        # Ambiguous - treat as failed to be safe
        return EvalResult(
            passed=False,
            check_name="tests_passed",
            details="Could not determine test result from output.",
            score=0.0,
        )

    def check_boundary_violations(self, violations: list[Any]) -> EvalResult:
        """Fail if there are any architectural boundary violations."""
        if not violations:
            return EvalResult(
                passed=True,
                check_name="boundary_violations",
                details="No boundary violations detected.",
                score=1.0,
            )
        count = len(violations)
        return EvalResult(
            passed=False,
            check_name="boundary_violations",
            details=f"{count} boundary violation(s) detected: {violations}",
            score=0.0,
        )

    def check_blast_radius(
        self, impact: dict[str, Any], threshold: int = 50
    ) -> EvalResult:
        """Fail if blast_radius exceeds *threshold*."""
        radius = impact.get("blast_radius", 0)
        passed = radius <= threshold
        return EvalResult(
            passed=passed,
            check_name="blast_radius",
            details=(
                f"Blast radius {radius} is {'within' if passed else 'above'} "
                f"threshold of {threshold}."
            ),
            score=1.0 if passed else max(0.0, 1.0 - (radius - threshold) / threshold),
        )

    def check_budget_compliance(self, budget: dict[str, Any]) -> EvalResult:
        """Fail if actual spend/tokens exceed the budget limits."""
        max_cost = budget.get("max_cost", float("inf"))
        max_tokens = budget.get("max_tokens", float("inf"))
        actual_cost = budget.get("actual_cost", 0.0)
        actual_tokens = budget.get("actual_tokens", 0)

        cost_ok = actual_cost <= max_cost
        tokens_ok = actual_tokens <= max_tokens
        passed = cost_ok and tokens_ok

        details_parts: list[str] = []
        if not cost_ok:
            details_parts.append(
                f"Cost ${actual_cost:.4f} exceeds budget ${max_cost:.4f}"
            )
        if not tokens_ok:
            details_parts.append(
                f"Tokens {actual_tokens} exceed budget {max_tokens}"
            )
        if passed:
            details_parts.append("Budget compliance OK.")

        return EvalResult(
            passed=passed,
            check_name="budget_compliance",
            details=" | ".join(details_parts),
            score=1.0 if passed else 0.0,
        )

    # ------------------------------------------------------------------
    # Run all checks
    # ------------------------------------------------------------------

    def run_all(self, task_state: dict[str, Any]) -> list[EvalResult]:
        """Run every applicable deterministic check against *task_state*.

        *task_state* should contain keys such as:
        - ``output`` and ``output_contract`` for schema validation
        - ``test_output`` for test-pass checking
        - ``boundary_violations`` for boundary checks
        - ``impact`` for blast-radius checks
        - ``budget`` for budget compliance
        """
        results: list[EvalResult] = []

        # Schema validation
        if "output" in task_state and "output_contract" in task_state:
            results.append(
                self.validate_output_schema(
                    task_state["output"], task_state["output_contract"]
                )
            )

        # Test results
        if "test_output" in task_state:
            results.append(self.check_tests_passed(task_state["test_output"]))

        # Boundary violations
        if "boundary_violations" in task_state:
            results.append(
                self.check_boundary_violations(task_state["boundary_violations"])
            )

        # Blast radius
        if "impact" in task_state:
            threshold = task_state.get("blast_radius_threshold", 50)
            results.append(
                self.check_blast_radius(task_state["impact"], threshold=threshold)
            )

        # Budget
        if "budget" in task_state:
            results.append(self.check_budget_compliance(task_state["budget"]))

        return results

"""Reviewer agent — read-only verification of worker output."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from packages.llm.prompt_loader import PromptLoader
from packages.llm.router import LLMRouter
from packages.repo_intel.codegraph_adapter import CodegraphAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (read-only)
# ---------------------------------------------------------------------------

REVIEWER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "repo_intel_get_boundary_violations",
            "description": "Check whether changes cross architectural boundaries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["files"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_intel_get_impact",
            "description": "Analyse the blast radius of the changed files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "symbol_name": {"type": "string"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diff_read",
            "description": "Read the diff for a specific file or the whole changeset.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Optional file to filter."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "test_results_read",
            "description": "Read test results from the latest test run.",
            "parameters": {
                "type": "object",
                "properties": {
                    "suite": {"type": "string", "description": "Optional test suite filter."},
                },
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Reviewer prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the Reviewer agent. Your job is to independently verify the quality \
and correctness of worker output. You are READ-ONLY — you cannot modify files.

## Review Checklist
1. Does the diff match the plan's in-scope files?
2. Are there any boundary violations?
3. Did tests pass?
4. Is the blast radius acceptable?
5. Are there suspicious omissions (e.g., no tests for new code)?
6. Is the change minimal and focused?

## Output Contract
Respond with a single JSON object:
{
  "verdict": "approved" | "rejected" | "needs_changes",
  "issues": [{"severity": "critical|warning|info", "description": "...", "file": "..."}],
  "confidence": 0.0-1.0,
  "summary": "..."
}
"""


class ReviewerAgent:
    """Reviewer agent — read-only review of diffs and test results."""

    def __init__(
        self,
        worktree_path: str | None = None,
        llm_router: LLMRouter | None = None,
    ) -> None:
        self.role = "reviewer"
        self.worktree_path = worktree_path or "."
        self._prompt_loader = PromptLoader()
        self._llm_router = llm_router or LLMRouter()
        self._codegraph = CodegraphAdapter()
        self._system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load prompt via PromptLoader; fall back to builtin."""
        try:
            prompt = self._prompt_loader.compose_system_prompt(self.role)
            if prompt:
                return prompt
        except Exception:
            logger.debug("PromptLoader failed — using built-in reviewer prompt")
        return _SYSTEM_PROMPT

    def _get_model(self) -> str:
        """Resolve model name via LLMRouter config."""
        try:
            primary, _fallbacks = self._llm_router._resolve_model(self.role)
            return primary
        except Exception:
            return "anthropic/claude-sonnet-4-6"

    # ------------------------------------------------------------------
    # Core review call
    # ------------------------------------------------------------------

    async def review(
        self,
        artifacts: list[dict[str, Any]],
        plan: dict[str, Any],
        task_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Review the worker's artifacts against the plan.

        Returns a review verdict dict.
        """

        import litellm  # type: ignore[import-untyped]

        model = self._get_model()
        task_id = task_state.get("task_id", "")

        # Build a summary of artifacts for the reviewer
        artifact_summary = self._summarise_artifacts(artifacts)

        user_message = (
            f"## Review Request — Task {task_id}\n\n"
            f"### Plan\n"
            f"- In-scope: {json.dumps(plan.get('in_scope', []))}\n"
            f"- Out-of-scope: {json.dumps(plan.get('out_of_scope', []))}\n"
            f"- Plan steps: {json.dumps(plan.get('plan_steps', []), indent=2)}\n\n"
            f"### Artifacts\n{artifact_summary}\n\n"
            f"Review these changes. Use the tools to check for boundary violations "
            f"and blast radius. Then produce your verdict."
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Multi-turn tool-use loop (max 3 rounds — review is lighter)
        for _round in range(3):
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                tools=REVIEWER_TOOLS,
                tool_choice="auto",
                max_tokens=4000,
                temperature=0.1,
            )

            choice = response.choices[0]

            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                messages.append(choice.message.model_dump())

                for tc in choice.message.tool_calls:
                    result = self._execute_tool(
                        tc.function.name, tc.function.arguments, artifacts
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    })
                continue

            content = choice.message.content or ""
            return self._parse_verdict(content)

        logger.warning("Reviewer exhausted rounds for task %s", task_id)
        return self._default_verdict()

    # ------------------------------------------------------------------
    # Tool execution (read-only stubs)
    # ------------------------------------------------------------------

    def _execute_tool(
        self, tool_name: str, arguments: str, artifacts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON: {arguments}"}

        if tool_name == "diff_read":
            return self._tool_diff_read(artifacts, args.get("file_path"))
        if tool_name == "test_results_read":
            return self._tool_test_results_read(artifacts, args.get("suite"))
        if tool_name == "repo_intel_get_boundary_violations":
            return self._tool_boundary_violations(args.get("files", []))
        if tool_name == "repo_intel_get_impact":
            return self._tool_get_impact(args.get("file_path", ""), args.get("symbol_name"))

        return {"error": f"Unknown tool: {tool_name}"}

    def _tool_diff_read(
        self, artifacts: list[dict[str, Any]], file_path: str | None = None
    ) -> dict[str, Any]:
        """Read diff content — check artifacts first, then try reading actual diff files."""
        diffs = [a for a in artifacts if a.get("type") == "diff"]
        if file_path:
            diffs = [d for d in diffs if d.get("path") == file_path]

        # If no matching artifacts, try reading actual diff files from the worktree
        if not diffs and file_path:
            full_path = os.path.join(self.worktree_path, file_path)
            if os.path.isfile(full_path):
                try:
                    with open(full_path) as f:
                        content = f.read()
                    diffs = [{"type": "diff", "path": file_path, "content": content}]
                except OSError:
                    pass
        return {"diffs": diffs}

    def _tool_test_results_read(
        self, artifacts: list[dict[str, Any]], suite: str | None = None
    ) -> dict[str, Any]:
        """Read test results — check artifacts first, then try reading actual test output files."""
        results = [a for a in artifacts if a.get("type") == "test_result"]
        if suite:
            results = [r for r in results if suite in r.get("path", "")]

        # If no matching artifacts, try reading test output from the worktree
        if not results:
            test_output_paths = [
                os.path.join(self.worktree_path, "test_output.txt"),
                os.path.join(self.worktree_path, "test-results.xml"),
            ]
            for tp in test_output_paths:
                if os.path.isfile(tp):
                    try:
                        with open(tp) as f:
                            content = f.read()
                        results.append({"type": "test_result", "path": tp, "content": content})
                    except OSError:
                        pass
        return {"test_results": results}

    def _tool_boundary_violations(self, files: list[str]) -> dict[str, Any]:
        """Check boundary violations via CodegraphAdapter."""
        all_violations: list[dict[str, Any]] = []
        for f in files:
            violations = self._codegraph.get_boundary_violations(f)
            all_violations.extend(violations)
        return {"files": files, "violations": all_violations}

    def _tool_get_impact(self, file_path: str, symbol_name: str | None = None) -> dict[str, Any]:
        """Analyse blast radius via CodegraphAdapter."""
        impact = self._codegraph.get_impact(file_path)
        return {"file": file_path, "impact": impact}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarise_artifacts(artifacts: list[dict[str, Any]]) -> str:
        if not artifacts:
            return "(no artifacts)"

        parts: list[str] = []
        for art in artifacts:
            art_type = art.get("type", "unknown")
            path = art.get("path", "")
            content = art.get("content", "")
            preview = content[:500] + "..." if len(content) > 500 else content
            parts.append(f"**{art_type}** `{path}`\n```\n{preview}\n```")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_verdict(content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            verdict = json.loads(cleaned)
            verdict.setdefault("verdict", "needs_changes")
            verdict.setdefault("issues", [])
            verdict.setdefault("confidence", 0.5)
            verdict.setdefault("summary", "")
            return verdict
        except json.JSONDecodeError:
            return {
                "verdict": "needs_changes",
                "issues": [
                    {
                        "severity": "warning",
                        "description": "Reviewer output was not valid JSON",
                        "file": "",
                    }
                ],
                "confidence": 0.0,
                "summary": content[:500],
            }

    @staticmethod
    def _default_verdict() -> dict[str, Any]:
        return {
            "verdict": "needs_changes",
            "issues": [
                {
                    "severity": "warning",
                    "description": "Reviewer exhausted tool-use rounds without producing a verdict",
                    "file": "",
                }
            ],
            "confidence": 0.0,
            "summary": "Review incomplete.",
        }

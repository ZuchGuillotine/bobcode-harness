"""Worker agent — executes the plan in a worktree and returns artifacts."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from packages.llm.prompt_loader import PromptLoader
from packages.llm.router import LLMRouter
from packages.repo_intel.codegraph_adapter import CodegraphAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions available to the Worker
# ---------------------------------------------------------------------------

WORKER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or repo-relative path."},
                    "start_line": {"type": "integer", "description": "First line to read (1-based)."},
                    "end_line": {"type": "integer", "description": "Last line to read."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write content to a file (creates or overwrites).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_patch",
            "description": "Apply a unified diff patch to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "patch": {"type": "string", "description": "Unified diff content."},
                },
                "required": ["path", "patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_run",
            "description": "Run a shell command in the worktree. Use for tests, linters, builds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "description": "Max execution time."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show the current git diff in the worktree.",
            "parameters": {
                "type": "object",
                "properties": {
                    "staged": {"type": "boolean", "description": "Show staged diff only."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_apply_patch",
            "description": "Apply a git-format patch file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch_content": {"type": "string"},
                },
                "required": ["patch_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_intel_get_context",
            "description": "Get targeted context for a file (imports, callers, callees).",
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
            "name": "repo_intel_get_candidate_tests",
            "description": "Find test files relevant to the changed files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["file_paths"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Worker prompt (fallback)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the Worker agent. Your job is to execute a plan step-by-step in a \
worktree. You have file read/write/patch tools, a sandboxed shell, and \
limited repo-intel access.

## Rules
1. Follow the plan steps exactly. Do not deviate.
2. After making changes, run relevant tests via shell_run.
3. Keep changes minimal and focused.
4. Return a summary of what was done plus the git diff.

## Output
After executing all steps, respond with a JSON object:
{
  "completed_steps": [...],
  "artifacts": [{"type": "diff|file|test_result", "path": "...", "content": "..."}],
  "tests_passed": true|false,
  "summary": "..."
}
"""


class WorkerAgent:
    """Worker agent — executes plans by writing code and running commands."""

    def __init__(
        self,
        worktree_path: str | None = None,
        llm_router: LLMRouter | None = None,
    ) -> None:
        self.role = "worker"
        self.worktree_path = os.path.realpath(worktree_path or ".")
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
            logger.debug("PromptLoader failed — using built-in worker prompt")
        return _SYSTEM_PROMPT

    def _get_model(self) -> str:
        """Resolve model name via LLMRouter config."""
        try:
            primary, _fallbacks = self._llm_router._resolve_model(self.role)
            return primary
        except Exception:
            return "anthropic/claude-sonnet-4-6"

    def _safe_resolve_path(self, path: str) -> str:
        """Resolve *path* and ensure it is within the worktree.  Raises ValueError otherwise."""
        full = os.path.realpath(
            os.path.join(self.worktree_path, path) if not os.path.isabs(path) else path
        )
        if not full.startswith(self.worktree_path):
            raise ValueError(f"Path escapes worktree: {path}")
        return full

    # ------------------------------------------------------------------
    # Core execution call
    # ------------------------------------------------------------------

    async def execute(self, plan: dict[str, Any], task_state: dict[str, Any]) -> dict[str, Any]:
        """Execute the plan and return artifacts.

        Returns a dict with completed_steps, artifacts, tests_passed, summary.
        """

        from packages.llm.providers import get_provider

        model = self._get_model()
        provider = get_provider(model)
        task_id = task_state.get("task_id", "")
        plan_steps = plan.get("plan_steps", [])

        user_message = (
            f"## Task {task_id}\n\n"
            f"### Plan Steps\n"
            f"{json.dumps(plan_steps, indent=2)}\n\n"
            f"### Selected Skill: {plan.get('selected_skill', 'unknown')}\n"
            f"### In-scope files: {json.dumps(plan.get('in_scope', []))}\n"
            f"### Out-of-scope files (DO NOT TOUCH): {json.dumps(plan.get('out_of_scope', []))}\n\n"
            f"Execute this plan now. Use the tools to read, write, and test."
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Multi-turn tool-use loop (max 10 rounds for complex implementations)
        for _round in range(10):
            response = await provider.acomplete(
                model=model,
                messages=messages,
                tools=WORKER_TOOLS,
                tool_choice="auto",
                max_tokens=16000,
                temperature=0.2,
            )

            # Access provider-specific raw response for tool_calls
            raw = response.raw

            if hasattr(raw, "choices") and raw.choices:
                # OpenAI-compatible response
                choice = raw.choices[0]
                if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                    messages.append(choice.message.model_dump())
                    for tc in choice.message.tool_calls:
                        result = await self._execute_tool(tc.function.name, tc.function.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result),
                        })
                    continue
            elif hasattr(raw, "content") and hasattr(raw, "stop_reason"):
                # Anthropic-style response
                tool_use_blocks = [b for b in raw.content if getattr(b, "type", None) == "tool_use"]
                if raw.stop_reason == "tool_use" and tool_use_blocks:
                    assistant_content = []
                    for block in raw.content:
                        if block.type == "text":
                            assistant_content.append({"type": "text", "text": block.text})
                        elif block.type == "tool_use":
                            assistant_content.append({
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            })
                    messages.append({"role": "assistant", "content": assistant_content})

                    tool_results = []
                    for block in tool_use_blocks:
                        result = await self._execute_tool(block.name, json.dumps(block.input))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })
                    messages.append({"role": "user", "content": tool_results})
                    continue

            # Final response
            content = response.content or ""
            return self._parse_result(content, task_id)

        logger.warning("Worker exhausted tool-use rounds for task %s", task_id)
        return {
            "completed_steps": [],
            "artifacts": [],
            "tests_passed": False,
            "summary": "Worker exhausted maximum tool-use rounds.",
        }

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_tool(self, tool_name: str, arguments: str) -> dict[str, Any]:
        """Dispatch a tool call to the real handler or stub."""

        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON: {arguments}"}

        dispatch: dict[str, Any] = {
            "file_read": self._tool_file_read,
            "file_write": self._tool_file_write,
            "file_patch": self._tool_file_patch,
            "shell_run": self._tool_shell_run,
            "git_diff": self._tool_git_diff,
            "git_apply_patch": self._tool_git_apply_patch,
            "repo_intel_get_context": self._tool_repo_intel_get_context,
            "repo_intel_get_candidate_tests": self._tool_repo_intel_get_candidate_tests,
        }

        handler = dispatch.get(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return await handler(**args) if asyncio.iscoroutinefunction(handler) else handler(**args)
        except Exception as exc:
            return {"error": str(exc)}

    # --- Real tool implementations ---

    def _tool_file_read(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> dict[str, Any]:
        full_path = self._safe_resolve_path(path)
        try:
            with open(full_path) as f:
                lines = f.readlines()
            if start_line is not None:
                s = max(0, start_line - 1)
                e = end_line if end_line else len(lines)
                lines = lines[s:e]
            return {"path": path, "content": "".join(lines), "lines": len(lines)}
        except FileNotFoundError:
            return {"error": f"File not found: {full_path}"}

    def _tool_file_write(self, path: str, content: str) -> dict[str, Any]:
        full_path = self._safe_resolve_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        return {"path": path, "bytes_written": len(content)}

    def _tool_file_patch(self, path: str, patch: str) -> dict[str, Any]:
        import subprocess
        import tempfile

        self._safe_resolve_path(path)  # validate path is inside worktree

        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as tmp:
            tmp.write(patch)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                ["patch", path, tmp_path],
                capture_output=True,
                text=True,
                cwd=self.worktree_path,
                timeout=10,
            )
            return {"success": result.returncode == 0, "output": result.stdout, "error": result.stderr}
        except Exception as exc:
            return {"error": str(exc)}

    def _tool_shell_run(self, command: str, timeout_seconds: int = 30) -> dict[str, Any]:
        import subprocess

        # Enforce that shell commands run inside the worktree
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.worktree_path,
                timeout=min(timeout_seconds, 120),
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout[-4000:] if len(result.stdout) > 4000 else result.stdout,
                "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after {timeout_seconds}s"}

    def _tool_git_diff(self, staged: bool = False) -> dict[str, Any]:
        import subprocess

        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.worktree_path)
        return {"diff": result.stdout, "error": result.stderr if result.returncode != 0 else None}

    def _tool_git_apply_patch(self, patch_content: str) -> dict[str, Any]:
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as tmp:
            tmp.write(patch_content)
            tmp_path = tmp.name

        result = subprocess.run(
            ["git", "apply", tmp_path],
            capture_output=True,
            text=True,
            cwd=self.worktree_path,
        )
        return {"success": result.returncode == 0, "output": result.stdout, "error": result.stderr}

    # --- Repo-intel tool handlers (backed by CodegraphAdapter) ---

    def _tool_repo_intel_get_context(self, file_path: str, symbol_name: str | None = None) -> dict[str, Any]:
        symbol = symbol_name or file_path
        context = self._codegraph.get_context(symbol)
        return {"file": file_path, "symbol": symbol_name, "context": context}

    def _tool_repo_intel_get_candidate_tests(self, file_paths: list[str]) -> dict[str, Any]:
        tests = self._codegraph.get_candidate_tests(file_paths)
        return {"file_paths": file_paths, "candidate_tests": tests}

    # ------------------------------------------------------------------
    # Parse result
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_result(content: str, task_id: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            result = json.loads(cleaned)
            result.setdefault("completed_steps", [])
            result.setdefault("artifacts", [])
            result.setdefault("tests_passed", False)
            result.setdefault("summary", "")
            return result
        except json.JSONDecodeError:
            return {
                "completed_steps": [],
                "artifacts": [{"type": "raw_output", "content": content}],
                "tests_passed": False,
                "summary": f"Worker output for {task_id} was not valid JSON.",
            }

"""Planner agent — decomposes tasks into bounded, executable plans."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from typing import Any

from packages.llm.prompt_loader import PromptLoader
from packages.llm.router import LLMRouter
from packages.repo_intel.codegraph_adapter import CodegraphAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions available to the Planner
# ---------------------------------------------------------------------------

PLANNER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "repo_intel_locate_symbol",
            "description": "Locate a symbol (function, class, variable) in the codebase by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {"type": "string", "description": "The symbol to locate."},
                    "kind": {
                        "type": "string",
                        "enum": ["function", "class", "variable", "any"],
                        "description": "Kind of symbol to search for.",
                    },
                },
                "required": ["symbol_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_intel_get_context",
            "description": "Get surrounding context for a file/symbol — imports, callers, callees.",
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
            "name": "repo_intel_get_impact",
            "description": "Analyse the blast radius of changing a symbol or file.",
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
            "name": "repo_intel_get_cochange",
            "description": "Find files that historically change together with the given file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_intel_get_boundary_violations",
            "description": "Check whether a proposed change crosses architectural boundaries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files in the proposed change.",
                    },
                },
                "required": ["files"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_registry_find_best_skill",
            "description": "Find the best matching skill for a given task type and context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["task_type"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Planner prompt (fallback when prompt_loader is unavailable)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the Planner agent. Your job is to decompose tasks into bounded, \
executable plans and select the smallest high-confidence code subgraph \
needed to act safely.

## Output Contract
You MUST respond with a single JSON object containing:
- task_id: string — echoed from input
- task_type: string — code_change | marketing_campaign | content_creation
- plan_steps: array of {step_number, action, target, rationale}
- selected_skill: string — skill id to use
- estimated_budget_tokens: integer
- confidence: float 0-1
- missing_evidence: array of strings (things you couldn't verify)
- in_scope: array of file paths
- out_of_scope: array of file paths that must NOT be touched

Do NOT include any text outside the JSON object.
"""


class PlannerAgent:
    """Planner agent — thin wrapper around a frontier LLM call with curated tools."""

    def __init__(
        self,
        repo_path: str = ".",
        llm_router: LLMRouter | None = None,
        use_claude_code: bool | None = None,
    ) -> None:
        self.role = "planner"
        self.repo_path = repo_path
        self._codegraph = CodegraphAdapter()
        self._prompt_loader = PromptLoader()
        self._llm_router = llm_router or LLMRouter()
        self._system_prompt = self._load_prompt()
        # Auto-detect: use Claude Code CLI if installed and authenticated
        if use_claude_code is None:
            self._use_claude_code = self._detect_claude_code()
        else:
            self._use_claude_code = use_claude_code

    def _load_prompt(self) -> str:
        """Load prompt via PromptLoader; fall back to builtin."""
        try:
            prompt = self._prompt_loader.compose_system_prompt(self.role)
            if prompt:
                return prompt
        except Exception:
            logger.debug("PromptLoader failed — using built-in planner prompt")
        return _SYSTEM_PROMPT

    def _get_model(self) -> str:
        """Resolve model name via LLMRouter config."""
        try:
            primary, _fallbacks = self._llm_router._resolve_model(self.role)
            return primary
        except Exception:
            return "anthropic/claude-opus-4-6"

    # ------------------------------------------------------------------
    # Claude Code CLI detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_claude_code() -> bool:
        """Return True if `claude` CLI is installed and authenticated."""
        if not shutil.which("claude"):
            return False
        try:
            result = subprocess.run(
                ["claude", "auth", "status"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and "loggedIn" in result.stdout:
                data = json.loads(result.stdout)
                if data.get("loggedIn"):
                    logger.info("Claude Code CLI detected (Max plan) — planner will use it")
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Core planning call
    # ------------------------------------------------------------------

    async def plan(self, task_state: dict[str, Any]) -> dict[str, Any]:
        """Generate a plan packet for the given task state.

        Routes to Claude Code CLI (Max plan) when available, otherwise
        falls back to direct provider API calls.
        """
        if self._use_claude_code:
            return await self._plan_via_claude_code(task_state)
        return await self._plan_via_llm(task_state)

    async def _plan_via_claude_code(self, task_state: dict[str, Any]) -> dict[str, Any]:
        """Plan using Claude Code CLI (uses Max subscription, not API credits).

        Since `claude --print` doesn't support tool use, we pre-gather repo
        context and include it in the prompt.
        """
        task_id = task_state.get("task_id", "")
        description = task_state.get("description", "")
        task_type = task_state.get("task_type", "code_change")

        # Pre-gather repo context via codegraph (no LLM cost)
        repo_context = self._gather_repo_context(description)

        prompt = (
            f"{self._system_prompt}\n\n"
            f"## Task\n"
            f"- task_id: {task_id}\n"
            f"- task_type: {task_type}\n"
            f"- description: {description}\n\n"
            f"## Repository Context (pre-gathered)\n"
            f"{json.dumps(repo_context, indent=2)}\n\n"
            f"Based on the above, produce a plan as a single JSON object."
        )

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["claude", "--print", "--model", "opus", "--output-format", "text", "-p", prompt],
                capture_output=True, text=True, timeout=120,
                cwd=self.repo_path,
            )

            if result.returncode != 0:
                logger.error("Claude Code CLI failed: %s", result.stderr[:500])
                # Fall back to provider API
                return await self._plan_via_llm(task_state)

            content = result.stdout.strip()
            logger.info("Planner (Claude Code CLI/Opus) produced %d chars", len(content))
            return self._parse_plan(content, task_id, task_type)

        except subprocess.TimeoutExpired:
            logger.error("Claude Code CLI timed out for task %s", task_id)
            return await self._plan_via_llm(task_state)
        except Exception as exc:
            logger.error("Claude Code CLI error: %s", exc)
            return await self._plan_via_llm(task_state)

    def _gather_repo_context(self, description: str) -> dict[str, Any]:
        """Pre-gather repo intelligence to include in the Claude Code prompt."""
        context: dict[str, Any] = {}

        # Extract likely symbol/file references from description
        words = description.split()
        for word in words:
            cleaned = word.strip(".,;:'\"(){}[]")
            if "." in cleaned and "/" in cleaned:
                # Looks like a file path
                try:
                    ctx = self._codegraph.get_context(cleaned)
                    if ctx:
                        context[f"context:{cleaned}"] = ctx
                    impact = self._codegraph.get_impact(cleaned)
                    if impact:
                        context[f"impact:{cleaned}"] = impact
                except Exception:
                    pass
            elif cleaned and not cleaned[0].isdigit() and "_" in cleaned:
                # Looks like a symbol name
                try:
                    loc = self._codegraph.locate_symbol(cleaned)
                    if loc and loc.get("file"):
                        context[f"symbol:{cleaned}"] = loc
                except Exception:
                    pass

        if not context:
            context["note"] = "No repo context available (codegraph may not be configured)"

        return context

    async def _plan_via_llm(self, task_state: dict[str, Any]) -> dict[str, Any]:
        """Plan using the provider system (standard API billing)."""

        from packages.llm.providers import get_provider

        model = self._get_model()
        provider = get_provider(model)
        task_id = task_state.get("task_id", "")
        description = task_state.get("description", "")
        task_type = task_state.get("task_type", "code_change")

        user_message = (
            f"## Task\n"
            f"- task_id: {task_id}\n"
            f"- task_type: {task_type}\n"
            f"- description: {description}\n\n"
            f"Create a plan for this task. Use the available tools to gather "
            f"context from the repository before finalising the plan."
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Multi-turn tool-use loop (max 5 rounds)
        for _round in range(5):
            response = await provider.acomplete(
                model=model,
                messages=messages,
                tools=PLANNER_TOOLS,
                tool_choice="auto",
                max_tokens=8000,
                temperature=0.3,
            )

            # Access provider-specific raw response for tool_calls
            raw = response.raw
            # OpenAI-style: raw.choices[0].message.tool_calls
            # Anthropic-style: raw.content blocks with type == "tool_use"
            tool_calls = None
            finish_reason = None

            if hasattr(raw, "choices") and raw.choices:
                # OpenAI-compatible response
                choice = raw.choices[0]
                finish_reason = choice.finish_reason
                tool_calls = choice.message.tool_calls
                if finish_reason == "tool_calls" and tool_calls:
                    messages.append(choice.message.model_dump())
                    for tc in tool_calls:
                        result = self._execute_tool(tc.function.name, tc.function.arguments)
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
                    # Build assistant message for Anthropic tool-use protocol
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

                    # Execute each tool call and append results
                    tool_results = []
                    for block in tool_use_blocks:
                        result = self._execute_tool(block.name, json.dumps(block.input))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })
                    messages.append({"role": "user", "content": tool_results})
                    continue

            # No more tool calls — extract final plan
            content = response.content or ""
            return self._parse_plan(content, task_id, task_type)

        # Fell through the loop — return a minimal plan
        logger.warning("Planner exhausted tool-use rounds for task %s", task_id)
        return self._empty_plan(task_id, task_type)

    # ------------------------------------------------------------------
    # Tool execution stubs
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_name: str, arguments: str) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate handler."""

        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON arguments: {arguments}"}

        # Route to real CodegraphAdapter and skill registry
        handlers: dict[str, Any] = {
            "repo_intel_locate_symbol": self._handle_locate_symbol,
            "repo_intel_get_context": self._handle_get_context,
            "repo_intel_get_impact": self._handle_get_impact,
            "repo_intel_get_cochange": self._handle_get_cochange,
            "repo_intel_get_boundary_violations": self._handle_get_boundary_violations,
            "skill_registry_find_best_skill": self._handle_find_best_skill,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return handler(**args)
        except Exception as exc:
            return {"error": str(exc)}

    # --- Real tool handlers backed by CodegraphAdapter ---

    def _handle_locate_symbol(self, symbol_name: str, kind: str = "any") -> dict[str, Any]:
        result = self._codegraph.locate_symbol(symbol_name)
        return {"symbol": symbol_name, "kind": kind, "locations": [result] if result.get("file") else []}

    def _handle_get_context(self, file_path: str, symbol_name: str | None = None) -> dict[str, Any]:
        symbol = symbol_name or file_path
        context = self._codegraph.get_context(symbol)
        return {"file": file_path, "symbol": symbol_name, "context": context}

    def _handle_get_impact(self, file_path: str, symbol_name: str | None = None) -> dict[str, Any]:
        impact = self._codegraph.get_impact(file_path)
        return {"file": file_path, "impact": impact}

    def _handle_get_cochange(self, file_path: str) -> dict[str, Any]:
        cochanges = self._codegraph.get_cochange(file_path)
        return {"file": file_path, "cochange_files": cochanges}

    def _handle_get_boundary_violations(self, files: list[str]) -> dict[str, Any]:
        # Boundary check expects a diff path; pass first file as proxy
        all_violations: list[dict[str, Any]] = []
        for f in files:
            violations = self._codegraph.get_boundary_violations(f)
            all_violations.extend(violations)
        return {"files": files, "violations": all_violations}

    @staticmethod
    def _handle_find_best_skill(task_type: str, context: str | None = None) -> dict[str, Any]:
        skill_map = {
            "code_change": "skill-code-change-v1",
            "marketing_campaign": "skill-campaign-v1",
            "content_creation": "skill-content-v1",
        }
        return {"skill_id": skill_map.get(task_type, "skill-code-change-v1")}

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_plan(content: str, task_id: str, task_type: str) -> dict[str, Any]:
        """Extract the JSON plan from the model's response."""
        cleaned = content.strip()

        # Extract JSON from markdown code fences (```json ... ```)
        import re
        fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        elif cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        else:
            # Try to find a JSON object in the response
            brace_start = cleaned.find("{")
            brace_end = cleaned.rfind("}")
            if brace_start != -1 and brace_end != -1:
                cleaned = cleaned[brace_start:brace_end + 1]

        try:
            plan = json.loads(cleaned)
            # Ensure required keys
            plan.setdefault("task_id", task_id)
            plan.setdefault("task_type", task_type)
            plan.setdefault("plan_steps", [])
            plan.setdefault("selected_skill", "skill-code-change-v1")
            plan.setdefault("estimated_budget_tokens", 50_000)
            plan.setdefault("confidence", 0.5)
            plan.setdefault("missing_evidence", [])
            plan.setdefault("in_scope", [])
            plan.setdefault("out_of_scope", [])
            return plan
        except json.JSONDecodeError:
            logger.warning("Failed to parse planner output as JSON, returning raw content")
            return {
                "task_id": task_id,
                "task_type": task_type,
                "plan_steps": [],
                "selected_skill": "skill-code-change-v1",
                "estimated_budget_tokens": 50_000,
                "confidence": 0.0,
                "missing_evidence": ["Planner output was not valid JSON"],
                "in_scope": [],
                "out_of_scope": [],
                "raw_output": content,
            }

    @staticmethod
    def _empty_plan(task_id: str, task_type: str) -> dict[str, Any]:
        return {
            "task_id": task_id,
            "task_type": task_type,
            "plan_steps": [],
            "selected_skill": "skill-code-change-v1",
            "estimated_budget_tokens": 0,
            "confidence": 0.0,
            "missing_evidence": ["Planner failed to produce output"],
            "in_scope": [],
            "out_of_scope": [],
        }

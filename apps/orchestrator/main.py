"""LangGraph StateGraph entrypoint for the agent harness orchestrator."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from apps.orchestrator.stages.execute import execute_node
from apps.orchestrator.stages.intake import intake_node
from apps.orchestrator.stages.learn import learn_node
from apps.orchestrator.stages.plan import plan_node
from apps.orchestrator.stages.validate import validate_node

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task state — the single object that flows through every node
# ---------------------------------------------------------------------------

class TaskState(TypedDict, total=False):
    """Typed state dict carried through the orchestrator graph."""

    task_id: str
    task_type: str  # code_change | marketing_campaign | content_creation
    domain: str
    description: str
    status: str  # intake | planning | executing | validating | done | retry | failed | learned
    plan: dict[str, Any] | None
    artifacts: list[dict[str, Any]]
    eval_results: dict[str, Any] | None
    budget: dict[str, Any]
    trace_id: str
    retries: int
    max_retries: int
    error: str | None


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

def route_result(state: TaskState) -> str:
    """Conditional edge: decide where to go after validation."""

    status = state.get("status", "")

    if status == "done":
        return "done"

    if status == "retry":
        retries = state.get("retries", 0)
        max_retries = state.get("max_retries", 3)
        if retries >= max_retries:
            logger.warning(
                "Task %s exhausted retries (%d/%d) — moving to learn",
                state.get("task_id"),
                retries,
                max_retries,
            )
            return "learn"
        return "retry"

    # Any non-terminal status (needs_changes, rejected, failed) → learn
    return "learn"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Construct and compile the orchestrator StateGraph."""

    graph = StateGraph(TaskState)

    # Register nodes
    graph.add_node("intake", intake_node)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("validate", validate_node)
    graph.add_node("route_result", _route_result_node)
    graph.add_node("learn", learn_node)

    # Linear edges
    graph.add_edge("intake", "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "validate")
    graph.add_edge("validate", "route_result")

    # Conditional edges from route_result
    graph.add_conditional_edges(
        "route_result",
        route_result,
        {
            "done": END,
            "retry": "plan",
            "learn": "learn",
        },
    )

    # Learn always terminates
    graph.add_edge("learn", END)

    # Retry goes back to plan (handled by conditional edge above)

    # Entry point
    graph.set_entry_point("intake")

    return graph


def _route_result_node(state: TaskState) -> TaskState:
    """Pass-through node that exists solely so conditional edges can branch."""
    logger.info("Routing task %s with status=%s", state.get("task_id"), state.get("status"))
    return state


# ---------------------------------------------------------------------------
# Phoenix / OpenTelemetry tracing bootstrap
# ---------------------------------------------------------------------------

def _init_tracing() -> None:
    """Start Phoenix tracing and wire up the OTel exporter."""
    try:
        import phoenix as px  # type: ignore[import-untyped]
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        # Launch local Phoenix instance (idempotent)
        px.launch_app()

        provider = TracerProvider()
        exporter = OTLPSpanExporter(endpoint="http://localhost:6006/v1/traces", insecure=True)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        logger.info("Phoenix tracing initialised on port 6006")
    except ImportError:
        logger.warning("Phoenix or OTel packages not installed — tracing disabled")
    except Exception:
        logger.exception("Failed to initialise tracing")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def run_task(description: str, task_type: str = "code_change") -> TaskState:
    """Submit a task and run it through the full orchestrator graph."""

    initial_state: TaskState = {
        "task_id": "",
        "task_type": task_type,
        "domain": "",
        "description": description,
        "status": "intake",
        "plan": None,
        "artifacts": [],
        "eval_results": None,
        "budget": {
            "max_tokens": 500_000,
            "max_cost_usd": 5.00,
            "tokens_used": 0,
            "cost_used": 0.0,
        },
        "trace_id": "",
        "retries": 0,
        "max_retries": 3,
        "error": None,
    }

    graph = build_graph()
    compiled = graph.compile()

    # LangGraph's invoke is synchronous by default; run in executor for async compat
    result = await asyncio.to_thread(compiled.invoke, initial_state)
    return result  # type: ignore[return-value]


async def main() -> None:
    """CLI-friendly async entrypoint."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    _init_tracing()

    logger.info("Agent harness orchestrator ready")
    logger.info("Use harness-ctl to submit tasks, or call run_task() programmatically.")


if __name__ == "__main__":
    asyncio.run(main())

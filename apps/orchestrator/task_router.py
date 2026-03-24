"""TaskRouter — lightweight task classification and skill routing."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known task types
# ---------------------------------------------------------------------------
TASK_TYPES = {"code_change", "marketing_campaign", "content_creation"}

# Simple keyword heuristics for classification when no LLM is available
_KEYWORD_MAP: dict[str, list[str]] = {
    "code_change": [
        "fix", "bug", "refactor", "implement", "feature", "test", "lint",
        "dependency", "upgrade", "migration", "api", "endpoint", "function",
        "class", "module", "patch", "error", "exception", "type",
    ],
    "marketing_campaign": [
        "campaign", "ads", "ad", "google ads", "linkedin", "twitter",
        "social media", "audience", "targeting", "budget", "cpc", "cpm",
        "impressions", "clicks", "conversions", "roi", "analytics",
    ],
    "content_creation": [
        "blog", "article", "post", "copy", "content", "write", "draft",
        "newsletter", "email", "landing page", "headline", "seo",
    ],
}

# Skill routing lookup — maps (task_type, optional context hints) → skill_id
_SKILL_MAP: dict[str, str] = {
    "code_change": "skill-code-change-v1",
    "marketing_campaign": "skill-campaign-v1",
    "content_creation": "skill-content-v1",
}


class TaskRouter:
    """Classify incoming task descriptions and route to the appropriate skill."""

    def __init__(self) -> None:
        self._model: str = "openai/gpt-5.4-mini"  # lightweight classifier

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify_task(self, description: str) -> str:
        """Classify a task description into a task_type.

        Uses keyword heuristics first. Falls back to the lightweight LLM
        classifier when heuristics are inconclusive.

        Returns one of: code_change, marketing_campaign, content_creation.
        """

        desc_lower = description.lower()
        scores: dict[str, int] = {t: 0 for t in TASK_TYPES}

        for task_type, keywords in _KEYWORD_MAP.items():
            for kw in keywords:
                if kw in desc_lower:
                    scores[task_type] += 1

        best = max(scores, key=lambda t: scores[t])

        if scores[best] == 0:
            # No keyword matches — try LLM classification
            return self._llm_classify(description)

        # If there's a clear winner, use it
        sorted_scores = sorted(scores.values(), reverse=True)
        if sorted_scores[0] > sorted_scores[1]:
            logger.info("Classified task as '%s' (keyword score %d)", best, scores[best])
            return best

        # Ambiguous — defer to LLM
        return self._llm_classify(description)

    def _llm_classify(self, description: str) -> str:
        """Use a lightweight LLM call to classify the task."""

        try:
            import litellm  # type: ignore[import-untyped]

            response = litellm.completion(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify the following task description into exactly one category: "
                            "code_change, marketing_campaign, or content_creation. "
                            "Respond with only the category name, nothing else."
                        ),
                    },
                    {"role": "user", "content": description},
                ],
                max_tokens=20,
                temperature=0.0,
            )
            result = response.choices[0].message.content.strip().lower()
            if result in TASK_TYPES:
                logger.info("LLM classified task as '%s'", result)
                return result
        except Exception:
            logger.exception("LLM classification failed — defaulting to code_change")

        return "code_change"

    # ------------------------------------------------------------------
    # Skill routing
    # ------------------------------------------------------------------

    def route_to_skill(self, task_type: str, context: dict[str, Any] | None = None) -> str:
        """Map a task_type (and optional context) to a skill_id."""

        # Context could carry hints like domain, repo, complexity — for now
        # we do a simple lookup.
        skill_id = _SKILL_MAP.get(task_type, "skill-code-change-v1")
        logger.info("Routed task_type='%s' → skill='%s'", task_type, skill_id)
        return skill_id


# Module-level singleton
task_router = TaskRouter()

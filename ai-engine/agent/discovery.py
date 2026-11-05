"""Graph nodes: inspect_repository, detect_providers. Purely deterministic --
no LLM call -- since provider detection is handled by the Java analyzer's
evidence-based registry (Phase 2), not by model guesswork.
"""
from __future__ import annotations

import logging

from agent.state import AgentState
from schemas.providers import RepositoryAnalysis
from tools.repository_tools import RepositoryAnalysisError, analyze_repository

logger = logging.getLogger("payshift.agent.discovery")


def inspect_repository(state: AgentState) -> dict:
    try:
        analysis = analyze_repository(state["repository_path"])
    except RepositoryAnalysisError as e:
        logger.error("Repository analysis failed: %s", e)
        return {"blocked": True, "blocker_reason": f"Repository analysis failed: {e}"}

    # by_alias=True: downstream nodes (understanding.py) read these dicts using the
    # original camelCase keys from java-analyzer's JSON (paymentOperations, etc.),
    # not Python's snake_case field names -- without by_alias, those lookups would
    # silently return [] via dict.get()'s default instead of raising, which is
    # exactly the bug that produced an empty capability list on the first E2E run.
    return {"repository_analysis": analysis.model_dump(by_alias=True)}


def detect_providers(state: AgentState) -> dict:
    analysis = RepositoryAnalysis.model_validate(state["repository_analysis"])
    existing = analysis.confident_provider_ids()

    errors = list(state.get("errors", []))
    if not existing:
        errors.append(
            "No existing payment provider was detected with sufficient confidence. "
            "Proceeding as a greenfield integration (target provider will be the only provider)."
        )
    return {"existing_providers": existing, "errors": errors}

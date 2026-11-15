"""Graph node: generate_report. Deterministic assembly of the final
IntegrationReport from real state only -- compilation/test results came from
real subprocess runs (tools/java_tools.py), never invented here.

VERIFIED is deliberately strict: the run was not blocked, the deterministic
static checks (if they ran) passed, the project compiled, AND a test run
actually executed at least one test with zero failures/errors against the
final code. Anything short of all of that is not evidence of a working change.
"""
from __future__ import annotations

import logging
from pathlib import Path

from agent.state import AgentState
from llm.client import LLMClient
from schemas.reports import (
    CompilationResult, IntegrationReport, LLMUsageSummary, RepairAttempt, StaticCheckResult, TestRunResult,
    VerificationResult,
)

logger = logging.getLogger("payshift.agent.reporting")


def generate_report(state: AgentState, llm: LLMClient | None = None) -> dict:
    plan = state.get("integration_plan", {}) or {}
    capability_model = plan.get("capability_model", {})

    verification = _build_verification_result(state)
    if verification is not None:
        final_status = verification.final_status
    else:
        final_status = "BLOCKED" if state.get("blocked") else "UNKNOWN"

    unsupported = list(plan.get("unsupported_functionality", []))
    for c in capability_model.get("capabilities", []):
        if c["target_support"] in ("UNSUPPORTED", "REQUIRES_RESEARCH"):
            line = f"{c['operation']}: {c.get('notes') or c['target_support']}"
            if not any(u.startswith(f"{c['operation']}:") for u in unsupported):
                unsupported.append(line)

    known_limitations = list(state.get("errors", []))
    if state.get("blocked"):
        known_limitations.append(f"Run blocked: {state.get('blocker_reason')}")

    applied = state.get("applied_changes") or {}
    report = IntegrationReport(
        operation_mode=state.get("operation_mode", "UNKNOWN"),
        existing_providers=state.get("existing_providers", []),
        target_provider=state.get("target_provider", "UNKNOWN"),
        final_status=final_status,
        architecture_implemented=_describe_architecture(plan),
        files_created=applied.get("created", []),
        files_modified=applied.get("modified", []),
        planned_files_to_create=[f["path"] for f in plan.get("files_to_create", [])],
        planned_files_to_modify=[f["path"] for f in plan.get("files_to_modify", [])],
        verification=verification,
        llm_usage=LLMUsageSummary.model_validate(llm.usage_summary()) if llm is not None else None,
        blocker_reason=state.get("blocker_reason") if state.get("blocked") else None,
        documentation_citations=sorted(set(plan.get("documentation_references", []))),
        unsupported_functionality=unsupported,
        manual_review_items=[m["description"] for m in plan.get("manual_review_items", [])],
        commands_to_run=_commands_to_run(state),
        reproduction_steps=_reproduction_steps(state),
        known_limitations=known_limitations,
        workspace_path=state.get("workspace_path"),
    )

    if state.get("workspace_path"):
        workspace_root = Path(state["workspace_path"]).parent
        try:
            (workspace_root / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        except OSError as e:
            logger.warning("Could not write report.json: %s", e)

    return {"report": report.model_dump(), "final_status": final_status}


def _build_verification_result(state: AgentState) -> VerificationResult | None:
    compilation_raw = state.get("compilation_result")
    static_raw = state.get("static_check_result")
    if compilation_raw is None and static_raw is None:
        return None  # never reached verification (blocked before any code was applied)

    compilation = CompilationResult.model_validate(compilation_raw) if compilation_raw else None
    test_result = TestRunResult.model_validate(state["test_result"]) if state.get("test_result") else None
    static = StaticCheckResult.model_validate(static_raw) if static_raw else None
    repair_attempts = [RepairAttempt.model_validate(a) for a in state.get("repair_attempts", [])]

    verified = (
        not state.get("blocked")
        and (static is None or static.passed)
        and compilation is not None and compilation.success
        and test_result is not None and test_result.success and test_result.tests_run > 0
    )
    return VerificationResult(
        compilation=compilation, tests=test_result, static_checks=static, repair_attempts=repair_attempts,
        final_status="VERIFIED" if verified else "UNRESOLVED_FAILURE",
    )


def _describe_architecture(plan: dict) -> str:
    if not plan:
        return "No plan was produced (run was blocked before planning completed)."
    if plan.get("reuse_existing_abstraction"):
        return (f"Reused existing provider abstraction '{plan.get('abstraction_interface')}'; "
                f"added a new implementation for {plan.get('target_provider')}.")
    return f"Introduced a new provider abstraction to support {plan.get('target_provider')}."


def _commands_to_run(state: AgentState) -> list[str]:
    if not state.get("workspace_path"):
        return []
    return [
        f"cd '{state['workspace_path']}'",
        "mvn -s ../../../settings.xml test",
    ]


def _reproduction_steps(state: AgentState) -> list[str]:
    return [
        f"1. Repository analyzed: {state.get('repository_path')}",
        f"2. Operation mode: {state.get('operation_mode')}; target provider: {state.get('target_provider')}",
        f"3. Workspace: {state.get('workspace_path', 'none created (blocked before code generation)')}",
        "4. Re-run the full pipeline via ai-engine/main.py with the same arguments to reproduce.",
    ]

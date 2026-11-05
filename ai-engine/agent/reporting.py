"""Graph node: generate_report. Deterministic assembly of the final
IntegrationReport from real state only -- compilation/test results came from
real subprocess runs (tools/java_tools.py), never invented here.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from agent.state import AgentState
from schemas.reports import CompilationResult, IntegrationReport, RepairAttempt, TestRunResult, VerificationResult

logger = logging.getLogger("payshift.agent.reporting")


def generate_report(state: AgentState) -> dict:
    plan = state.get("integration_plan", {})
    capability_model = plan.get("capability_model", {})

    verification = _build_verification_result(state)

    unsupported = list(plan.get("unsupported_functionality", []))
    for c in capability_model.get("capabilities", []):
        if c["target_support"] in ("UNSUPPORTED", "REQUIRES_RESEARCH") and c["operation"] not in unsupported:
            unsupported.append(f"{c['operation']}: {c.get('notes') or c['target_support']}")

    known_limitations = list(state.get("errors", []))
    if state.get("blocked"):
        known_limitations.append(f"Run blocked: {state.get('blocker_reason')}")

    doc_citations = sorted(set(plan.get("documentation_references", [])))

    report = IntegrationReport(
        operation_mode=state.get("operation_mode", "UNKNOWN"),
        existing_providers=state.get("existing_providers", []),
        target_provider=state.get("target_provider", "UNKNOWN"),
        architecture_implemented=_describe_architecture(plan),
        files_created=[f["path"] for f in plan.get("files_to_create", [])],
        files_modified=[f["path"] for f in plan.get("files_to_modify", [])],
        verification=verification,
        documentation_citations=doc_citations,
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

    final_status = verification.final_status if verification else ("BLOCKED" if state.get("blocked") else "UNKNOWN")
    return {"report": report.model_dump(), "final_status": final_status}


def _build_verification_result(state: AgentState) -> VerificationResult | None:
    compilation_raw = state.get("compilation_result")
    if compilation_raw is None:
        return None

    compilation = CompilationResult.model_validate(compilation_raw)
    test_result = TestRunResult.model_validate(state["test_result"]) if state.get("test_result") else None

    repair_attempts_raw = state.get("repair_attempts", [])
    repair_attempts = []
    for i, attempt in enumerate(repair_attempts_raw):
        is_last = i == len(repair_attempts_raw) - 1
        attempt = dict(attempt)
        if is_last:
            attempt["recompile_success"] = compilation.success
            attempt["retest_success"] = test_result.success if test_result else None
        else:
            # An earlier attempt was followed by another attempt, so by definition
            # it did not fully resolve the failure.
            attempt["recompile_success"] = attempt.get("recompile_success", True)
            attempt["retest_success"] = False
        repair_attempts.append(RepairAttempt.model_validate(attempt))

    if not compilation.success:
        final_status = "UNRESOLVED_FAILURE"
    elif test_result is not None and not test_result.success:
        final_status = "UNRESOLVED_FAILURE"
    else:
        final_status = "VERIFIED"

    return VerificationResult(
        compilation=compilation, tests=test_result, repair_attempts=repair_attempts, final_status=final_status,
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

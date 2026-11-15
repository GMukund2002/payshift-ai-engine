"""Graph nodes: compile_project, run_tests. Deterministic -- real `mvn`
subprocesses against the workspace's `modified` copy, real surefire XML
parsing. Never fabricated; see tools/java_tools.py.

Both nodes also record their real outcome onto the most recent repair
attempt (if any), so each attempt's recompile/retest result in the report is
what actually happened rather than inferred afterwards.
"""
from __future__ import annotations

import logging

from agent.state import AgentState
from tools.java_tools import compile_project as _compile_project
from tools.java_tools import run_tests as _run_tests

logger = logging.getLogger("payshift.agent.verification")


def compile_project(state: AgentState) -> dict:
    if not state.get("workspace_path"):
        return {"compilation_result": {"success": False, "raw_output_tail": "no workspace to compile", "duration_seconds": 0.0}}
    result = _compile_project(state["workspace_path"])
    update: dict = {"compilation_result": result.model_dump()}
    if not result.success:
        # A test result from before this (failed) compile describes code that no
        # longer exists in the workspace; never let it reach the report.
        update["test_result"] = None
    attempts = _with_last_attempt(state, recompile_success=result.success,
                                  retest_success=None if result.success else False)
    if attempts is not None:
        update["repair_attempts"] = attempts
    return update


def run_tests(state: AgentState) -> dict:
    result = _run_tests(state["workspace_path"])
    update: dict = {"test_result": result.model_dump()}
    attempts = _with_last_attempt(state, retest_success=result.success)
    if attempts is not None:
        update["repair_attempts"] = attempts
    return update


def _with_last_attempt(state: AgentState, **outcome) -> list[dict] | None:
    attempts = state.get("repair_attempts") or []
    if not attempts:
        return None
    attempts = [dict(a) for a in attempts]
    attempts[-1].update(outcome)
    return attempts

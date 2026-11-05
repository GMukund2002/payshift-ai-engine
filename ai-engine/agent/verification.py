"""Graph nodes: compile_project, run_tests. Deterministic -- real `mvn`
subprocesses against the workspace's `modified` copy, real surefire XML
parsing. Never fabricated; see tools/java_tools.py.
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
    return {"compilation_result": result.model_dump()}


def run_tests(state: AgentState) -> dict:
    result = _run_tests(state["workspace_path"])
    return {"test_result": result.model_dump()}

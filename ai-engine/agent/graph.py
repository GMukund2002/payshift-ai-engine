"""Phase 9: the real LangGraph StateGraph wiring all 14 required nodes together,
with conditional routing driven by actual tool/LLM outputs (never hardcoded to
assume a specific provider or a specific outcome).

Routing summary (mirrors the spec's "Conditional Behavior" section):
- Any node that sets state["blocked"] short-circuits straight to generate_report.
- create_plan's hard guardrail (no retrieved docs -> no SUPPORTED claim) and the
  "all operations unsupported" path both flow through the same blocked check.
- generate_code treats "nothing is actionable" as blocked too, so there's one
  single routing rule for "stop unsupported code generation and report it".
- compile_project / run_tests failures route to diagnose_failures -> repair_code
  -> apply_patch -> compile_project, bounded to MAX_REPAIR_ATTEMPTS total passes;
  once exhausted, whatever the last state was flows to generate_report as
  UNRESOLVED_FAILURE (never silently claimed as success).
"""
from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from agent import discovery, generation, planning, repair, reporting, research, understanding, verification
from agent.apply_patch import apply_patch
from agent.state import MAX_REPAIR_ATTEMPTS, AgentState
from llm.client import LLMClient


def _route_blocked(state: AgentState) -> str:
    return "blocked" if state.get("blocked") else "continue"


def _route_after_compile(state: AgentState) -> str:
    compilation = state.get("compilation_result", {})
    if compilation.get("success"):
        return "run_tests"
    if state.get("repair_count", 0) < MAX_REPAIR_ATTEMPTS:
        return "diagnose_failures"
    return "generate_report"


def _route_after_tests(state: AgentState) -> str:
    test_result = state.get("test_result", {})
    if test_result.get("success"):
        return "generate_report"
    if state.get("repair_count", 0) < MAX_REPAIR_ATTEMPTS:
        return "diagnose_failures"
    return "generate_report"


def build_graph(llm: LLMClient):
    graph = StateGraph(AgentState)

    graph.add_node("inspect_repository", discovery.inspect_repository)
    graph.add_node("detect_providers", discovery.detect_providers)
    graph.add_node("understand_architecture", partial(understanding.understand_architecture, llm=llm))
    graph.add_node("build_payment_ir", understanding.build_payment_ir)
    graph.add_node("research_provider", research.research_provider)
    graph.add_node("retrieve_documentation", research.retrieve_documentation)
    graph.add_node("create_plan", partial(planning.create_plan, llm=llm))
    graph.add_node("generate_code", partial(generation.generate_code, llm=llm))
    graph.add_node("apply_patch", apply_patch)
    graph.add_node("compile_project", verification.compile_project)
    graph.add_node("run_tests", verification.run_tests)
    graph.add_node("diagnose_failures", partial(repair.diagnose_failures, llm=llm))
    graph.add_node("repair_code", partial(repair.repair_code, llm=llm))
    graph.add_node("generate_report", reporting.generate_report)

    graph.add_edge(START, "inspect_repository")
    graph.add_conditional_edges("inspect_repository", _route_blocked,
                                 {"blocked": "generate_report", "continue": "detect_providers"})
    graph.add_edge("detect_providers", "understand_architecture")
    graph.add_conditional_edges("understand_architecture", _route_blocked,
                                 {"blocked": "generate_report", "continue": "build_payment_ir"})
    graph.add_edge("build_payment_ir", "research_provider")
    graph.add_edge("research_provider", "retrieve_documentation")
    graph.add_edge("retrieve_documentation", "create_plan")
    graph.add_conditional_edges("create_plan", _route_blocked,
                                 {"blocked": "generate_report", "continue": "generate_code"})
    graph.add_conditional_edges("generate_code", _route_blocked,
                                 {"blocked": "generate_report", "continue": "apply_patch"})
    graph.add_edge("apply_patch", "compile_project")
    graph.add_conditional_edges("compile_project", _route_after_compile,
                                 {"run_tests": "run_tests", "diagnose_failures": "diagnose_failures",
                                  "generate_report": "generate_report"})
    graph.add_conditional_edges("run_tests", _route_after_tests,
                                 {"generate_report": "generate_report", "diagnose_failures": "diagnose_failures"})
    graph.add_conditional_edges("diagnose_failures", _route_blocked,
                                 {"blocked": "generate_report", "continue": "repair_code"})
    graph.add_conditional_edges("repair_code", _route_blocked,
                                 {"blocked": "generate_report", "continue": "apply_patch"})
    graph.add_edge("generate_report", END)

    return graph.compile()

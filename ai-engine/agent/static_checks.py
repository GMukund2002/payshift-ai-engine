"""Graph node: static_checks (deterministic, no LLM).

Runs between apply_patch and compile_project. Catches defects that compile
cleanly but break the application at startup or leave it hollow -- exactly
the failure classes a real LLM produced in live runs:

- missing_bean / ambiguous_bean: a constructor dependency no bean provides
  (an injected RestTemplate), or a second bean for an existing interface;
  the Spring ApplicationContext fails and EVERY test errors, including the
  existing provider's -- the run-5/run-6/3fe329852a5d failure mode.
- unresolved_placeholder: @Value("${key}") with no default and no key in
  application.yml (README run 6).
- stub_method: methods that only log / return null / "implement this".
  Tests can't catch these (nothing exercises the new provider for real), so
  without this check a hollow integration could be reported VERIFIED.
- unimplemented_interface: a new port with nothing implementing it.

These are checked in code by java-analyzer's WiringChecker (JavaParser AST),
not by asking an LLM. A failure here routes to the same diagnose -> repair
loop as a compile failure, with its own small budget, and costs about a
second instead of a multi-minute Maven run.

If the checker itself can't run, the node records a WARNING and lets the run
continue: compile + tests remain the authoritative gate, so a checker outage
degrades the run's diagnostics, never its correctness.
"""
from __future__ import annotations

import logging

from pathlib import Path

from agent.apply_patch import is_test_source_path
from agent.state import AgentState
from tools.compile_diagnostics import fix_misimports
from tools.java_tools import _run_maven
from tools.repository_tools import RepositoryAnalysisError, check_wiring

logger = logging.getLogger("payshift.agent.static_checks")


def static_checks(state: AgentState) -> dict:
    workspace = state.get("workspace_path")
    changed = [p for p in state.get("touched_paths", [])
               if p.endswith(".java") and not is_test_source_path(p)]
    if not workspace or not changed:
        return {"static_check_result": {"passed": True, "findings": []}}

    # Deterministic import correction first (cheap, IDE-style; recorded in the report).
    try:
        import_fixes = fix_misimports(Path(workspace), changed, _run_maven)
    except Exception:  # best effort: the compile step still reports any import it couldn't fix
        logger.warning("Import correction failed; continuing", exc_info=True)
        import_fixes = []
    fixed = [{"check": "auto_fixed_import", "severity": "INFO", "file": f["file"], "line": None,
              "message": f"Rewrote import {f['from']} -> {f['to']} (the only class of that name in the project "
                         f"or on its classpath)."} for f in import_fixes]

    try:
        raw = check_wiring(workspace, changed)
    except RepositoryAnalysisError as e:
        logger.warning("Static checks could not run; continuing to compile/test: %s", e)
        return {"static_check_result": {"passed": True, "findings": fixed + [{
            "check": "checker_unavailable", "severity": "WARNING", "file": "", "line": None,
            "message": f"Deterministic wiring checks could not run: {e}",
        }]}}

    findings = fixed + [
        {"check": f.get("check", ""), "severity": f.get("severity", "ERROR"), "file": f.get("file", ""),
         "line": f.get("line"), "message": f.get("message", "")}
        for f in raw.get("findings", [])
    ]
    for err in raw.get("errors", []):
        findings.append({"check": "checker_warning", "severity": "WARNING", "file": "", "line": None, "message": err})
    passed = bool(raw.get("passed", True))

    update: dict = {"static_check_result": {"passed": passed, "findings": findings}}
    if not passed:
        # Any earlier compile/test result describes code that has since changed.
        update["compilation_result"] = None
        update["test_result"] = None
    attempts = state.get("repair_attempts") or []
    if attempts and attempts[-1].get("kind") == "static":
        attempts = [dict(a) for a in attempts]
        attempts[-1]["static_checks_passed"] = passed
        update["repair_attempts"] = attempts
    return update

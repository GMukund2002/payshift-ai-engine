"""Deterministic Maven/JUnit execution (Phase 10/11). Financial-correctness and
compilation verification are never delegated to the LLM -- these functions run
real subprocesses and parse real output.
"""
from __future__ import annotations

import logging
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from schemas.reports import CompilationResult, TestCaseResult, TestRunResult

logger = logging.getLogger("payshift.tools.java")

AI_ENGINE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = AI_ENGINE_ROOT.parent
MAVEN_SETTINGS = REPO_ROOT / "settings.xml"
MAVEN_BUILD_TIMEOUT_SECONDS = 300


def _run_maven(project_dir: Path, goals: list[str], timeout_seconds: int) -> tuple[int, str, float]:
    cmd = ["mvn"]
    if MAVEN_SETTINGS.exists():
        cmd += ["-s", str(MAVEN_SETTINGS)]
    cmd += goals
    logger.info("Running in %s: %s", project_dir, " ".join(cmd))
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd, cwd=project_dir, capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
        duration = time.monotonic() - start
        return result.returncode, result.stdout + "\n" + result.stderr, duration
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - start
        output = (e.stdout or "") + "\n" + (e.stderr or "")
        return 124, output + f"\n[TIMED OUT after {timeout_seconds}s]", duration


def compile_project(project_dir: Path | str) -> CompilationResult:
    project_dir = Path(project_dir)
    code, output, duration = _run_maven(project_dir, ["-q", "-DskipTests", "compile"], MAVEN_BUILD_TIMEOUT_SECONDS)
    return CompilationResult(success=code == 0, raw_output_tail=output[-4000:], duration_seconds=duration)


def run_tests(project_dir: Path | str, test_class: str | None = None) -> TestRunResult:
    project_dir = Path(project_dir)
    goals = ["-q", "test"]
    if test_class:
        goals = ["-q", f"-Dtest={test_class}", "test"]
    code, output, duration = _run_maven(project_dir, goals, MAVEN_BUILD_TIMEOUT_SECONDS)

    cases, totals = _parse_surefire_reports(project_dir)
    success = code == 0 and totals["failures"] == 0 and totals["errors"] == 0

    return TestRunResult(
        success=success,
        tests_run=totals["tests"],
        failures=totals["failures"],
        errors=totals["errors"],
        skipped=totals["skipped"],
        cases=cases,
        raw_output_tail=output[-4000:],
        duration_seconds=duration,
    )


def _parse_surefire_reports(project_dir: Path) -> tuple[list[TestCaseResult], dict[str, int]]:
    reports_dir = project_dir / "target" / "surefire-reports"
    cases: list[TestCaseResult] = []
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if not reports_dir.is_dir():
        return cases, totals

    for xml_file in sorted(reports_dir.glob("TEST-*.xml")):
        try:
            tree = ET.parse(xml_file)
        except ET.ParseError as e:
            logger.warning("Could not parse surefire report %s: %s", xml_file, e)
            continue
        root = tree.getroot()
        totals["tests"] += int(root.attrib.get("tests", 0))
        totals["failures"] += int(root.attrib.get("failures", 0))
        totals["errors"] += int(root.attrib.get("errors", 0))
        totals["skipped"] += int(root.attrib.get("skipped", 0))

        for testcase in root.findall("testcase"):
            name = f"{testcase.attrib.get('classname', '')}.{testcase.attrib.get('name', '')}"
            failure = testcase.find("failure")
            error = testcase.find("error")
            skipped = testcase.find("skipped")
            if failure is not None:
                cases.append(TestCaseResult(name=name, status="FAILED", message=failure.attrib.get("message")))
            elif error is not None:
                cases.append(TestCaseResult(name=name, status="ERROR", message=error.attrib.get("message")))
            elif skipped is not None:
                cases.append(TestCaseResult(name=name, status="SKIPPED"))
            else:
                cases.append(TestCaseResult(name=name, status="PASSED"))

    return cases, totals

"""Checks applied to a finished run's workspace that the pipeline never sees.

A run's own verification (static checks + compile + the app's existing tests)
can be satisfied by a change that doesn't actually integrate the target
provider -- live run f0d9df91493b did exactly that. These checks are how the
evaluation measures the false-VERIFIED rate, the number that matters most to a
buyer: how often does "VERIFIED" not mean "the new provider is really there"?

None of these are visible to, or tunable by, the generation/repair prompts.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from evaluation.corpus import PROVIDER_EVIDENCE, EvalCase
from tools.java_tools import run_tests

HIDDEN_TEST_CLASS = "PayShiftHiddenWiringCheckTest"

_HIDDEN_TEST_TEMPLATE = """package {package};

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.config.ConfigurableListableBeanFactory;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.stereotype.Controller;

import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertFalse;

/**
 * Injected by PayShift's evaluation harness after the run; never shown to the pipeline.
 * Boots the real application context and requires a bean for the target provider that
 * is actually reachable: some other bean depends on it, or it is itself a controller.
 */
@SpringBootTest
class {cls} {{

    @Autowired
    ConfigurableApplicationContext context;

    @Test
    void targetProviderIntegrationIsWiredAndReachable() {{
        ConfigurableListableBeanFactory beans = context.getBeanFactory();
        List<String> providerBeans = Arrays.stream(context.getBeanDefinitionNames())
                .filter(n -> {{
                    Class<?> type = context.getType(n);
                    return type != null && type.getName().toLowerCase().contains("{provider}")
                            && !AnnotatedElementUtils.hasAnnotation(type, Configuration.class);
                }})
                .toList();
        assertFalse(providerBeans.isEmpty(), "no bean whose class mentions '{provider}' is registered");
        List<String> reachable = providerBeans.stream()
                .filter(n -> beans.getDependentBeans(n).length > 0
                        || AnnotatedElementUtils.hasAnnotation(context.getType(n), Controller.class))
                .toList();
        assertFalse(reachable.isEmpty(), "'{provider}' beans exist but nothing depends on them: " + providerBeans);
    }}
}}
"""


@dataclass
class HiddenCheckResult:
    context_has_provider_bean: bool | None = None   # None: not run (code never compiled)
    provider_evidence_in_code: bool = False
    evidence_found: list[str] = field(default_factory=list)
    existing_tests_preserved: bool | None = None
    new_provider_test_files: list[str] = field(default_factory=list)
    hidden_test_output_tail: str = ""

    @property
    def integration_is_real(self) -> bool:
        return bool(self.context_has_provider_bean) and self.provider_evidence_in_code

    def to_dict(self) -> dict:
        d = asdict(self)
        d["integration_is_real"] = self.integration_is_real
        return d


def run_hidden_checks(case: EvalCase, final_state: dict) -> HiddenCheckResult:
    result = HiddenCheckResult()
    workspace = final_state.get("workspace_path")
    applied = final_state.get("applied_changes") or {}
    changed = list(applied.get("created", [])) + list(applied.get("modified", []))
    if not workspace or not Path(workspace).is_dir():
        return result
    workspace = Path(workspace)

    # 1. Does the changed production code reference the provider at all?
    patterns = PROVIDER_EVIDENCE.get(case.target_provider, [case.target_provider])
    for rel in changed:
        if "src/test/" in rel or not rel.endswith((".java", ".yml", ".yaml", ".properties")):
            continue
        text = (workspace / rel).read_text(encoding="utf-8", errors="replace") if (workspace / rel).is_file() else ""
        result.evidence_found += [f"{rel}: {p}" for p in patterns if p in text]
    result.provider_evidence_in_code = bool(result.evidence_found)

    # 2. New tests that mention the provider (informational: did the change test itself?).
    provider_re = re.compile(re.escape(case.target_provider), re.IGNORECASE)
    for rel in applied.get("created", []):
        if "src/test/" in rel and (workspace / rel).is_file() and provider_re.search((workspace / rel).read_text(
                encoding="utf-8", errors="replace")):
            result.new_provider_test_files.append(rel)

    # 3. Did every original test still run and pass in the run's final test pass?
    tests = final_state.get("test_result") or {}
    if tests:
        original = [c for c in tests.get("cases", []) if HIDDEN_TEST_CLASS not in c.get("name", "")]
        result.existing_tests_preserved = (
            tests.get("tests_run", 0) >= case.baseline_tests
            and all(c["status"] in ("PASSED", "SKIPPED") for c in original)
        )

    # 4. Boot the real context with the change applied and look for the provider's bean.
    compiled = (final_state.get("compilation_result") or {}).get("success")
    if compiled:
        result.context_has_provider_bean, result.hidden_test_output_tail = _run_hidden_context_test(case, workspace)
    return result


def _run_hidden_context_test(case: EvalCase, workspace: Path) -> tuple[bool, str]:
    test_dir = workspace / "src" / "test" / "java" / Path(*case.base_package.split("."))
    test_file = test_dir / f"{HIDDEN_TEST_CLASS}.java"
    reports = workspace / "target" / "surefire-reports"
    backup = workspace.parent / "surefire-reports.run"
    try:
        # Keep the run's own surefire reports intact for anyone inspecting the workspace.
        if reports.is_dir():
            shutil.rmtree(backup, ignore_errors=True)
            shutil.copytree(reports, backup)
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file.write_text(_HIDDEN_TEST_TEMPLATE.format(
            package=case.base_package, cls=HIDDEN_TEST_CLASS, provider=case.target_provider.lower()), encoding="utf-8")
        outcome = run_tests(workspace, test_class=HIDDEN_TEST_CLASS)
        # The JUnit assertion message (why it failed) lives in the surefire report,
        # not in Maven's quiet console output.
        reasons = [f"{c.status}: {c.message}" for c in outcome.cases
                   if HIDDEN_TEST_CLASS in c.name and c.status != "PASSED" and c.message]
        detail = "\n".join(reasons) or outcome.raw_output_tail[-1500:]
        return outcome.success and outcome.tests_run >= 1, detail
    finally:
        test_file.unlink(missing_ok=True)
        if backup.is_dir():
            shutil.rmtree(reports, ignore_errors=True)
            shutil.copytree(backup, reports)
            shutil.rmtree(backup, ignore_errors=True)

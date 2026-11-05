"""Integration tests for the subprocess tool wrappers. These run REAL
subprocesses (the java-analyzer jar, real `mvn test`) against the sample
app -- no mocking -- so a pass means the Python<->Java process boundary
genuinely works end to end.
"""
from pathlib import Path

from tools.java_tools import compile_project, run_tests
from tools.repository_tools import analyze_repository

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERCHANT_APP = REPO_ROOT / "sample-apps" / "merchant-app"


def test_analyze_repository_against_sample_app():
    analysis = analyze_repository(MERCHANT_APP)
    assert "stripe" in analysis.confident_provider_ids()
    assert analysis.architecture.provider_abstraction_exists is True
    assert len(analysis.payment_operations) > 0


def test_compile_sample_app_succeeds():
    result = compile_project(MERCHANT_APP)
    assert result.success is True, result.raw_output_tail


def test_run_tests_against_sample_app_all_pass():
    result = run_tests(MERCHANT_APP)
    assert result.success is True, result.raw_output_tail
    assert result.tests_run >= 9
    assert result.failures == 0
    assert result.errors == 0
    assert all(c.status == "PASSED" for c in result.cases)

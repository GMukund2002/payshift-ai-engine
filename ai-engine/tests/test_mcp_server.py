from pathlib import Path

import pytest

from tools.mcp_server import (
    UnapprovedPathError,
    discover_payment_providers,
    get_integration_report,
    get_payment_capabilities,
    inspect_repository,
    read_repository_file,
    run_java_tests,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERCHANT_APP = REPO_ROOT / "sample-apps" / "merchant-app"


def test_inspect_repository_tool():
    result = inspect_repository(str(MERCHANT_APP))
    assert "error" not in result
    assert any(p["name"] == "stripe" for p in result["detectedProviders"])


def test_discover_payment_providers_tool():
    result = discover_payment_providers(str(MERCHANT_APP))
    assert "stripe" in result["confident_provider_ids"]


def test_get_payment_capabilities_tool():
    result = get_payment_capabilities(str(MERCHANT_APP), "razorpay")
    assert result["target_provider"] == "razorpay"
    assert len(result["capabilities"]) > 0
    assert all(c["target_support"] == "REQUIRES_RESEARCH" for c in result["capabilities"])


def test_run_java_tests_tool():
    result = run_java_tests(str(MERCHANT_APP))
    assert result["success"] is True
    assert result["tests_run"] >= 9


def test_read_repository_file_tool():
    content = read_repository_file(str(MERCHANT_APP), "pom.xml")
    assert "<artifactId>merchant-app</artifactId>" in content


def test_read_repository_file_rejects_path_traversal():
    content = read_repository_file(str(MERCHANT_APP), "../../../etc/passwd")
    assert content.startswith("ERROR")


def test_tools_reject_unapproved_paths():
    with pytest.raises(UnapprovedPathError):
        inspect_repository("/etc")


def test_get_integration_report_missing_returns_error():
    result = get_integration_report(str(REPO_ROOT / "workspaces"))
    assert "error" in result

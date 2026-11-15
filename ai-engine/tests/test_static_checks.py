"""Deterministic pre-compile checks, end to end through the real java-analyzer
jar and (for the graph test) real Maven.

The stub below is the exact shape gpt-4o generated in live run 3fe329852a5d:
a gateway that injects a RestTemplate no bean provides, uses @Value
placeholders with no defaults, and whose methods only log next to an
"Implement the logic..." comment. That run compiled, then failed every
existing test at Spring startup and burned both repair attempts without
finding the cause. These tests prove the checks now name each defect
before compile, and that the repair loop can act on them.
"""
import json
import socket
import uuid
from pathlib import Path

import pytest

from agent.apply_patch import apply_patch
from agent.graph import build_graph
from agent.static_checks import static_checks
from tests.fakes import FakeLLMClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERCHANT_APP = REPO_ROOT / "sample-apps" / "merchant-app"
GOOD_FILES = json.loads((Path(__file__).parent / "fixtures" / "razorpay_add_psp_files.json").read_text())
GATEWAY = "src/main/java/com/payshift/merchant/provider/RazorpayApiPaymentGateway.java"
PORT = "src/main/java/com/payshift/merchant/provider/RazorpayPaymentGateway.java"

LIVE_RUN_STUB = """package com.payshift.merchant.provider;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.math.BigDecimal;

@Component
public class RazorpayApiPaymentGateway implements RazorpayPaymentGateway {

    private static final Logger logger = LoggerFactory.getLogger(RazorpayApiPaymentGateway.class);

    private final RestTemplate restTemplate;

    @Value("${razorpay.api.key}")
    private String apiKey;

    @Value("${razorpay.api.secret}")
    private String apiSecret;

    public RazorpayApiPaymentGateway(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @Override
    public ProviderOrderResult createOrder(String orderReference, BigDecimal amount, String currency) {
        String url = "https://api.razorpay.com/v1/orders";
        // Implement the logic to call Razorpay API and create an order
        logger.info("Creating order {}", orderReference);
        return null;
    }

    @Override
    public ProviderRefundResult createRefund(String paymentId, BigDecimal amount) {
        String url = String.format("https://api.razorpay.com/v1/payments/%s/refund", paymentId);
        // Implement the logic to call Razorpay API and create a refund
        logger.info("Creating refund for payment ID: {}", paymentId);
        return null;
    }
}
"""


def _files_with_stub_gateway():
    return [{"path": f["path"], "content": LIVE_RUN_STUB if f["path"] == GATEWAY else f["content"]}
            for f in GOOD_FILES]


def _apply(files):
    state = {"repository_path": str(MERCHANT_APP), "run_id": "sc-" + uuid.uuid4().hex[:8], "pending_patch": files}
    state.update(apply_patch(state))
    return state


def test_live_run_stub_is_caught_before_compile_with_each_defect_named():
    state = _apply(_files_with_stub_gateway())
    result = static_checks(state)["static_check_result"]

    assert result["passed"] is False
    errors = [f for f in result["findings"] if f["severity"] == "ERROR"]
    by_check = {}
    for f in errors:
        by_check.setdefault(f["check"], []).append(f)
    assert {f["file"] for f in errors} == {GATEWAY}
    assert "RestTemplate" in by_check["missing_bean"][0]["message"]
    assert len(by_check["unresolved_placeholder"]) == 2
    assert {m["message"].split("(")[0] for m in by_check["stub_method"]} == {
        "RazorpayApiPaymentGateway.createOrder", "RazorpayApiPaymentGateway.createRefund"}


def test_hand_validated_integration_passes_the_checks():
    state = _apply(GOOD_FILES)
    result = static_checks(state)["static_check_result"]
    assert result["passed"] is True
    assert not [f for f in result["findings"] if f["severity"] == "ERROR"]


def test_failing_checks_clear_stale_build_results():
    state = _apply(_files_with_stub_gateway())
    state["compilation_result"] = {"success": True, "raw_output_tail": "", "duration_seconds": 1.0}
    update = static_checks(state)
    assert update["compilation_result"] is None and update["test_result"] is None


# ---------------------------------------------------------------- full graph

def _has_network() -> bool:
    try:
        socket.create_connection(("razorpay.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _has_network(), reason="no network access in this environment")
def test_graph_repairs_a_static_check_failure_then_verifies_for_real():
    from tests.test_graph_end_to_end import ARCHITECTURE_FINDINGS_RESPONSE, _plan_response

    stubbed = _files_with_stub_gateway()
    good_gateway = next(f for f in GOOD_FILES if f["path"] == GATEWAY)

    def responder(system_prompt: str, user_prompt: str) -> str:
        if "principal software architect" in system_prompt:
            return ARCHITECTURE_FINDINGS_RESPONSE
        if "planning a Java payment-provider integration" in system_prompt:
            return _plan_response()
        if "senior Java backend engineer" in system_prompt:
            return json.dumps({"files": stubbed})
        if "diagnosing a failed verification" in system_prompt:
            assert "STATIC CHECK FAILURES" in user_prompt and "RestTemplate" in user_prompt
            return json.dumps({"diagnosis_summary": "Gateway injects an undefined RestTemplate bean, has unresolved "
                                                    "@Value placeholders and stub methods.",
                               "likely_cause": "placeholder implementation", "confidence": "HIGH",
                               "files_to_inspect": [GATEWAY], "doc_query": None})
        if "fixing a specific, diagnosed defect" in system_prompt:
            return json.dumps({"patch_description": "Real REST implementation with defaulted config.",
                               "files": [good_gateway]})
        raise AssertionError(f"Unexpected system prompt: {system_prompt[:80]}")

    llm = FakeLLMClient(responder=responder)
    final = build_graph(llm).invoke({
        "repository_path": str(MERCHANT_APP), "operation_mode": "ADD_PSP", "target_provider": "razorpay",
        "target_provider_doc_url": None, "run_id": "sc-graph-" + uuid.uuid4().hex[:8],
    }, config={"recursion_limit": 60})

    assert final["final_status"] == "VERIFIED", final.get("report")
    assert final.get("static_repair_count") == 1
    assert final.get("repair_count", 0) == 0          # the build budget was never touched
    attempt = final["report"]["verification"]["repair_attempts"][0]
    assert attempt["kind"] == "static" and attempt["static_checks_passed"] is True
    assert final["test_result"]["tests_run"] == 11 and final["test_result"]["success"] is True
    assert PORT in final["report"]["files_created"]

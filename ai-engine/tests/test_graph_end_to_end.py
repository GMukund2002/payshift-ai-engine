"""End-to-end test of the full LangGraph pipeline (Phase 9): inspect_repository
through generate_report, for a real ADD_PSP run (add Razorpay alongside the
sample app's existing Stripe integration).

Everything deterministic is 100% real: the Java analyzer subprocess, the live
RAG fetch+retrieval against Razorpay's actual docs, apply_patch's workspace
isolation, and real `mvn compile`/`mvn test` runs. The three LLM calls
(understand_architecture, create_plan, generate_code) are scripted via
FakeLLMClient with hand-validated Java file contents -- the same 7 files
were already proven, outside this test, to compile and pass 11/11 tests
against the real sample app. This test proves the GRAPH wiring (routing,
state threading, bounded repair) actually drives that real verification
correctly, not just that the files happen to work in isolation.
"""
import json
import socket
import uuid
from pathlib import Path

import pytest

from agent.graph import build_graph
from tests.fakes import FakeLLMClient

GENERATED_FILES_FIXTURE = Path(__file__).parent / "fixtures" / "razorpay_add_psp_files.json"

REPO_ROOT_MARKER = "principal software architect"
PLAN_MARKER = "planning a Java payment-provider integration"
GENERATE_MARKER = "senior Java backend engineer"


def _has_network() -> bool:
    try:
        socket.create_connection(("razorpay.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


requires_network = pytest.mark.skipif(not _has_network(), reason="no network access in this environment")

MERCHANT_APP = __file__.rsplit("/ai-engine/", 1)[0] + "/sample-apps/merchant-app"

ARCHITECTURE_FINDINGS_RESPONSE = json.dumps({
    "summary": "A Spring Boot merchant app with payment creation, webhook handling, and refunds, "
               "coupled directly to a Stripe gateway interface with no generic provider abstraction in use.",
    "payment_creation_flow": "PaymentService.createPayment calls StripePaymentGateway.createPaymentIntent and persists a Payment.",
    "webhook_flow": "WebhookController -> WebhookService.verifySignature/processEvent, idempotent via ProcessedWebhookEvent.",
    "refund_flow": "PaymentService.refund validates refundable amount then calls StripePaymentGateway.createRefund.",
    "provider_abstraction_assessment": "StripePaymentGateway is Stripe-specific; no shared interface exists for other providers.",
    "coupling_risk": "MEDIUM",
    "refactoring_recommended": False,
    "file_references": ["src/main/java/com/payshift/merchant/service/PaymentService.java"],
})

_ALL_OPERATIONS = [
    "CREATE_PAYMENT", "GET_PAYMENT_STATUS", "CREATE_REFUND",
    "HANDLE_WEBHOOK", "VERIFY_WEBHOOK_SIGNATURE", "FULFILL_ORDER",
]


def _plan_response() -> str:
    decisions = []
    for op in _ALL_OPERATIONS:
        if op == "FULFILL_ORDER":
            decisions.append({"operation": op, "target_support": "REQUIRES_RESEARCH", "target_api": None,
                               "notes": "Internal business logic, not a provider API capability."})
        else:
            decisions.append({"operation": op, "target_support": "SUPPORTED",
                               "target_api": "Razorpay Orders/Payments API", "notes": "Documented."})
    return json.dumps({
        "capability_decisions": decisions,
        "reuse_existing_abstraction": False,
        "abstraction_interface": None,
        "required_changes": [
            "Add Razorpay as an additional PSP without modifying the existing Stripe integration",
            "Reuse the existing Order/Payment/Refund domain model with provider='razorpay'",
        ],
        "files_to_create": [
            {"path": "src/main/java/com/payshift/merchant/provider/RazorpayPaymentGateway.java", "reason": "port", "change_type": "CREATE"},
            {"path": "src/main/java/com/payshift/merchant/provider/RazorpayApiPaymentGateway.java", "reason": "REST client impl", "change_type": "CREATE"},
            {"path": "src/main/java/com/payshift/merchant/service/RazorpayPaymentService.java", "reason": "business logic", "change_type": "CREATE"},
            {"path": "src/main/java/com/payshift/merchant/controller/RazorpayPaymentController.java", "reason": "API", "change_type": "CREATE"},
            {"path": "src/main/java/com/payshift/merchant/service/RazorpayWebhookService.java", "reason": "webhook handling", "change_type": "CREATE"},
            {"path": "src/main/java/com/payshift/merchant/controller/RazorpayWebhookController.java", "reason": "webhook API", "change_type": "CREATE"},
            {"path": "src/test/java/com/payshift/merchant/RazorpayPaymentFlowIntegrationTest.java", "reason": "tests", "change_type": "CREATE"},
        ],
        "files_to_modify": [],
        "security_requirements": ["Verify Razorpay webhook signatures via HMAC-SHA256 over the raw body"],
        "unsupported_functionality": [],
        "testing_requirements": ["New RazorpayPaymentFlowIntegrationTest covers payment creation and cross-provider refund rejection"],
        "manual_review_items": [{"description": "Unify refund routing across providers",
                                  "reason": "Caller currently must know which provider's endpoint owns a payment"}],
        "cutover_checklist": [],
        "preserved_historical_ownership_note": None,
    })


def _make_fake_llm() -> FakeLLMClient:
    generated_files = json.loads(GENERATED_FILES_FIXTURE.read_text())

    def responder(system_prompt: str, user_prompt: str) -> str:
        if REPO_ROOT_MARKER in system_prompt:
            return ARCHITECTURE_FINDINGS_RESPONSE
        if PLAN_MARKER in system_prompt:
            return _plan_response()
        if GENERATE_MARKER in system_prompt:
            return json.dumps({"files": generated_files})
        raise AssertionError(f"Unexpected system prompt: {system_prompt[:80]}")

    return FakeLLMClient(responder=responder)


@requires_network
def test_full_add_psp_pipeline_end_to_end():
    llm = _make_fake_llm()
    graph = build_graph(llm)

    run_id = "e2e-" + uuid.uuid4().hex[:8]
    initial_state = {
        "repository_path": MERCHANT_APP,
        "operation_mode": "ADD_PSP",
        "target_provider": "razorpay",
        "target_provider_doc_url": None,
        "run_id": run_id,
    }

    final_state = graph.invoke(initial_state, config={"recursion_limit": 50})

    assert final_state.get("blocked") is not True, final_state.get("blocker_reason")
    assert final_state["existing_providers"] == ["stripe"]

    compilation = final_state["compilation_result"]
    assert compilation["success"] is True, compilation["raw_output_tail"]

    tests = final_state["test_result"]
    assert tests["success"] is True, tests["raw_output_tail"]
    assert tests["tests_run"] == 11
    assert tests["failures"] == 0
    assert tests["errors"] == 0

    # No repair needed since the scripted generation compiles clean on the first pass.
    assert final_state.get("repair_count", 0) == 0

    report = final_state["report"]
    assert report["verification"]["final_status"] == "VERIFIED"
    assert len(report["files_created"]) == 7
    assert report["files_modified"] == []  # fully additive -- existing Stripe code untouched
    assert final_state["final_status"] == "VERIFIED"

    # The existing Stripe regression tests are in the passing set, proving the
    # existing provider's behavior was preserved, not just "not deleted".
    case_names = {c["name"] for c in tests["cases"]}
    assert any("PaymentFlowIntegrationTest" in n for n in case_names)
    assert any("RazorpayPaymentFlowIntegrationTest" in n for n in case_names)

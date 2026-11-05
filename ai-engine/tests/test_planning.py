import json

from agent.planning import create_plan
from tests.fakes import FakeLLMClient


def _base_state():
    return {
        "operation_mode": "ADD_PSP",
        "existing_providers": ["stripe"],
        "target_provider": "razorpay",
        "architecture_findings": {"summary": "stripe-coupled app"},
        "capability_model": {
            "operation_mode": "ADD_PSP",
            "existing_providers": ["stripe"],
            "target_provider": "razorpay",
            "capabilities": [
                {"operation": "CREATE_PAYMENT", "business_intent": "collect_customer_payment",
                 "source_api": "stripe:PaymentService.createPayment", "target_support": "REQUIRES_RESEARCH",
                 "target_api": None, "documentation_refs": [], "notes": None},
                {"operation": "CREATE_REFUND", "business_intent": "issue_refund",
                 "source_api": "stripe:PaymentService.refund", "target_support": "REQUIRES_RESEARCH",
                 "target_api": None, "documentation_refs": [], "notes": None},
            ],
            "currency_support": [], "idempotency_strategy": None,
            "manual_review_required": [], "unresolved_operations": ["CREATE_PAYMENT", "CREATE_REFUND"],
        },
        "documentation_indexed": {"blocked": False},
        "retrieved_passages": {
            "CREATE_PAYMENT": [{"text": "POST /v1/payments creates a payment", "source_url": "https://razorpay.com/docs/api/payments/",
                                 "title": "Payments API", "trust_level": "OFFICIAL_VERIFIED", "code_block": False, "distance": 0.1}],
            "CREATE_REFUND": [],  # deliberately empty: no documentation retrieved for refunds
        },
    }


def test_overrides_supported_claim_with_no_retrieved_passages():
    """The model (wrongly) claims CREATE_REFUND is SUPPORTED even though zero
    passages were retrieved for it. The guardrail must downgrade this -- it's
    exactly the 'do not invent undocumented methods' rule enforced in code."""
    fake_response = json.dumps({
        "capability_decisions": [
            {"operation": "CREATE_PAYMENT", "target_support": "SUPPORTED", "target_api": "POST /v1/payments", "notes": "documented"},
            {"operation": "CREATE_REFUND", "target_support": "SUPPORTED", "target_api": "POST /v1/payments/{id}/refund", "notes": "should work"},
        ],
        "reuse_existing_abstraction": True,
        "abstraction_interface": "StripePaymentGateway",
        "required_changes": ["Add RazorpayPaymentGateway"],
        "files_to_create": [{"path": "RazorpayPaymentGateway.java", "reason": "new adapter", "change_type": "CREATE"}],
        "files_to_modify": [],
        "security_requirements": [], "unsupported_functionality": [], "testing_requirements": [],
        "manual_review_items": [], "cutover_checklist": [], "preserved_historical_ownership_note": None,
    })
    llm = FakeLLMClient(responses=[fake_response])

    result = create_plan(_base_state(), llm)

    cap_by_op = {c["operation"]: c for c in result["capability_model"]["capabilities"]}
    assert cap_by_op["CREATE_PAYMENT"]["target_support"] == "SUPPORTED"
    assert cap_by_op["CREATE_REFUND"]["target_support"] == "REQUIRES_RESEARCH"
    assert "overridden" in cap_by_op["CREATE_REFUND"]["notes"]


def test_strips_modification_to_protected_test_file():
    fake_response = json.dumps({
        "capability_decisions": [
            {"operation": "CREATE_PAYMENT", "target_support": "SUPPORTED", "target_api": "POST /v1/payments", "notes": "ok"},
            {"operation": "CREATE_REFUND", "target_support": "REQUIRES_RESEARCH", "target_api": None, "notes": "no docs"},
        ],
        "reuse_existing_abstraction": True,
        "abstraction_interface": "StripePaymentGateway",
        "required_changes": [],
        "files_to_create": [],
        "files_to_modify": [
            {"path": "src/test/java/com/payshift/merchant/PaymentFlowIntegrationTest.java",
             "reason": "make the test pass", "change_type": "MODIFY"},
            {"path": "src/main/java/com/payshift/merchant/service/PaymentService.java",
             "reason": "route to new provider", "change_type": "MODIFY"},
        ],
        "security_requirements": [], "unsupported_functionality": [], "testing_requirements": [],
        "manual_review_items": [], "cutover_checklist": [], "preserved_historical_ownership_note": None,
    })
    llm = FakeLLMClient(responses=[fake_response])

    result = create_plan(_base_state(), llm)

    plan = result["integration_plan"]
    modified_paths = [f["path"] for f in plan["files_to_modify"]]
    assert "src/test/java/com/payshift/merchant/PaymentFlowIntegrationTest.java" not in modified_paths
    assert "src/main/java/com/payshift/merchant/service/PaymentService.java" in modified_paths


def test_blocked_documentation_produces_fully_unsupported_plan():
    state = _base_state()
    state["documentation_indexed"] = {"blocked": True, "blocker_reason": "No trusted documentation registered"}

    llm = FakeLLMClient(responses=[])  # must not even be called
    result = create_plan(state, llm)

    assert result["blocked"] is True
    assert llm.calls == []
    plan = result["integration_plan"]
    assert all(c["target_support"] == "UNSUPPORTED" for c in plan["capability_model"]["capabilities"])

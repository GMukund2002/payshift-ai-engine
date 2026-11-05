"""MIGRATE_PSP planning guarantees. A full generated-code demonstration for
MIGRATE_PSP would duplicate the ADD_PSP engineering effort in
test_graph_end_to_end.py (changing default routing for new payments while
leaving historical payments pointing at their original provider needs a
real modification to PaymentService, not just additive new files); this
test instead proves create_plan itself handles the mode correctly --
required_changes/cutover_checklist/preserved_historical_ownership_note are
populated distinctly from ADD_PSP, and existing provider ownership
language is never dropped.
"""
import json

from agent.planning import create_plan
from tests.fakes import FakeLLMClient


def _migrate_state():
    return {
        "operation_mode": "MIGRATE_PSP",
        "existing_providers": ["stripe"],
        "target_provider": "razorpay",
        "architecture_findings": {"summary": "stripe-coupled app, single provider"},
        "capability_model": {
            "operation_mode": "MIGRATE_PSP",
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
            "CREATE_PAYMENT": [{"text": "POST /v1/orders creates a new order", "source_url": "https://razorpay.com/docs/api/payments/",
                                 "title": "Orders API", "trust_level": "OFFICIAL_VERIFIED", "code_block": False, "distance": 0.1}],
            "CREATE_REFUND": [{"text": "POST /v1/payments/{id}/refund issues a refund", "source_url": "https://razorpay.com/docs/api/refunds/",
                                "title": "Refunds API", "trust_level": "OFFICIAL_VERIFIED", "code_block": False, "distance": 0.1}],
        },
    }


def test_migrate_psp_plan_preserves_historical_ownership_and_builds_cutover_checklist():
    fake_response = json.dumps({
        "capability_decisions": [
            {"operation": "CREATE_PAYMENT", "target_support": "SUPPORTED", "target_api": "POST /v1/orders", "notes": "documented"},
            {"operation": "CREATE_REFUND", "target_support": "SUPPORTED", "target_api": "POST /v1/payments/{id}/refund", "notes": "documented"},
        ],
        "reuse_existing_abstraction": False,
        "abstraction_interface": None,
        "required_changes": [
            "Change default payment routing for NEW payments to Razorpay",
            "Existing Stripe-owned payments keep using the Stripe gateway for status/refunds -- never re-routed",
        ],
        "files_to_create": [{"path": "RazorpayPaymentGateway.java", "reason": "new default provider", "change_type": "CREATE"}],
        "files_to_modify": [{"path": "PaymentService.java", "reason": "route new payments to Razorpay by default", "change_type": "MODIFY"}],
        "security_requirements": [],
        "unsupported_functionality": [],
        "testing_requirements": ["Regression: existing Stripe payment refund still works after cutover"],
        "manual_review_items": [{"description": "Confirm no stored payment methods need migrating", "reason": "out of scope for this MVP"}],
        "cutover_checklist": [
            "New payments created after cutover use Razorpay",
            "Existing stripe-owned payments retain provider='stripe' in the database",
            "Refunds for pre-cutover payments continue to route to Stripe",
        ],
        "preserved_historical_ownership_note": (
            "Payment.provider is set once at creation and never rewritten; migration only changes "
            "which provider NEW payments use, so historical Stripe payments and their refunds are unaffected."
        ),
    })
    llm = FakeLLMClient(responses=[fake_response])

    result = create_plan(_migrate_state(), llm)
    plan = result["integration_plan"]

    assert plan["operation_mode"] == "MIGRATE_PSP"
    assert plan["existing_providers"] == ["stripe"]
    assert plan["target_provider"] == "razorpay"
    assert len(plan["cutover_checklist"]) == 3
    assert "never rewritten" in plan["preserved_historical_ownership_note"]
    assert any("never re-routed" in c or "Razorpay" in c for c in plan["required_changes"])

    # The capability guardrail still applies identically in MIGRATE_PSP mode.
    cap_by_op = {c["operation"]: c for c in plan["capability_model"]["capabilities"]}
    assert cap_by_op["CREATE_PAYMENT"]["target_support"] == "SUPPORTED"
    assert cap_by_op["CREATE_REFUND"]["target_support"] == "SUPPORTED"


def test_migrate_psp_still_blocks_on_missing_documentation():
    state = _migrate_state()
    state["documentation_indexed"] = {"blocked": True, "blocker_reason": "No trusted documentation registered"}

    llm = FakeLLMClient(responses=[])
    result = create_plan(state, llm)

    assert result["blocked"] is True
    plan = result["integration_plan"]
    assert plan["operation_mode"] == "MIGRATE_PSP"
    assert all(c["target_support"] == "UNSUPPORTED" for c in plan["capability_model"]["capabilities"])

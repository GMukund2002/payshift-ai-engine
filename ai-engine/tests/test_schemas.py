import json
from pathlib import Path

from schemas.providers import RepositoryAnalysis
from schemas.capabilities import CapabilityEntry, PaymentCapabilityModel
from schemas.plans import IntegrationPlan, FileChange

FIXTURE = Path(__file__).parent / "fixtures" / "merchant-app-analysis.json"


def test_repository_analysis_parses_real_analyzer_output():
    raw = json.loads(FIXTURE.read_text())
    analysis = RepositoryAnalysis.model_validate(raw)

    assert analysis.architecture.provider_abstraction_exists is True
    assert "stripe" in analysis.confident_provider_ids()
    assert any(op.operation == "CREATE_PAYMENT" for op in analysis.payment_operations)
    assert any(pc.role == "PROVIDER_GATEWAY" for pc in analysis.payment_classes)


def test_capability_model_defaults_to_requires_research():
    model = PaymentCapabilityModel(
        operation_mode="ADD_PSP",
        existing_providers=["stripe"],
        target_provider="razorpay",
        capabilities=[
            CapabilityEntry(
                operation="CREATE_PAYMENT",
                business_intent="collect_customer_payment",
                source_api="stripe:PaymentIntent.create",
            )
        ],
    )
    assert model.capabilities[0].target_support == "REQUIRES_RESEARCH"
    assert model.requires_research() == model.capabilities
    assert model.has_blocking_gaps() is False


def test_integration_plan_round_trips_through_json():
    model = PaymentCapabilityModel(
        operation_mode="ADD_PSP",
        existing_providers=["stripe"],
        target_provider="razorpay",
    )
    plan = IntegrationPlan(
        operation_mode="ADD_PSP",
        existing_providers=["stripe"],
        target_provider="razorpay",
        capability_model=model,
        reuse_existing_abstraction=True,
        abstraction_interface="StripePaymentGateway",
        files_to_create=[FileChange(path="RazorpayPaymentGateway.java", reason="new adapter", change_type="CREATE")],
    )
    serialized = plan.model_dump_json()
    restored = IntegrationPlan.model_validate_json(serialized)
    assert restored.target_provider == "razorpay"
    assert restored.files_to_create[0].path == "RazorpayPaymentGateway.java"

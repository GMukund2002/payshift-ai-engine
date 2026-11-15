"""Fixes driven by the second live evaluation (8 runs, gpt-4o): 1 real
integration, 1 false VERIFIED, 6 UNRESOLVED_FAILURE. Each test reproduces
what a real run did.
"""
import json
import uuid
from pathlib import Path

from agent.apply_patch import apply_patch
from agent.generation import generate_code
from agent.planning import _normalize_file_changes
from agent.static_checks import static_checks
from tests.fakes import FakeLLMClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERCHANT_APP = REPO_ROOT / "sample-apps" / "merchant-app"
CHECKOUT_APP = REPO_ROOT / "sample-apps" / "stripe-direct-checkout"
ROUTER_APP = REPO_ROOT / "sample-apps" / "multi-psp-router"


def test_planned_files_outside_the_component_scan_are_moved_into_it():
    # eval-stripe-direct-checkout-2 put every class in com.acme.payment; the app scans com.acme.checkout,
    # so none of them were ever registered as beans -- yet the run was reported VERIFIED.
    creates, _ = _normalize_file_changes([
        {"path": "src/main/java/com/acme/payment/RazorpayPaymentAdapter.java", "reason": "r", "change_type": "CREATE"},
        {"path": "src/main/java/com/acme/payment/web/RazorpayController.java", "reason": "r", "change_type": "CREATE"},
        {"path": "src/main/java/com/acme/checkout/config/RazorpayConfig.java", "reason": "r", "change_type": "CREATE"},
        {"path": "src/test/java/com/acme/payment/RazorpayFlowTest.java", "reason": "r", "change_type": "CREATE"},
    ], [], str(CHECKOUT_APP))
    assert [c.path for c in creates] == [
        "src/main/java/com/acme/checkout/payment/RazorpayPaymentAdapter.java",
        "src/main/java/com/acme/checkout/payment/web/RazorpayController.java",
        "src/main/java/com/acme/checkout/config/RazorpayConfig.java",
        "src/test/java/com/acme/checkout/payment/RazorpayFlowTest.java",
    ]


def test_generation_is_shown_the_real_source_of_the_interface_it_implements():
    # eval-multi-psp-router-1/2: RazorpayProvider implemented only part of PaymentProvider (twice).
    target = "src/main/java/com/payments/router/provider/RazorpayProvider.java"
    llm = FakeLLMClient(responses=[json.dumps({"files": [{"path": target, "content": "class X {}"}]})])
    state = {
        "repository_path": str(ROUTER_APP), "target_provider": "razorpay",
        "integration_plan": {
            "capability_model": {"capabilities": [{"operation": "CREATE_PAYMENT", "target_support": "SUPPORTED"}]},
            "reuse_existing_abstraction": True, "abstraction_interface": "PaymentProvider",
            "files_to_create": [{"path": target, "reason": "Razorpay adapter", "change_type": "CREATE"}],
            "files_to_modify": [],
        },
        "retrieved_passages": {"CREATE_PAYMENT": [{"text": "POST /v1/orders", "source_url": "https://razorpay.com/docs"}]},
    }
    generate_code(state, llm)
    prompt = llm.calls[0][1]
    assert "APPLICATION BASE PACKAGE(S) (component-scanned): com.payments.router" in prompt
    assert "EXISTING SOURCE OF TYPES THIS CHANGE USES" in prompt
    assert "Set<String> supportedCurrencies();" in prompt          # the real interface, verbatim
    assert "com.payments.router.provider.PaymentProvider" in prompt   # and its real FQN


def test_wrong_import_is_corrected_deterministically_before_compile():
    # 3 of 8 runs imported RestTemplateBuilder from org.springframework.web.client, each costing
    # a full compile + LLM repair round.
    cfg = "src/main/java/com/payshift/merchant/config/RazorpayConfig.java"
    content = """package com.payshift.merchant.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.client.RestTemplateBuilder;

@Configuration
public class RazorpayConfig {
    @Bean
    public RestTemplate razorpayRestTemplate(RestTemplateBuilder builder) {
        return builder.build();
    }
}
"""
    state = {"repository_path": str(MERCHANT_APP), "run_id": "imp-" + uuid.uuid4().hex[:8],
             "pending_patch": [{"path": cfg, "content": content}]}
    state.update(apply_patch(state))

    result = static_checks(state)["static_check_result"]

    fixed = Path(state["workspace_path"], cfg).read_text()
    assert "import org.springframework.boot.web.client.RestTemplateBuilder;" in fixed
    assert "import org.springframework.web.client.RestTemplate;" in fixed   # correct imports untouched
    assert any(f["check"] == "auto_fixed_import" and f["severity"] == "INFO" for f in result["findings"])


def test_repair_can_delete_files_this_run_created_but_never_original_files():
    moved_from = "src/main/java/com/acme/payment/RazorpayAdapter.java"
    state = {"repository_path": str(CHECKOUT_APP), "run_id": "del-" + uuid.uuid4().hex[:8],
             "pending_patch": [{"path": moved_from, "content": "package com.acme.payment; class RazorpayAdapter {}"}]}
    state.update(apply_patch(state))
    assert state["applied_changes"]["created"] == [moved_from]

    original = "src/main/java/com/acme/checkout/service/CheckoutService.java"
    state["pending_patch"] = [{"path": moved_from, "delete": True}, {"path": original, "delete": True}]
    state.update(apply_patch(state))

    assert not Path(state["workspace_path"], moved_from).exists()
    assert Path(state["workspace_path"], original).exists()
    assert state["applied_changes"] == {"created": [], "modified": []}
    assert state["rejected_patch_files"] == [{"path": original, "reason": "only files created in this run can be deleted"}]

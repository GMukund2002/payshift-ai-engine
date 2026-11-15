"""The evaluation's hidden checks must tell a real integration from a hollow
one independently of the pipeline's own gates. Uses real Maven + Spring.

Hollow case = the three files live run f0d9df91493b generated: they compiled,
booted and passed every existing test, so the pipeline (before the
unused-credential / reachability static checks existed) reported VERIFIED.
"""
import uuid
from pathlib import Path

from agent.apply_patch import apply_patch
from evaluation.corpus import by_name
from evaluation.hidden_checks import run_hidden_checks
from tests.test_static_checks import GOOD_FILES
from tools.java_tools import compile_project

MERCHANT = by_name(["merchant-app"])[0]
PKG_DIR = "src/main/java/com/payshift/merchant"

HOLLOW_F0D9 = [
    {"path": f"{PKG_DIR}/config/RazorpayClientConfig.java", "content": """package com.payshift.merchant.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

@Configuration
public class RazorpayClientConfig {
    @Value("${payshift.razorpay.api-key:placeholder}")
    private String apiKey;

    @Bean
    public RestTemplate razorpayRestTemplate(RestTemplateBuilder builder) {
        return builder.build();
    }
}
"""},
    {"path": f"{PKG_DIR}/provider/RazorpayPaymentGateway.java", "content": """package com.payshift.merchant.provider;

public interface RazorpayPaymentGateway {
    void createRefund(String paymentId);
    String getPaymentStatus(String paymentId);
}
"""},
    {"path": f"{PKG_DIR}/provider/RazorpayApiPaymentGateway.java", "content": """package com.payshift.merchant.provider;

import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

@Component
public class RazorpayApiPaymentGateway implements RazorpayPaymentGateway {
    private final RestTemplate restTemplate;

    public RazorpayApiPaymentGateway(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @Override
    public void createRefund(String paymentId) {
        restTemplate.postForEntity("https://api.razorpay.com/v1/payments/" + paymentId + "/refund", null, Void.class);
    }

    @Override
    public String getPaymentStatus(String paymentId) {
        return restTemplate.getForObject("https://api.razorpay.com/v1/payments/" + paymentId, String.class);
    }
}
"""},
]


def _finished_state(files):
    state = {"repository_path": str(MERCHANT.path), "run_id": "hc-" + uuid.uuid4().hex[:8], "pending_patch": files}
    state.update(apply_patch(state))
    state["compilation_result"] = compile_project(state["workspace_path"]).model_dump()
    assert state["compilation_result"]["success"], state["compilation_result"]["raw_output_tail"]
    return state


def test_real_integration_passes_hidden_checks():
    result = run_hidden_checks(MERCHANT, _finished_state(GOOD_FILES))
    assert result.provider_evidence_in_code
    assert result.context_has_provider_bean is True, result.hidden_test_output_tail
    assert result.integration_is_real
    assert result.new_provider_test_files == ["src/test/java/com/payshift/merchant/RazorpayPaymentFlowIntegrationTest.java"]


def test_hollow_unreachable_integration_fails_hidden_checks():
    state = _finished_state(HOLLOW_F0D9)
    result = run_hidden_checks(MERCHANT, state)
    assert result.provider_evidence_in_code            # it does mention api.razorpay.com...
    assert result.context_has_provider_bean is False   # ...but nothing can ever call it
    assert not result.integration_is_real
    assert "nothing depends on them" in result.hidden_test_output_tail
    # The hidden test is removed again: the workspace is left as the run produced it.
    assert not list(Path(state["workspace_path"]).rglob("PayShiftHiddenWiringCheckTest.java"))

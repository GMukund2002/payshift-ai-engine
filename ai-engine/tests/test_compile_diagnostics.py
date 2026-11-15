"""Live run 5f1db5114a03: generated config imported RestTemplateBuilder from
org.springframework.web.client (it lives in org.springframework.boot.web.client).
The repair model read "cannot find symbol" as a missing dependency and spent
the whole build-repair budget trying to edit pom.xml. These tests prove the
compile step now hands repair the real location, looked up on the project's
actual classpath.
"""
import uuid
from pathlib import Path

from agent.apply_patch import apply_patch
from tools.compile_diagnostics import hints_for_compile_failure, strip_ansi
from tools.java_tools import compile_project

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERCHANT_APP = REPO_ROOT / "sample-apps" / "merchant-app"
CONFIG = "src/main/java/com/payshift/merchant/config/RazorpayConfig.java"

# Exactly what the model generated in that run.
LIVE_RUN_CONFIG = """package com.payshift.merchant.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.client.RestTemplateBuilder;

@Configuration
public class RazorpayConfig {

    @Value("${payshift.razorpay.api-key:rzp_test_placeholder}")
    private String apiKey;

    @Bean
    public RestTemplate razorpayRestTemplate(RestTemplateBuilder builder) {
        return builder.basicAuthentication(apiKey, "").build();
    }
}
"""

# The (ANSI-colored) javac output from that run, verbatim.
LIVE_RUN_OUTPUT = (
    "[\x1b[1;31mERROR\x1b[m] COMPILATION ERROR : \n"
    "[\x1b[1;31mERROR\x1b[m] /app/workspaces/5f1db5114a03/modified/src/main/java/com/payshift/merchant/config/"
    "RazorpayConfig.java:[7,38] cannot find symbol\n  symbol:   class RestTemplateBuilder\n"
    "  location: package org.springframework.web.client\n"
    "[\x1b[1;31mERROR\x1b[m] /app/workspaces/5f1db5114a03/modified/src/main/java/com/payshift/merchant/config/"
    "RazorpayConfig.java:[16,46] cannot find symbol\n  symbol:   class RestTemplateBuilder\n"
    "  location: class com.payshift.merchant.config.RazorpayConfig\n"
)


def test_hint_names_the_real_package_for_a_misimported_class():
    index = {"RestTemplateBuilder": ["org.springframework.boot.web.client.RestTemplateBuilder"]}
    hints = hints_for_compile_failure(LIVE_RUN_OUTPUT, index)
    assert hints == [
        "RestTemplateBuilder is not in package org.springframework.web.client. On this project's classpath it is: "
        "org.springframework.boot.web.client.RestTemplateBuilder. Fix the import; no dependency change is needed."
    ]


def test_hint_says_when_a_class_is_not_available_at_all():
    hints = hints_for_compile_failure(LIVE_RUN_OUTPUT.replace("RestTemplateBuilder", "RazorpayClient"), {})
    assert len(hints) == 1 and "No class named RazorpayClient" in hints[0] and "pom.xml is not editable" in hints[0]


def test_strip_ansi():
    assert strip_ansi("[\x1b[1;31mERROR\x1b[m] x") == "[ERROR] x"


def test_real_compile_of_the_live_run_config_produces_the_classpath_hint():
    state = {"repository_path": str(MERCHANT_APP), "run_id": "cd-" + uuid.uuid4().hex[:8],
             "pending_patch": [{"path": CONFIG, "content": LIVE_RUN_CONFIG}]}
    state.update(apply_patch(state))

    result = compile_project(state["workspace_path"], with_hints=True)

    assert result.success is False
    assert "\x1b[" not in result.raw_output_tail          # batch mode / stripped: no color codes
    assert any("org.springframework.boot.web.client.RestTemplateBuilder" in h for h in result.hints), result.hints


def test_hint_points_at_the_projects_own_type_not_a_new_one(tmp_path):
    # Live eval run eval-multi-psp-router-1: the app's own PaymentProvider was imported from
    # an invented package; the repair then created a parallel interface instead of fixing it.
    src = tmp_path / "src/main/java/com/payments/router/provider"
    src.mkdir(parents=True)
    (src / "PaymentProvider.java").write_text("package com.payments.router.provider;\npublic interface PaymentProvider {}\n")
    output = ("[ERROR] /w/src/main/java/com/payments/router/provider/RazorpayProvider.java:[7,35] "
              "package com.payments.router.spi does not exist\n")
    (src / "RazorpayProvider.java").write_text(
        "package com.payments.router.provider;\nimport com.payments.router.spi.PaymentProvider;\nclass RazorpayProvider {}\n")
    hints = hints_for_compile_failure(output, {}, workspace=tmp_path)
    assert hints == ["PaymentProvider already exists in this project as com.payments.router.provider.PaymentProvider "
                     "(not in package com.payments.router.spi). Import and use that existing type; do NOT create a new "
                     "class or interface named PaymentProvider."]


def _project(tmp_path, files: dict[str, str]):
    for rel, content in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    return tmp_path


def test_hint_lists_real_members_when_generated_code_calls_a_nonexistent_method(tmp_path):
    # Live eval run eval-merchant-app-1: refundRequest.getPaymentId() on a record with only amount().
    ws = _project(tmp_path, {"src/main/java/com/payshift/merchant/dto/RefundRequest.java":
                             "package com.payshift.merchant.dto;\nimport java.math.BigDecimal;\n"
                             "public record RefundRequest(BigDecimal amount) {\n}\n"})
    output = ("[ERROR] /w/RazorpayApiPaymentGateway.java:[33,50] cannot find symbol\n"
              "  symbol:   method getPaymentId()\n"
              "  location: variable refundRequest of type com.payshift.merchant.dto.RefundRequest\n")
    [hint] = hints_for_compile_failure(output, {}, workspace=ws)
    assert "RefundRequest has no method getPaymentId()" in hint
    assert "amount()  [record component: BigDecimal amount]" in hint


def test_hint_lists_every_interface_method_when_an_implementation_is_incomplete(tmp_path):
    # Live eval runs eval-multi-psp-router-1/2: RazorpayProvider implemented only part of PaymentProvider.
    ws = _project(tmp_path, {"src/main/java/com/payments/router/provider/PaymentProvider.java": """package com.payments.router.provider;
import java.util.Set;
public interface PaymentProvider {
    record ProviderPayment(String providerPaymentId, String status) {}
    String id();
    Set<String> supportedCurrencies();
    ProviderPayment createPayment(String reference, long amountMinor, String currency);
}
"""})
    output = ("[ERROR] /w/RazorpayProvider.java:[13,8] com.payments.router.provider.RazorpayProvider is not abstract "
              "and does not override abstract method supportedCurrencies() in com.payments.router.provider.PaymentProvider\n")
    [hint] = hints_for_compile_failure(output, {}, workspace=ws)
    assert "RazorpayProvider implements PaymentProvider but not all of its methods" in hint
    for sig in ("String id()", "Set<String> supportedCurrencies()",
                "ProviderPayment createPayment(String reference, long amountMinor, String currency)"):
        assert sig in hint, hint

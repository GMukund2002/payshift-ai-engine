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

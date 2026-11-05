"""Guardrail found by running the real pipeline against a real LLM: the model
generated a file under a hallucinated package path (com.example.payment
instead of the repo's real com.payshift.merchant.provider). The existing
path-matching filter correctly rejected it, but the node then silently
returned an empty generated_files list and let the graph proceed to
apply_patch -> compile -> test -> "VERIFIED" against an unchanged repo --
true that nothing broke, false that anything was accomplished. This test
locks in the fix: when every returned file is rejected, generate_code must
block instead of silently reporting success.
"""
import json

from agent.generation import generate_code
from tests.fakes import FakeLLMClient


def _state_with_one_actionable_capability():
    return {
        "repository_path": "/nonexistent",
        "target_provider": "razorpay",
        "integration_plan": {
            "capability_model": {
                "capabilities": [
                    {"operation": "CREATE_REFUND", "target_support": "SUPPORTED"},
                    {"operation": "CREATE_PAYMENT", "target_support": "REQUIRES_RESEARCH"},
                ],
            },
            "files_to_create": [
                {"path": "src/main/java/com/payshift/merchant/provider/RazorpayPaymentGateway.java",
                 "reason": "adapter", "change_type": "CREATE"},
            ],
            "files_to_modify": [],
        },
        "retrieved_passages": {"CREATE_REFUND": [{"text": "refund docs", "source_url": "https://x"}]},
    }


def test_blocks_when_every_generated_file_is_rejected():
    llm = FakeLLMClient(responses=[json.dumps({
        "files": [{"path": "src/main/java/com/example/payment/RazorpayPaymentGateway.java", "content": "// wrong package"}],
    })])

    result = generate_code(_state_with_one_actionable_capability(), llm)

    assert result["blocked"] is True
    assert "com/example/payment" in result["blocker_reason"]
    assert result["generated_files"] == []


def test_blocks_when_plan_is_internally_inconsistent_no_files_for_a_supported_capability():
    """Found running against a real LLM: the planner marked CREATE_REFUND SUPPORTED
    but left files_to_create/files_to_modify both empty."""
    state = _state_with_one_actionable_capability()
    state["integration_plan"]["files_to_create"] = []

    llm = FakeLLMClient(responses=[])  # must not even be called
    result = generate_code(state, llm)

    assert result["blocked"] is True
    assert "CREATE_REFUND" in result["blocker_reason"]
    assert llm.calls == []


def test_accepts_files_matching_the_planned_path_exactly():
    llm = FakeLLMClient(responses=[json.dumps({
        "files": [{"path": "src/main/java/com/payshift/merchant/provider/RazorpayPaymentGateway.java",
                   "content": "package com.payshift.merchant.provider;"}],
    })])

    result = generate_code(_state_with_one_actionable_capability(), llm)

    assert result.get("blocked") is not True
    assert len(result["generated_files"]) == 1

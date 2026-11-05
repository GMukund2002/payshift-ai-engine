"""Proves the bounded self-repair loop (Agent 5) actually works: a deliberately
broken file fails a real `mvn compile`, diagnose_failures and repair_code run
against that real failure output, and the repaired file recompiles for real.
No network dependency -- this test is self-contained.
"""
import json
import uuid
from pathlib import Path

from agent.apply_patch import apply_patch
from agent.repair import diagnose_failures, repair_code
from tools.java_tools import compile_project
from tests.fakes import FakeLLMClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERCHANT_APP = REPO_ROOT / "sample-apps" / "merchant-app"
GOOD_FILE = json.loads((Path(__file__).parent / "fixtures" / "razorpay_add_psp_files.json").read_text())
GATEWAY_PATH = "src/main/java/com/payshift/merchant/provider/RazorpayPaymentGateway.java"
GOOD_CONTENT = next(f["content"] for f in GOOD_FILE if f["path"] == GATEWAY_PATH)

# Deliberately broken: drop the closing brace of the interface body.
BROKEN_CONTENT = GOOD_CONTENT.rsplit("}", 1)[0]

DIAGNOSIS_RESPONSE = json.dumps({
    "diagnosis_summary": "RazorpayPaymentGateway.java is missing its closing brace, causing a syntax error.",
    "likely_cause": "Unbalanced braces in the interface declaration.",
    "confidence": "HIGH",
    "files_to_inspect": [GATEWAY_PATH],
    "doc_query": None,
})

REPAIR_RESPONSE = json.dumps({
    "patch_description": "Restore the missing closing brace.",
    "files": [{"path": GATEWAY_PATH, "content": GOOD_CONTENT}],
})


def test_repair_loop_fixes_a_real_compile_failure():
    run_id = "repair-test-" + uuid.uuid4().hex[:8]
    state = {
        "repository_path": str(MERCHANT_APP),
        "run_id": run_id,
        "target_provider": "razorpay",
        "integration_plan": {"files_to_create": [{"path": GATEWAY_PATH}], "files_to_modify": []},
        "generated_files": [{"path": GATEWAY_PATH, "content": BROKEN_CONTENT}],
    }

    patch_result = apply_patch(state)
    state.update(patch_result)

    compilation = compile_project(state["workspace_path"])
    assert compilation.success is False, "expected the deliberately broken file to fail compilation"
    state["compilation_result"] = compilation.model_dump()

    diagnosis_llm = FakeLLMClient(responses=[DIAGNOSIS_RESPONSE])
    diag_result = diagnose_failures(state, diagnosis_llm)
    assert diag_result.get("blocked") is not True
    state.update(diag_result)
    assert state["diagnosis"]["likely_cause"]

    repair_llm = FakeLLMClient(responses=[REPAIR_RESPONSE])
    repair_result = repair_code(state, repair_llm)
    assert repair_result.get("blocked") is not True
    state.update(repair_result)

    assert state["repair_count"] == 1
    assert len(state["repair_attempts"]) == 1
    assert state["repair_attempts"][0]["files_touched"] == [GATEWAY_PATH]

    reapplied = apply_patch(state)
    state.update(reapplied)

    recompiled = compile_project(state["workspace_path"])
    assert recompiled.success is True, recompiled.raw_output_tail

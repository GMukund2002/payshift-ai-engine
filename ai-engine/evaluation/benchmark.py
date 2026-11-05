"""Phase 14 benchmark: PayShift's real, measured numbers against three sample
variants. The spec also asks for a baseline ("direct LLM code generation")
comparison -- this environment has no configured LLM provider, so baseline
rows are reported as unmeasured (None) with an explicit note, never a
fabricated or estimated number. Re-run this script with OPENAI_API_KEY or
ANTHROPIC_API_KEY set to get a real baseline comparison.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from agent.apply_patch import apply_patch
from evaluation.metrics import DetectionAccuracy, EvaluationRun, OperationDiscoveryRecall
from tools.documentation_tools import ensure_docs_indexed, search_provider_docs
from tools.java_tools import compile_project, run_tests
from tools.repository_tools import analyze_repository

AI_ENGINE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = AI_ENGINE_ROOT.parent
MERCHANT_APP = REPO_ROOT / "sample-apps" / "merchant-app"
TIGHTLY_COUPLED_FIXTURE = REPO_ROOT / "java-analyzer" / "src" / "test" / "resources" / "fixtures" / "tightly-coupled"
ABSTRACTED_FIXTURE = REPO_ROOT / "java-analyzer" / "src" / "test" / "resources" / "fixtures" / "abstracted"
RAZORPAY_FILES_FIXTURE = AI_ENGINE_ROOT / "tests" / "fixtures" / "razorpay_add_psp_files.json"

GROUND_TRUTH = {
    "merchant-app": {
        "path": MERCHANT_APP,
        "expected_providers": {"stripe"},
        "expected_operations": {
            "CREATE_PAYMENT", "GET_PAYMENT_STATUS", "CREATE_REFUND",
            "HANDLE_WEBHOOK", "VERIFY_WEBHOOK_SIGNATURE", "FULFILL_ORDER",
        },
    },
    "tightly-coupled-fixture": {
        "path": TIGHTLY_COUPLED_FIXTURE,
        "expected_providers": {"razorpay"},
        "expected_operations": {"CREATE_PAYMENT", "GET_PAYMENT_STATUS", "CREATE_REFUND"},
    },
    "abstracted-fixture": {
        "path": ABSTRACTED_FIXTURE,
        "expected_providers": {"stripe", "razorpay"},
        "expected_operations": {"CREATE_PAYMENT", "GET_PAYMENT_STATUS", "CREATE_REFUND"},
    },
}


def _measure_detection_and_recall(variant: str, meta: dict) -> tuple[DetectionAccuracy, OperationDiscoveryRecall, dict]:
    analysis = analyze_repository(meta["path"])
    detection = DetectionAccuracy(
        expected_providers=meta["expected_providers"],
        detected_providers=set(analysis.confident_provider_ids()),
    )
    discovered_ops = {op.operation for op in analysis.payment_operations}
    recall = OperationDiscoveryRecall(expected_operations=meta["expected_operations"], discovered_operations=discovered_ops)
    return detection, recall, analysis.architecture.model_dump()


def _measure_doc_retrieval_relevance(provider_id: str) -> bool | None:
    try:
        ensure_docs_indexed(provider_id)
        results = search_provider_docs("how to issue a refund", provider_id=provider_id, operation="CREATE_REFUND", top_k=3)
    except Exception:
        return None
    if not results:
        return False
    return any("refund" in r.text.lower() for r in results)


def _measure_payshift_add_psp_verification() -> dict:
    """The only variant where we can measure real compilation/test outcomes:
    the hand-validated Razorpay ADD_PSP files from the E2E test, applied fresh."""
    generated_files = json.loads(RAZORPAY_FILES_FIXTURE.read_text())
    run_id = "bench-" + uuid.uuid4().hex[:8]
    patch_result = apply_patch({
        "repository_path": str(MERCHANT_APP), "run_id": run_id, "generated_files": generated_files,
    })
    compilation = compile_project(patch_result["workspace_path"])
    if not compilation.success:
        return {"compilation_success": False, "test_pass_rate": None}
    tests = run_tests(patch_result["workspace_path"])
    pass_rate = (tests.tests_run - tests.failures - tests.errors) / tests.tests_run if tests.tests_run else None
    return {"compilation_success": compilation.success, "test_pass_rate": pass_rate, "tests_run": tests.tests_run}


def run_benchmark() -> list[EvaluationRun]:
    runs: list[EvaluationRun] = []

    for variant, meta in GROUND_TRUTH.items():
        detection, recall, _arch = _measure_detection_and_recall(variant, meta)
        doc_relevant = _measure_doc_retrieval_relevance(next(iter(meta["expected_providers"])))

        run = EvaluationRun(
            condition="payshift", sample_variant=variant,
            detection=detection, operation_recall=recall,
            documentation_retrieval_relevant=doc_relevant,
        )
        if variant == "merchant-app":
            add_psp_metrics = _measure_payshift_add_psp_verification()
            run.compilation_success = add_psp_metrics["compilation_success"]
            run.test_pass_rate = add_psp_metrics.get("test_pass_rate")
            run.repair_attempts_used = 0
            run.notes.append(f"ADD_PSP(razorpay) verification using hand-validated generated files "
                              f"({add_psp_metrics.get('tests_run', '?')} tests)")
        else:
            run.notes.append("Detection-only fixture (not a full compilable Maven project)")
        runs.append(run)

        baseline = EvaluationRun(
            condition="baseline", sample_variant=variant,
            notes=["Not measured: no LLM provider is configured in this environment. "
                   "Baseline = a direct LLM code-generation prompt with no repository analysis, "
                   "RAG, or verification loop. Re-run with OPENAI_API_KEY/ANTHROPIC_API_KEY set "
                   "for a real comparison; this row is intentionally left unmeasured rather than estimated."],
        )
        runs.append(baseline)

    return runs


def main():
    start = time.monotonic()
    runs = run_benchmark()
    duration = time.monotonic() - start

    rows = [r.to_row() for r in runs]
    output = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "duration_seconds": round(duration, 2), "rows": rows}

    out_path = AI_ENGINE_ROOT / "evaluation" / "results.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"Benchmark completed in {duration:.1f}s. Results written to {out_path}\n")
    columns = ["condition", "sample_variant", "detection_precision", "detection_recall",
               "operation_recall", "documentation_retrieval_relevant", "compilation_success", "test_pass_rate"]
    print(" | ".join(columns))
    for r in rows:
        print(" | ".join(str(r.get(col)) for col in columns))


if __name__ == "__main__":
    main()

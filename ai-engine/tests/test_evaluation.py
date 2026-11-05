"""Confirms the evaluation benchmark produces honest results: perfect
detection/recall on our own fixtures (deterministic analyzer, known ground
truth), real compile/test verification for the one variant that supports
it, and -- critically -- never a fabricated number for the baseline
condition when no LLM is configured.
"""
from evaluation.benchmark import run_benchmark


def test_benchmark_produces_real_measurements_not_fabricated_baseline():
    runs = run_benchmark()
    by_key = {(r.condition, r.sample_variant): r for r in runs}

    payshift_merchant = by_key[("payshift", "merchant-app")]
    assert payshift_merchant.detection.precision == 1.0
    assert payshift_merchant.detection.recall == 1.0
    assert payshift_merchant.operation_recall.recall == 1.0
    assert payshift_merchant.compilation_success is True
    assert payshift_merchant.test_pass_rate == 1.0

    for variant in ("merchant-app", "tightly-coupled-fixture", "abstracted-fixture"):
        baseline = by_key[("baseline", variant)]
        assert baseline.detection is None
        assert baseline.compilation_success is None
        assert baseline.test_pass_rate is None
        assert any("not measured" in n.lower() for n in baseline.notes)

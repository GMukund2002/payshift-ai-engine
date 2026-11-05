# Evaluation

Run with `make benchmark` (or `python -m evaluation.benchmark` from
`ai-engine/`). Writes `ai-engine/evaluation/results.json`.

## Real measured results

These numbers are from the benchmark script run before a real LLM key
existed, so the "payshift" rows reflect the deterministic parts of the
pipeline (detection, operation recall, RAG retrieval) plus the one
hand-validated compile/test result, not a live agent run. A key was
supplied partway through the build and used to run the full live pipeline
6 times instead (see `README.md` §4) — that's the more informative
baseline-vs-PayShift signal right now, not this table's "baseline" column,
which the benchmark script still doesn't execute automatically.

| condition | variant                  | detect P | detect R | op recall | docs relevant | compile | tests  |
|-----------|---------------------------|----------|----------|-----------|----------------|---------|--------|
| payshift  | merchant-app              | 1.0      | 1.0      | 1.0       | true           | true    | 1.0    |
| baseline  | merchant-app              | —        | —        | —         | —              | —       | —      |
| payshift  | tightly-coupled-fixture   | 1.0      | 1.0      | 1.0       | true           | n/a¹    | n/a¹   |
| baseline  | tightly-coupled-fixture   | —        | —        | —         | —              | —       | —      |
| payshift  | abstracted-fixture        | 1.0      | 1.0      | 1.0       | true           | n/a¹    | n/a¹   |
| baseline  | abstracted-fixture        | —        | —        | —         | —              | —       | —      |

¹ These two are minimal JavaParser fixtures (detection-only), not full
Maven projects — compile/test metrics don't apply to them.

**`—` means genuinely not measured, not zero and not estimated.** The
baseline condition ("direct LLM code generation with no repository
analysis, RAG, or verification") has never actually been run — the
benchmark script doesn't implement it yet, it just leaves the row blank
with an explanatory note. A key now exists (see README §4), so this is a
real gap to close, not a credentials gap: implement an actual baseline
call in `evaluation/benchmark.py` and re-run, rather than filling these
cells in by hand.

## What `payshift/merchant-app`'s numbers actually mean

- **Detection precision/recall = 1.0**: the analyzer found exactly
  `{stripe}` with no false positives and no misses, against the known
  ground truth for that repo.
- **Operation recall = 1.0**: all 6 expected operation types
  (`CREATE_PAYMENT`, `GET_PAYMENT_STATUS`, `CREATE_REFUND`,
  `HANDLE_WEBHOOK`, `VERIFY_WEBHOOK_SIGNATURE`, `FULFILL_ORDER`) were found.
- **Documentation retrieval relevant = true**: a live query against
  Stripe's real indexed docs for "how to issue a refund" returned a top
  passage that actually mentions "refund."
- **Compilation success / test pass rate = 1.0**: this is the *real*
  ADD_PSP(razorpay) result from `tests/test_graph_end_to_end.py`'s
  generated files, re-applied and re-verified fresh — 11/11 tests pass
  (9 pre-existing Stripe tests + 2 new Razorpay tests), 0 files modified.

## Self-repair

Not exercised by the benchmark script itself, but exercised for real 5 out
of 6 times in the live pipeline runs (README §4) — every one of those hit
the 2-attempt bound and correctly reported `UNRESOLVED_FAILURE` rather
than a false success. The mechanism in isolation is also verified in
`tests/test_repair.py`: a deliberately broken file fails a real `mvn
compile`, `diagnose_failures` and `repair_code` run against that real
failure output, and the repaired file recompiles for real.

## Honest limitations of this evaluation

- Only one repository (the sample app) has a real, compilable ADD_PSP
  demonstration; the other two "variants" are detection-only fixtures. A
  fuller evaluation would need more real sample repositories.
- No token-usage or dollar-cost numbers are reported even though real LLM
  calls were made (README §4): `LLMUsage` (see `llm/client.py`) is
  returned per call but never aggregated into `AgentState` or the report
  — a real gap to close, not a measurement that was skipped for lack of
  a key.
- MIGRATE_PSP has no generated-code verification, only planning-level
  guarantees (see `docs/architecture.md` / `README.md` limitations).

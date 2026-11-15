# Evaluation

Two layers: a **live evaluation** that runs the whole pipeline with a real LLM
against a corpus of apps and judges the result with hidden checks, and a
deterministic **benchmark** of the non-LLM parts.

## Live evaluation (`make docker-eval`, `ai-engine/evaluation/live_eval.py`)

### Corpus (`ai-engine/evaluation/corpus.py`, apps under `sample-apps/`)

| Case | Existing integration | Target |
|---|---|---|
| `merchant-app` | Stripe SDK behind a provider-named port, webhooks, idempotency | razorpay |
| `stripe-direct-checkout` | `StripeClient` called directly in the service; no abstraction | razorpay |
| `razorpay-rest-orders` | Razorpay over raw REST (`RestClient`, endpoint only in `application.yml`), HMAC webhooks; no SDK | stripe |
| `multi-psp-router` | `PaymentProvider` port, Stripe (SDK) + PayPal (REST) adapters, router over `List<PaymentProvider>` | razorpay |

Each app builds and passes its own tests unmodified, and the wiring checker
reports nothing on its untouched sources.

### Hidden checks (`ai-engine/evaluation/hidden_checks.py`)

Applied to each finished workspace; the pipeline never sees them:
1. A JUnit test is injected and run: it boots the real `ApplicationContext` and
   requires a bean whose class names the target provider **and** that some other
   bean depends on (or is itself a controller).
2. Changed production code must reference the provider (API host or SDK package).
3. Every original test must still run and pass.

`false_verified` = the pipeline said VERIFIED but check 1 or 2 failed. That is
the number a buyer cares about most; the target is 0.

### Results (gpt-4o)

| Round | Runs | VERIFIED | Real integration | False VERIFIED | What the round exposed (each fixed + regression-tested before the next) |
|---|---|---|---|---|---|
| 1 | 4 | 2 | 1 | 1 | Types matched by simple name: a repair invented a second `PaymentProvider` in a made-up package, and the router's real one never saw the adapter. Plans with no caller for the adapter. |
| 2 | 8 | 2 | 1 | 1 | New classes outside the component-scanned package (never registered as beans). Generated code calling methods that don't exist on existing types (never shown their source). Repeated mis-import of `RestTemplateBuilder`. |
| 3 | 8 | 4 | 3 | 1 | A repair removed `@Component`, leaving an implementation nothing created. Plans without an entry point. Repair budgets exhausted while still converging. |
| 4 | 5\* | 5 | 5 | 0 | LLM quota exhaustion crashed the graph instead of blocking (fixed); scripted tests were silently spending real embedding quota (fixed). |

\* 3 runs of round 4 never executed (OpenAI credits ran out); they are excluded.

Never observed in any run: an existing test broken by a VERIFIED change, a
provider mis-detected, or a run exceeding its repair budget.

Caveats: 25 runs, 4 apps, one model. `multi-psp-router` has not been measured
since the last two rounds of fixes. Rates are directional until more runs and
more apps exist. Raw per-run JSON: `ai-engine/evaluation/live_results/`.

## Deterministic benchmark (`make benchmark`, `ai-engine/evaluation/benchmark.py`)

Detection precision/recall and operation recall against known ground truth,
plus a doc-retrieval relevance probe and a compile/test check of the
hand-validated ADD_PSP(razorpay) files. No LLM involved; the "baseline"
condition (direct LLM generation without analysis/RAG/verification) is still
not implemented and is reported as unmeasured, not estimated.

| variant | detect P | detect R | op recall | docs relevant | compile | tests |
|---|---|---|---|---|---|---|
| merchant-app | 1.0 | 1.0 | 1.0 | true | true | 1.0 |
| tightly-coupled-fixture | 1.0 | 1.0 | 1.0 | true | n/a | n/a |
| abstracted-fixture | 1.0 | 1.0 | 1.0 | true | n/a | n/a |

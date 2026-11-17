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
| 5 | 8 | 6 | 6 | 0 | First full round after all fixes, all 4 apps (both `multi-psp-router` runs real). 2 runs exhausted their repair budgets (`merchant-app`: 3 static repairs; `razorpay-rest-orders`: 3 static + 3 build); not yet root-caused. |
| 6 | 8 | 8 | 8 | 0 | Both round-5 failures root-caused and fixed first: static and build repairers undoing each other (repair history + recurrence warning), and a `*Service` file wrongly counted as an entry point. One run still needed all 6 repairs to converge. |

\* 3 runs of round 4 never executed (OpenAI credits ran out); they are excluded.

Never observed in any run: an existing test broken by a VERIFIED change, a
provider mis-detected, or a run exceeding its repair budget.

Caveats: 41 runs, 4 apps, one model. Rounds 4-6 combined: 19 of 21 real
integrations, no false VERIFIED. The corpus doubled as the development set --
every fix came from failures on these apps -- so held-out apps are needed before
any rate is quoted for unseen codebases. Raw per-run JSON: `ai-engine/evaluation/live_results/`.

### Held-out results (`--split held-out`, gpt-4o, pipeline unchanged)

Three apps committed before the pipeline was ever run on them
(`ai-engine/evaluation/corpus.py`, `HELD_OUT`), 2 runs each:

| App | Runs | Real integration | False VERIFIED |
|---|---|---|---|
| `heldout-subscriptions-lombok` (Lombok, feature packages) | 2 | 2 | 0 |
| `heldout-invoices-jdbc` (JdbcTemplate, `.properties`, static Stripe API) | 2 | 2 | 0 |
| `heldout-storefront-paypal` (REST-only app, unqualified `RestTemplate`) | 2 | 0 | 0 |
| **Total** | **6** | **4 (67%)** | **0** |

No existing test broken; provider detection correct in all 6. Both failures
were reported as `UNRESOLVED_FAILURE`, never as success, and expose real
product gaps rather than tuning issues:
1. **No way to add a dependency.** One run wrote the Stripe integration against
   the Stripe Java SDK, which this REST-only app does not depend on; `pom.xml`
   is not editable, so it could not compile and the repairs never settled on
   plain REST.
2. **A fix that requires touching existing code.** The other run added a second
   `RestTemplate` bean; the existing `PaypalClient` injects `RestTemplate` by
   type, so the checker correctly flagged the ambiguity -- but every repair
   tried to edit `PaypalClient` (not editable) instead of not defining a
   competing bean.

These are deliberately left unfixed here: once a failure on a held-out app
drives a change, that app belongs to the development corpus.

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

# PayShift AI

An AI engineer for payment-provider integrations in Java/Spring Boot codebases.
Point it at a repository and a target PSP; it analyzes the existing payment
integration, researches the provider's official documentation, plans and
writes the change in an isolated workspace, and verifies it with deterministic
checks, a real Maven build and the application's own test suite -- repairing
within a fixed budget, and never reporting success it can't back with evidence.

- Modes: `ADD_PSP` (add a provider alongside existing ones) and `MIGRATE_PSP`
  (route new payments to a new provider; historical payments keep theirs --
  planning-level only today, see Limitations).
- Providers with registered documentation: Stripe, Razorpay, Adyen, PayPal,
  Cashfree; any other provider works with a user-supplied official docs URL.

See [`docs/architecture.md`](docs/architecture.md),
[`docs/provider-model.md`](docs/provider-model.md) and
[`docs/evaluation.md`](docs/evaluation.md).

## Status, measured

Measured with the live evaluation (`make docker-eval`): the real pipeline,
gpt-4o, real Maven, against 4 corpus apps with different integration styles
(SDK behind a port, SDK called directly, raw REST with no SDK, multi-provider
router). Every finished workspace is then judged by hidden checks the pipeline
never sees: a JUnit test injected afterwards boots the real Spring context and
requires a target-provider bean that something actually depends on.

| Round | Runs | VERIFIED | Real integration (hidden checks) | False VERIFIED | Existing tests broken |
|---|---|---|---|---|---|
| 1 | 4 | 2 | 1 (25%) | 1 of 2 | 0 |
| 2 | 8 | 2 | 1 (12.5%) | 1 of 2 | 0 |
| 3 | 8 | 4 | 3 (37.5%) | 1 of 4 | 0 |
| 4 | 5 completed\* | 5 | **5 (100%)** | **0 of 5** | 0 |

\* Round 4 stopped when the OpenAI account ran out of credits; 3 runs never
executed (`multi-psp-router` x2, one `razorpay-rest-orders`) and are not counted.
Every round's false VERIFIED was caught by the hidden checks, root-caused, and
turned into a deterministic static check plus a regression test before the
next round (see `docs/evaluation.md`). **Read these as directional**: 25 runs
in total, 4 apps, one model. Raw results: `ai-engine/evaluation/live_results/`.

What has held in every run so far: no existing test was ever broken, provider
detection was correct in every run, and every run stayed within its repair budget.

## How it works

```
repository ─► java-analyzer (JavaParser: providers, payment classes/operations, abstractions)
          ─► LLM architecture understanding ─► provider-neutral capability model
          ─► official-docs discovery + RAG (ChromaDB) ─► LLM plan (doc-backed capabilities only)
          ─► LLM code generation, one file per call ─► isolated workspace (original/modified)
          ─► deterministic static checks ─► mvn compile ─► mvn test (the app's own suite)
          ─► scoped diagnosis + repair (3 static + 3 build attempts) ─► report
```

A real LangGraph `StateGraph` (`ai-engine/agent/graph.py`, 15 nodes). What is
enforced in code rather than requested in a prompt:

| Guarantee | Where |
|---|---|
| A capability with zero retrieved documentation can never be marked supported | `agent/planning.py` |
| The original repository is never written; paths are checked for traversal | `agent/apply_patch.py` |
| Existing tests can never be modified or overwritten, by generation or repair | `agent/planning.py`, `agent/apply_patch.py`, `agent/repair.py` |
| Repairs may only touch planned/generated files, new files under `src/main`, or `application.*`; never build files | `agent/repair.py` |
| Spring wiring, component-scan placement, `@Value` placeholders, stubs, unused credentials, unreachable or duplicate types are checked before compiling; wrong imports are corrected deterministically | `java-analyzer --check-wiring`, `agent/static_checks.py` |
| Compile errors get classpath-backed fix hints (the real package of a mis-imported class) | `tools/compile_diagnostics.py` |
| `VERIFIED` requires static checks + compile + ≥1 test run with zero failures, against the final code | `agent/reporting.py` |
| Report lists files actually changed on disk, token usage per step, and every repair attempt | `schemas/reports.py` |

## Repository layout

```
ai-engine/              Python: LangGraph agent, RAG, LLM client, tools, evaluation, tests
  agent/                pipeline nodes (discovery, understanding, research, planning, generation,
                        apply_patch, static_checks, verification, repair, reporting) + graph
  evaluation/           corpus, live evaluation runner, hidden checks, results
java-analyzer/          JavaParser analyzer + wiring checker (dist/ holds the deployable jar)
sample-apps/            evaluation corpus: 4 Spring Boot apps with different integration styles
backend/main.py         FastAPI API (what's deployed): analyze, run (async + polling), history
webapp/                 dashboard (plain HTML/JS, served by the backend)
frontend/app.py         legacy Streamlit UI (local reference only)
docs/                   architecture, provider model, evaluation
```

## Running it

Everything runs in Docker -- no local JDK, Maven or Python needed.

```bash
cp .env.example .env        # add OPENAI_API_KEY (or ANTHROPIC_API_KEY)
make docker-build           # image with JDK 21, Maven, Python 3.12
make docker-run             # dashboard + API at http://localhost:8000
make docker-test            # Python test suite (real Maven, real analyzer)
make docker-test-java       # java-analyzer + sample-app JUnit suites
make docker-eval            # live evaluation over the corpus (real, paid LLM calls)
make docker-build-analyzer  # rebuild java-analyzer and refresh dist/java-analyzer.jar
```

Without an LLM key the pipeline still runs repository analysis and
documentation retrieval for real, then reports `BLOCKED` at the first
reasoning step rather than fabricating a plan.

Configuration (all optional except one LLM key; see `.env.example`):
`PAYSHIFT_LLM_PROVIDER`, `PAYSHIFT_LLM_MODEL`, `DATABASE_URL` (Postgres for
run history; SQLite otherwise), `DEMO_ACCESS_KEY` (gates upload/analyze/run),
`PAYSHIFT_MAX_CONCURRENT_RUNS` (default 1), `MAVEN_OPTS` (default `-Xmx256m`),
`PAYSHIFT_EMBEDDINGS` (`local` | `openai` for documentation retrieval).

Deployment: `render.yaml` + `Dockerfile` deploy the backend and dashboard as one
service. Maven and the JDK are runtime dependencies: verification really
compiles and tests the customer's code inside the container.

## Tests

| Suite | Tests |
|---|---|
| `ai-engine` (pytest; real Maven, real analyzer, live docs where marked; no paid API calls) | 88 |
| `java-analyzer` (JUnit) | 25 |
| sample apps (JUnit): merchant-app 9, stripe-direct-checkout 5, razorpay-rest-orders 5, multi-psp-router 4 | 23 |

## Known limitations

- **The sample is small.** 25 live runs over 4 apps with one model; the round-4
  numbers come from 5 runs and `multi-psp-router` was not re-measured after the
  last fixes. More rounds (and more apps) are needed before quoting a rate.
- **Hidden checks prove wiring, not correctness against the provider.** A
  change that boots, is reachable and calls the provider's API host can still
  send a wrong request body. Provider contract tests (recorded sandbox
  traffic) are the next step.
- **`MIGRATE_PSP` has no generated-code demonstration** -- planning-level
  guarantees only.
- **Java/Spring Boot + Maven only.** No Gradle, Kotlin or multi-module support yet.
- **Corpus is small** (4 apps). Rates from it are directional, not statistically tight.
- **Run history** written by the API is fail-open telemetry; a database outage
  never fails a run, but the run will then be missing from history.

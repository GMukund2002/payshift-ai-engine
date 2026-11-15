# PayShift AI — Architecture

```
User Repository
      |
      v
Repository Discovery  ----------------  java-analyzer (JavaParser, deterministic)
      |
      v
LLM Repository Understanding  -------  agent/understanding.py (Agent 1)
      |
      v
Provider Identification  ------------  schemas/providers.py (evidence-based, data-driven registry)
      |
      v
Provider-Neutral Capability Model  --  schemas/capabilities.py (agent/understanding.build_payment_ir)
      |
      v
Dynamic Documentation Discovery  ----  rag/discovery.py (trusted domains + user-approved URLs)
      |
      v
Documentation Ingestion + RAG  ------  rag/ingestion.py, rag/retrieval.py (ChromaDB)
      |
      v
LLM Integration Planning  -----------  agent/planning.py (Agent 3)
      |
      v
Java Code Generation  ---------------  agent/generation.py (Agent 4)
      |
      v
Isolated Workspace  ------------------ agent/apply_patch.py (workspaces/<run_id>/{original,modified})
      |
      v
Deterministic Static Checks  --------- agent/static_checks.py -> java-analyzer --check-wiring
      |                                (beans, @Value placeholders, stubs, unused credentials,
      |                                 unimplemented interfaces, unreachable integrations)
      v
Maven Compilation + JUnit Tests  ----  tools/java_tools.py (real subprocess, real surefire parsing,
      |                                classpath-backed hints for compile errors)
      v
Agentic Diagnosis + Repair  ---------  agent/repair.py (Agent 5; scoped edits; separate budgets:
      |                                2 for static-check failures, 2 for compile/test failures)
      v
Final Integration Report  -----------  agent/reporting.py / schemas/reports.py
```

Orchestrated by a real LangGraph `StateGraph` (`agent/graph.py`) with 15 nodes
(the spec's 14 plus `static_checks`). Routing is driven by actual state,
not hardcoded to a provider or outcome:

- Any node that sets `state["blocked"]` short-circuits straight to
  `generate_report` — this is the single rule that implements "stop
  unsupported code generation and report the blocker," "report missing
  documentation," and "no LLM configured" all at once.
- `apply_patch` → `static_checks` → `compile_project`. A static-check failure
  routes to `diagnose_failures` → `repair_code` with its own budget
  (`MAX_STATIC_REPAIR_ATTEMPTS = 2`), so a one-second deterministic finding never
  consumes the attempts the real build needs.
- `compile_project` / `run_tests` failures route through
  `diagnose_failures` → `repair_code` → `apply_patch` → `static_checks` →
  `compile_project`, bounded to `MAX_REPAIR_ATTEMPTS = 2`.
- A repair whose every file was out of scope (protected tests, unplanned existing
  files, build files) changes nothing, so it skips straight to the next diagnosis
  instead of re-running an unchanged build.

## What VERIFIED means

`VERIFIED` requires all of: the run was not blocked, the static checks passed,
the project compiled, and a test run executed at least one test with zero
failures/errors against the final code. Anything else is `UNRESOLVED_FAILURE`
(or `BLOCKED` if no code was ever applied).

That bar is necessary but not sufficient: the app's existing tests rarely
exercise a *new* provider. Live run `f0d9df91493b` compiled, booted and passed
every existing test with an integration that sent every call unauthenticated,
stubbed its webhook handler, and was reachable from nowhere. The static checks
now catch each of those, and `evaluation/live_eval.py` measures the remaining
gap independently with hidden checks the pipeline never sees (see
`docs/evaluation.md`).

## Deterministic checks (`java-analyzer --check-wiring`)

JavaParser-based, no classpath needed, reported only for files the change
touched (pre-existing issues in the customer's code never block a run):

| check | catches |
|---|---|
| `missing_bean` | injected type no bean provides (e.g. `RestTemplate`, which Boot does not auto-configure) -- the ApplicationContext would fail and every test error |
| `ambiguous_bean` | a second bean for an injected interface with no `@Primary`/`@Qualifier` |
| `unresolved_placeholder` | `@Value("${key}")` with no default and no such key in `application.yml` |
| `stub_method` | bodies that only log / return null / throw "not implemented", or carry "implement this" comments |
| `unimplemented_interface` | a new interface nothing implements |
| `unused_config_value` | an injected credential that is never used (calls go out unauthenticated) |
| `unreachable_integration` | a new service/component that nothing injects |
| `duplicate_type_name` | a new type reusing an existing project type's name in another package (a hallucinated import "fixed" by inventing a parallel type) |

Types are matched by fully qualified name, resolved per file from its package and imports.

Compile failures are also enriched deterministically: every missing class is
looked up in the project's real Maven classpath, so repair is told "X lives in
package Q, fix the import" instead of guessing at a missing dependency
(`tools/compile_diagnostics.py`).

## Why no hardcoded PSP in the core engine

Provider names appear in exactly two places: `java-analyzer`'s
`provider-signatures.json` (detection **evidence**, not orchestration — see
below) and `rag/provider_registry.py` (trusted documentation domains, also
data). Every agent node, every Pydantic schema, and the LangGraph routing
logic operate on opaque provider ids. Adding a new provider never requires
touching `agent/*.py` — only adding an entry to one of those two JSON/data
files, and even that is optional: an unregistered provider still works if
the user supplies a documentation URL (see `rag/discovery.py`).

## A real false-positive caught during development

The first version of `provider-signatures.json` included generic
class-name hints like `"Order"`, `"Payment"`, `"Refund"` for providers whose
real SDKs do have classes with those names (e.g. Razorpay's Java SDK
genuinely has a class called `Order`). Running the analyzer against the
sample app immediately misattributed our own `OrderRepository`,
`PaymentService`, etc. to Razorpay with "HIGH" confidence — a textbook
"do not force a provider identity when evidence is insufficient" failure.
Fixed by (1) trimming the generic hints and (2) requiring that a bare
class-name hint only counts as evidence when the *same file* also imports
something from that provider's actual package. See the Phase 2 commit for
the full writeup; the two regression fixtures in
`java-analyzer/src/test/resources/fixtures/` exist specifically to catch
this class of bug again.

## Workspace safety

`agent/apply_patch.py` never writes into the original repository. Every run
gets `workspaces/<run_id>/{original,modified}`; every generated file path is
checked for absolute paths and `..` traversal before being written, and
anything that fails that check is dropped with a logged error rather than
applied. `tests/test_apply_patch.py` proves this with a real path-traversal
attempt and a real absolute-path attempt, not just a unit-level mock.

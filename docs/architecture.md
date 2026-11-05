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
Maven Compilation + JUnit Tests  ----  tools/java_tools.py (real subprocess, real surefire parsing)
      |
      v
Agentic Diagnosis + Repair  ---------  agent/repair.py (Agent 5, bounded to 2 attempts)
      |
      v
Final Integration Report  -----------  agent/reporting.py / schemas/reports.py
```

Orchestrated by a real LangGraph `StateGraph` (`agent/graph.py`) with 14 nodes
matching the spec's required list exactly. Routing is driven by actual state,
not hardcoded to a provider or outcome:

- Any node that sets `state["blocked"]` short-circuits straight to
  `generate_report` — this is the single rule that implements "stop
  unsupported code generation and report the blocker," "report missing
  documentation," and "no LLM configured" all at once.
- `compile_project` / `run_tests` failures route through
  `diagnose_failures` → `repair_code` → `apply_patch` → `compile_project`,
  bounded to `MAX_REPAIR_ATTEMPTS = 2` total passes.

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

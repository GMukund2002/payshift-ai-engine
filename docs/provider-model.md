# Provider-Neutral Payment Model

Two layers, both provider-agnostic:

## 1. Repository analysis (`schemas/providers.py`)

Validated form of `java-analyzer`'s JSON output: `DetectedProvider` (id +
confidence + evidence strings), `PaymentClass` (file, role, interface
relationships), `PaymentOperation` (operation type, source file/class/method,
best-effort provider attribution), `ArchitectureAssessment`
(`provider_abstraction_exists`, `multiple_providers_supported`).

Provider attribution on an operation is **allowed to be `null`**. A
controller that delegates to a service doesn't "know" which provider it
uses, and the analyzer doesn't guess — see `resolveSingleProviderForClass`
in `JavaSourceAnalyzer.java`, which only attributes a provider when exactly
one provider's brand name appears in the enclosing class's field/parameter
types, and leaves it unresolved otherwise.

## 2. Canonical capability model (`schemas/capabilities.py`)

```python
PaymentCapabilityModel(
    operation_mode="ADD_PSP" | "MIGRATE_PSP",
    existing_providers=["stripe"],
    target_provider="razorpay",
    capabilities=[
        CapabilityEntry(
            operation="CREATE_PAYMENT",
            business_intent="collect_customer_payment",
            source_api="stripe:PaymentService.createPayment",
            target_support="REQUIRES_RESEARCH",  # never defaults to SUPPORTED
        ),
        ...
    ],
)
```

`target_support` starts at `REQUIRES_RESEARCH` for every entry
(`agent/understanding.build_payment_ir`) and is only ever upgraded by
`agent/planning.create_plan`, which enforces a **hard, code-level
guardrail**: an operation can never be marked `SUPPORTED` or
`PARTIALLY_SUPPORTED` if zero documentation passages were retrieved for it,
no matter what the LLM claims. See
`tests/test_planning.py::test_overrides_supported_claim_with_no_retrieved_passages`
— it feeds the planner a response that wrongly claims `CREATE_REFUND` is
`SUPPORTED` with zero retrieved passages, and asserts the override fires.

This is the single most important safety property in the whole system:
**"do not invent undocumented methods" is enforced in code, not just
requested in a prompt.**

## Why this matters for ADD_PSP vs MIGRATE_PSP

- **ADD_PSP**: the plan can reuse an existing provider abstraction if one
  exists and is structurally reusable (checked by
  `architecture.provider_abstraction_exists`, not by the interface's *name*
  — see the architecture doc's note on `StripePaymentGateway` being
  structurally generic despite its name). Existing providers are never
  removed from `existing_providers`.
- **MIGRATE_PSP**: `IntegrationPlan.cutover_checklist` and
  `preserved_historical_ownership_note` are mandatory fields specifically so
  the plan can never silently imply that historical payments move
  providers. `Payment.provider` (Java domain model) is set once at creation
  and never rewritten — migration only changes which provider *new*
  payments default to.

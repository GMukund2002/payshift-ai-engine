"""The live-evaluation corpus: real, compilable Spring Boot apps whose payment
integrations differ in the ways that matter for an automated change, each
paired with a target provider and the facts the hidden checks need.

Add a case by dropping a Maven project under sample-apps/ and appending an
EvalCase here. Every case must build and pass its own tests unmodified, and
the wiring checker must report nothing on its untouched sources.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_APPS = REPO_ROOT / "sample-apps"

# What generated code for a provider must contain somewhere if it really talks
# to that provider (its API host, or its SDK's package).
PROVIDER_EVIDENCE = {
    "razorpay": ["api.razorpay.com", "com.razorpay."],
    "stripe": ["api.stripe.com", "com.stripe."],
    "adyen": ["adyen.com", "com.adyen."],
    "paypal": ["paypal.com", "com.paypal."],
}


@dataclass(frozen=True)
class EvalCase:
    name: str
    app_dir: str                 # under sample-apps/
    base_package: str            # the @SpringBootApplication package (hidden test goes here)
    existing_providers: frozenset[str]
    target_provider: str
    baseline_tests: int          # tests the app ships with (all must still run and pass)
    operation_mode: str = "ADD_PSP"
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    # Held-out cases are never used to develop fixes: the pipeline is run on them
    # unchanged to estimate how results carry over to codebases it wasn't tuned on.
    held_out: bool = False

    @property
    def path(self) -> Path:
        return SAMPLE_APPS / self.app_dir


CORPUS: list[EvalCase] = [
    EvalCase(
        name="merchant-app",
        app_dir="merchant-app", base_package="com.payshift.merchant",
        existing_providers=frozenset({"stripe"}), target_provider="razorpay", baseline_tests=9,
        notes="Stripe behind a provider-named port (StripePaymentGateway), webhooks, idempotency.",
        tags=("abstraction:provider-specific", "webhooks", "sdk"),
    ),
    EvalCase(
        name="stripe-direct-checkout",
        app_dir="stripe-direct-checkout", base_package="com.acme.checkout",
        existing_providers=frozenset({"stripe"}), target_provider="razorpay", baseline_tests=5,
        notes="StripeClient called directly from the service layer; no provider abstraction.",
        tags=("abstraction:none", "sdk"),
    ),
    EvalCase(
        name="razorpay-rest-orders",
        app_dir="razorpay-rest-orders", base_package="com.shop.orders",
        existing_providers=frozenset({"razorpay"}), target_provider="stripe", baseline_tests=5,
        notes="Razorpay over raw REST (RestClient, endpoint in application.yml), HMAC webhooks; no SDK.",
        tags=("abstraction:none", "rest", "webhooks"),
    ),
    EvalCase(
        name="multi-psp-router",
        app_dir="multi-psp-router", base_package="com.payments.router",
        existing_providers=frozenset({"stripe", "paypal"}), target_provider="razorpay", baseline_tests=4,
        notes="PaymentProvider port with Stripe (SDK) + PayPal (REST) adapters; currency router over "
              "List<PaymentProvider>; refunds route to the owning provider.",
        tags=("abstraction:generic", "router", "sdk", "rest"),
    ),
]


HELD_OUT: list[EvalCase] = [
    EvalCase(
        name="heldout-subscriptions-lombok", held_out=True,
        app_dir="heldout-subscriptions-lombok", base_package="com.billing.subs",
        existing_providers=frozenset({"stripe"}), target_provider="razorpay", baseline_tests=3,
        notes="Lombok throughout (@RequiredArgsConstructor, @Slf4j, @Getter), feature packages, StripeClient.",
        tags=("lombok", "sdk", "abstraction:none"),
    ),
    EvalCase(
        name="heldout-storefront-paypal", held_out=True,
        app_dir="heldout-storefront-paypal", base_package="com.store.front",
        existing_providers=frozenset({"paypal"}), target_provider="stripe", baseline_tests=3,
        notes="PayPal over RestTemplate injected by type with no qualifier: a second RestTemplate bean "
              "breaks the existing client.",
        tags=("rest", "abstraction:none", "bean-ambiguity-trap"),
    ),
    EvalCase(
        name="heldout-invoices-jdbc", held_out=True,
        app_dir="heldout-invoices-jdbc", base_package="com.ledger.invoices",
        existing_providers=frozenset({"stripe"}), target_provider="razorpay", baseline_tests=3,
        notes="JdbcTemplate + schema.sql (no JPA), application.properties, Stripe's static SDK API.",
        tags=("jdbc", "properties", "sdk", "abstraction:none"),
    ),
]


def by_name(names: list[str] | None, split: str = "dev") -> list[EvalCase]:
    """split: "dev" (the development corpus), "held-out", or "all". Explicit names win."""
    everything = CORPUS + HELD_OUT
    if not names:
        return {"dev": list(CORPUS), "held-out": list(HELD_OUT), "all": everything}[split]
    known = {c.name: c for c in everything}
    missing = [n for n in names if n not in known]
    if missing:
        raise SystemExit(f"Unknown eval case(s): {missing}. Known: {sorted(known)}")
    return [known[n] for n in names]

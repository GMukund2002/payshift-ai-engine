"""Trusted documentation sources, keyed by provider id.

This is data, not orchestration logic: the core RAG pipeline (ingestion.py,
discovery.py, retrieval.py) never branches on a provider id directly. It only
asks this registry two things -- "what are this provider's official domains
(for trust checks)" and "what seed URLs should I start indexing from" -- and
treats providers it has never heard of generically (Phase 4's dynamic
discovery path: ask the user for a documentation URL, verify it looks like
a real docs domain, and proceed with that single URL as a user-approved
source rather than refusing outright).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderDocsSource:
    provider_id: str
    official_domains: list[str]
    seed_urls: list[str] = field(default_factory=list)


KNOWN_PROVIDER_DOCS: dict[str, ProviderDocsSource] = {
    "stripe": ProviderDocsSource(
        provider_id="stripe",
        official_domains=["stripe.com", "docs.stripe.com"],
        seed_urls=[
            "https://docs.stripe.com/api/payment_intents/create",
            "https://docs.stripe.com/api/payment_intents/retrieve",
            "https://docs.stripe.com/api/refunds/create",
            "https://docs.stripe.com/webhooks",
        ],
    ),
    "razorpay": ProviderDocsSource(
        provider_id="razorpay",
        official_domains=["razorpay.com"],
        seed_urls=[
            "https://razorpay.com/docs/api/payments/",
            "https://razorpay.com/docs/api/refunds/",
            "https://razorpay.com/docs/webhooks/",
        ],
    ),
    "adyen": ProviderDocsSource(
        provider_id="adyen",
        official_domains=["adyen.com", "docs.adyen.com"],
        seed_urls=[
            "https://docs.adyen.com/api-explorer/Checkout/latest/post/payments",
            "https://docs.adyen.com/development-resources/webhooks/",
        ],
    ),
    "paypal": ProviderDocsSource(
        provider_id="paypal",
        official_domains=["paypal.com", "developer.paypal.com"],
        seed_urls=[
            "https://developer.paypal.com/docs/api/orders/v2/",
            "https://developer.paypal.com/docs/api/payments/v2/",
            "https://developer.paypal.com/api/rest/webhooks/",
        ],
    ),
    "cashfree": ProviderDocsSource(
        provider_id="cashfree",
        official_domains=["cashfree.com", "docs.cashfree.com"],
        seed_urls=[
            "https://docs.cashfree.com/reference/pg-create-order",
            "https://docs.cashfree.com/reference/pg-new-refund",
        ],
    ),
}


def is_official_domain(provider_id: str, url_host: str) -> bool:
    source = KNOWN_PROVIDER_DOCS.get(provider_id)
    if source is None:
        return False
    host = url_host.lower()
    return any(host == d or host.endswith("." + d) for d in source.official_domains)


def looks_like_documentation_host(url_host: str) -> bool:
    """Loose heuristic used only to warn (never to silently auto-trust) when a
    user supplies a documentation URL for a provider we don't have a registry
    entry for yet."""
    host = url_host.lower()
    return any(token in host for token in ("docs.", "developer.", "/docs", "api."))

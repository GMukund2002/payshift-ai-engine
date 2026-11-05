"""Provider-neutral payment capability model (Phase 3 / Phase 11 of the spec).

This is the canonical intermediate representation of payment business
behavior, independent of any PSP's concrete API shape. The LLM integration
planner (Phase 6) reads and writes this model; it must never be skipped in
favor of letting the LLM reason directly from raw repository text, so that
every planning decision is grounded in a structured, inspectable artifact.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

OperationMode = Literal["ADD_PSP", "MIGRATE_PSP"]

# How well the target provider is believed to support a given business capability.
# REQUIRES_RESEARCH is the honest default until documentation retrieval confirms
# one of the other states -- the model must never default to SUPPORTED.
TargetSupport = Literal[
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "UNSUPPORTED",
    "REQUIRES_RESEARCH",
    "MANUAL_REVIEW_REQUIRED",
]

BusinessIntent = Literal[
    "collect_customer_payment",
    "report_payment_status",
    "issue_refund",
    "receive_async_payment_event",
    "verify_event_authenticity",
    "fulfill_order_after_payment",
]


class DocumentationReference(BaseModel):
    title: str
    url: str
    provider_id: str
    retrieved_at: str | None = None


class CapabilityEntry(BaseModel):
    """One business capability, mapped from whatever the existing repository
    does today (source_api) onto whether/how the target provider supports it."""

    operation: str  # matches schemas.providers.PaymentOperationType values
    business_intent: BusinessIntent
    source_api: str  # e.g. "stripe:PaymentIntent.create" or "unknown" if unresolved
    target_support: TargetSupport = "REQUIRES_RESEARCH"
    target_api: str | None = None  # filled in once research resolves target_support
    documentation_refs: list[DocumentationReference] = Field(default_factory=list)
    notes: str | None = None


class PaymentCapabilityModel(BaseModel):
    operation_mode: OperationMode
    existing_providers: list[str]
    target_provider: str
    capabilities: list[CapabilityEntry] = Field(default_factory=list)
    currency_support: list[str] = Field(default_factory=list)
    idempotency_strategy: str | None = None
    manual_review_required: list[str] = Field(default_factory=list)
    unresolved_operations: list[str] = Field(default_factory=list)

    def requires_research(self) -> list[CapabilityEntry]:
        return [c for c in self.capabilities if c.target_support == "REQUIRES_RESEARCH"]

    def has_blocking_gaps(self) -> bool:
        return any(c.target_support == "UNSUPPORTED" for c in self.capabilities)

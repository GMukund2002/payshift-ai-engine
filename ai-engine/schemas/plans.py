"""Structured integration plan (Phase 6 output). Validated with Pydantic so the
code-generation agent (Phase 8) consumes a verified plan rather than free text."""
from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.capabilities import OperationMode, PaymentCapabilityModel


class FileChange(BaseModel):
    path: str
    reason: str
    change_type: str  # "CREATE" | "MODIFY"


class ManualReviewItem(BaseModel):
    description: str
    reason: str


class IntegrationPlan(BaseModel):
    operation_mode: OperationMode
    existing_providers: list[str]
    target_provider: str
    capability_model: PaymentCapabilityModel

    reuse_existing_abstraction: bool
    abstraction_interface: str | None = None  # name of the interface being reused, if any

    required_changes: list[str] = Field(default_factory=list)
    files_to_create: list[FileChange] = Field(default_factory=list)
    files_to_modify: list[FileChange] = Field(default_factory=list)

    documentation_references: list[str] = Field(default_factory=list)
    security_requirements: list[str] = Field(default_factory=list)
    unsupported_functionality: list[str] = Field(default_factory=list)
    testing_requirements: list[str] = Field(default_factory=list)
    manual_review_items: list[ManualReviewItem] = Field(default_factory=list)

    # MIGRATE_PSP-specific; empty for ADD_PSP
    cutover_checklist: list[str] = Field(default_factory=list)
    preserved_historical_ownership_note: str | None = None

    def is_blocked(self) -> bool:
        return self.capability_model.has_blocking_gaps() and not self.unsupported_functionality

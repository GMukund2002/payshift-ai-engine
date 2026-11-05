"""Pydantic models mirroring the JSON the Java repository analyzer emits.

These are the Python-side validated view of java-analyzer's output (Phase 2).
Nothing here hardcodes a specific PSP: `name` is an opaque provider id
("stripe", "razorpay", or any id the analyzer's data-driven signature
registry produced) that the rest of the engine treats as a label, never as
a branch target.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["HIGH", "MEDIUM", "LOW"]

PaymentOperationType = Literal[
    "CREATE_PAYMENT",
    "GET_PAYMENT_STATUS",
    "CREATE_REFUND",
    "HANDLE_WEBHOOK",
    "VERIFY_WEBHOOK_SIGNATURE",
    "FULFILL_ORDER",
]

ClassRole = Literal[
    "CONTROLLER", "SERVICE", "PROVIDER_GATEWAY", "WEBHOOK_HANDLER",
    "REPOSITORY", "DOMAIN", "CONFIG", "COMPONENT", "OTHER",
]


class MavenDependency(BaseModel):
    group_id: str | None = Field(alias="groupId", default=None)
    artifact_id: str | None = Field(alias="artifactId", default=None)
    version: str | None = None

    model_config = {"populate_by_name": True}


class DetectedProvider(BaseModel):
    name: str
    confidence: Confidence
    evidence: list[str] = Field(default_factory=list)


class PaymentClass(BaseModel):
    file: str
    class_name: str = Field(alias="className")
    role: ClassRole
    is_interface: bool = Field(alias="isInterface")
    implemented_by: list[str] = Field(alias="implementedBy", default_factory=list)
    implements_interfaces: list[str] = Field(alias="implementsInterfaces", default_factory=list)

    model_config = {"populate_by_name": True}


class PaymentOperation(BaseModel):
    operation: PaymentOperationType
    source_file: str = Field(alias="sourceFile")
    class_name: str = Field(alias="className")
    method: str
    provider: str | None = None

    model_config = {"populate_by_name": True}


class ArchitectureAssessment(BaseModel):
    provider_abstraction_exists: bool = Field(alias="providerAbstractionExists")
    multiple_providers_supported: bool = Field(alias="multipleProvidersSupported")
    abstraction_interfaces: list[str] = Field(alias="abstractionInterfaces", default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class RepositoryAnalysis(BaseModel):
    """Validated form of java-analyzer's full JSON report for one repository."""

    repository_path: str = Field(alias="repositoryPath")
    dependencies: list[MavenDependency] = Field(default_factory=list)
    detected_providers: list[DetectedProvider] = Field(alias="detectedProviders", default_factory=list)
    payment_classes: list[PaymentClass] = Field(alias="paymentClasses", default_factory=list)
    payment_operations: list[PaymentOperation] = Field(alias="paymentOperations", default_factory=list)
    architecture: ArchitectureAssessment
    errors: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    def confident_provider_ids(self) -> list[str]:
        return [p.name for p in self.detected_providers if p.confidence in ("HIGH", "MEDIUM")]

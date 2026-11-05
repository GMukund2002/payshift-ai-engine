"""Final integration/migration report (Phase 27 output format) and the structured
verification results it is built from. These are produced from REAL subprocess
output (mvn/junit), never fabricated -- see verification.py."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TestCaseResult(BaseModel):
    name: str
    status: str  # "PASSED" | "FAILED" | "ERROR" | "SKIPPED"
    message: str | None = None


class CompilationResult(BaseModel):
    success: bool
    raw_output_tail: str
    duration_seconds: float


class TestRunResult(BaseModel):
    success: bool
    tests_run: int
    failures: int
    errors: int
    skipped: int
    cases: list[TestCaseResult] = Field(default_factory=list)
    raw_output_tail: str
    duration_seconds: float


class RepairAttempt(BaseModel):
    attempt_number: int
    failure_summary: str
    diagnosis: str
    patch_description: str
    files_touched: list[str]
    recompiled: bool
    recompile_success: bool | None = None
    retest_success: bool | None = None


class VerificationResult(BaseModel):
    compilation: CompilationResult
    tests: TestRunResult | None = None
    protected_tests: TestRunResult | None = None
    repair_attempts: list[RepairAttempt] = Field(default_factory=list)
    final_status: str  # "VERIFIED" | "UNRESOLVED_FAILURE" | "BLOCKED_ON_DOCUMENTATION"


class IntegrationReport(BaseModel):
    operation_mode: str
    existing_providers: list[str]
    target_provider: str

    architecture_implemented: str
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)

    verification: VerificationResult | None = None

    documentation_citations: list[str] = Field(default_factory=list)
    unsupported_functionality: list[str] = Field(default_factory=list)
    manual_review_items: list[str] = Field(default_factory=list)

    commands_to_run: list[str] = Field(default_factory=list)
    reproduction_steps: list[str] = Field(default_factory=list)
    known_limitations: list[str] = Field(default_factory=list)

    workspace_path: str | None = None

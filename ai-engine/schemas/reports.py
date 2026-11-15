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


class RejectedFile(BaseModel):
    path: str
    reason: str


class RepairAttempt(BaseModel):
    attempt_number: int
    failure_summary: str
    diagnosis: str
    patch_description: str
    files_touched: list[str]
    files_rejected: list[RejectedFile] = Field(default_factory=list)
    patch_applied: bool = True  # False: every file the repair returned was out of scope
    recompiled: bool
    recompile_success: bool | None = None
    retest_success: bool | None = None


class StaticCheckFinding(BaseModel):
    check: str        # e.g. "unresolved_placeholder", "missing_bean", "stub_method"
    severity: str     # "ERROR" blocks verification; "WARNING" is reported only
    file: str
    message: str
    line: int | None = None


class StaticCheckResult(BaseModel):
    passed: bool
    findings: list[StaticCheckFinding] = Field(default_factory=list)


class LLMUsageSummary(BaseModel):
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    models: list[str] = Field(default_factory=list)
    by_step: dict[str, dict[str, int]] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    # None when the run never reached a compile because deterministic static
    # checks still failed after the repair budget ran out.
    compilation: CompilationResult | None = None
    tests: TestRunResult | None = None
    static_checks: StaticCheckResult | None = None
    protected_tests: TestRunResult | None = None
    repair_attempts: list[RepairAttempt] = Field(default_factory=list)
    final_status: str  # "VERIFIED" | "UNRESOLVED_FAILURE"


class IntegrationReport(BaseModel):
    operation_mode: str
    existing_providers: list[str]
    target_provider: str
    final_status: str = "UNKNOWN"  # "VERIFIED" | "UNRESOLVED_FAILURE" | "BLOCKED"

    architecture_implemented: str
    # What is actually different in the workspace vs the original repository,
    # computed from disk -- not what the plan said it would do.
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    # What the plan intended, for comparison (and for runs blocked before
    # anything was written).
    planned_files_to_create: list[str] = Field(default_factory=list)
    planned_files_to_modify: list[str] = Field(default_factory=list)

    verification: VerificationResult | None = None
    llm_usage: LLMUsageSummary | None = None
    blocker_reason: str | None = None

    documentation_citations: list[str] = Field(default_factory=list)
    unsupported_functionality: list[str] = Field(default_factory=list)
    manual_review_items: list[str] = Field(default_factory=list)

    commands_to_run: list[str] = Field(default_factory=list)
    reproduction_steps: list[str] = Field(default_factory=list)
    known_limitations: list[str] = Field(default_factory=list)

    workspace_path: str | None = None

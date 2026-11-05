"""Shared LangGraph state. A plain TypedDict (LangGraph's native state shape)
rather than a Pydantic model, because every node returns a partial dict of
updates that LangGraph merges into the running state -- Pydantic validation
on every partial merge would fight that pattern. Each field that corresponds
to a Pydantic model elsewhere (RepositoryAnalysis, PaymentCapabilityModel,
IntegrationPlan, IntegrationReport) is stored as its `.model_dump()` dict and
re-validated at the point it's consumed.
"""
from __future__ import annotations

from typing import Any, TypedDict

MAX_REPAIR_ATTEMPTS = 2


class AgentState(TypedDict, total=False):
    # inputs
    repository_path: str
    operation_mode: str  # "ADD_PSP" | "MIGRATE_PSP"
    target_provider: str
    target_provider_doc_url: str | None
    run_id: str

    # inspect_repository / detect_providers
    repository_analysis: dict[str, Any]
    existing_providers: list[str]

    # understand_architecture
    architecture_findings: dict[str, Any]

    # build_payment_ir
    capability_model: dict[str, Any]

    # research_provider / retrieve_documentation
    documentation_indexed: dict[str, Any]
    retrieved_passages: dict[str, list[dict[str, Any]]]  # operation -> passages

    # create_plan
    integration_plan: dict[str, Any]

    # generate_code / apply_patch
    generated_files: list[dict[str, str]]  # [{path, content}]
    workspace_path: str
    changes_diff: str

    # compile_project / run_tests
    compilation_result: dict[str, Any]
    test_result: dict[str, Any]

    # diagnose_failures / repair_code
    diagnosis: dict[str, Any]
    repair_attempts: list[dict[str, Any]]
    repair_count: int

    # generate_report
    report: dict[str, Any]

    # cross-cutting
    blocked: bool
    blocker_reason: str | None
    errors: list[str]
    final_status: str

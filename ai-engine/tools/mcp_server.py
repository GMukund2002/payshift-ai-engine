"""Phase 12: local MCP server exposing PayShift's deterministic tools so a
LangGraph agent (or any other MCP client) can call them directly.

Every tool that takes a filesystem path is restricted to paths inside this
repository (sample-apps/ or workspaces/) via _ensure_approved -- this server
is explicitly local-only and never reads or executes arbitrary host paths.

Note: this module deliberately does NOT use `from __future__ import annotations`.
The installed FastMCP version inspects parameter annotations at decoration time
via raw `issubclass()` checks that don't resolve postponed (string) annotations,
so turning those on breaks tool registration for every function with a
non-trivial type hint (e.g. `str | None`).
"""
import json
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from agent import understanding
from agent.apply_patch import UnsafePathError, _validate_relative_path
from tools.documentation_tools import search_provider_docs as _search_provider_docs
from tools.java_tools import run_tests as _run_tests
from tools.repository_tools import RepositoryAnalysisError, analyze_repository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("payshift.mcp_server")

AI_ENGINE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = AI_ENGINE_ROOT.parent
APPROVED_ROOTS = [REPO_ROOT / "sample-apps", REPO_ROOT / "workspaces"]

MAX_FILE_READ_CHARS = 50_000

mcp = FastMCP("payshift-ai")


class UnapprovedPathError(ValueError):
    pass


def _ensure_approved(path_str: str) -> Path:
    path = Path(path_str).resolve()
    if not any(path.is_relative_to(root.resolve()) for root in APPROVED_ROOTS):
        raise UnapprovedPathError(
            f"'{path}' is outside the approved workspace roots {[str(r) for r in APPROVED_ROOTS]}"
        )
    return path


@mcp.tool()
def inspect_repository(repository_path: str) -> dict:
    """Run the deterministic JavaParser-based analyzer against a repository and
    return its full structured findings (dependencies, detected providers,
    payment classes, payment operations, architecture assessment)."""
    approved = _ensure_approved(repository_path)
    try:
        analysis = analyze_repository(approved)
    except RepositoryAnalysisError as e:
        return {"error": str(e)}
    return analysis.model_dump(by_alias=True)


@mcp.tool()
def discover_payment_providers(repository_path: str) -> dict:
    """Return only the provider-detection evidence for a repository (a focused
    subset of inspect_repository, for when the caller only needs provider ids)."""
    approved = _ensure_approved(repository_path)
    try:
        analysis = analyze_repository(approved)
    except RepositoryAnalysisError as e:
        return {"error": str(e)}
    return {
        "detected_providers": [p.model_dump() for p in analysis.detected_providers],
        "confident_provider_ids": analysis.confident_provider_ids(),
        "architecture": analysis.architecture.model_dump(by_alias=True),
    }


@mcp.tool()
def get_payment_capabilities(repository_path: str, target_provider: str) -> dict:
    """Build the provider-neutral payment capability model (one entry per
    distinct payment operation detected in the repository) for a given target
    provider. target_support starts at REQUIRES_RESEARCH for every entry until
    documentation retrieval and planning resolve it."""
    approved = _ensure_approved(repository_path)
    try:
        analysis = analyze_repository(approved)
    except RepositoryAnalysisError as e:
        return {"error": str(e)}

    state = {
        "repository_analysis": analysis.model_dump(by_alias=True),
        "operation_mode": "ADD_PSP",
        "existing_providers": analysis.confident_provider_ids(),
        "target_provider": target_provider,
    }
    return understanding.build_payment_ir(state)["capability_model"]


@mcp.tool()
def search_provider_docs(query: str, provider_id: str, operation: str | None = None, top_k: int = 5) -> list[dict]:
    """Semantic search over indexed, trust-tagged provider documentation. Returns
    passages with their source_url and trust_level (OFFICIAL_VERIFIED or
    USER_APPROVED) so callers can judge how much to trust each result."""
    results = _search_provider_docs(query=query, provider_id=provider_id, operation=operation, top_k=top_k)
    return [
        {
            "text": r.text, "source_url": r.source_url, "title": r.title,
            "trust_level": r.trust_level, "code_block": r.code_block, "distance": r.distance,
        }
        for r in results
    ]


@mcp.tool()
def read_repository_file(repository_path: str, relative_path: str) -> str:
    """Read one file's content from an approved repository/workspace path.
    Truncated to MAX_FILE_READ_CHARS to keep responses bounded."""
    approved_root = _ensure_approved(repository_path)
    try:
        rel = _validate_relative_path(relative_path)
    except UnsafePathError as e:
        return f"ERROR: {e}"
    full_path = approved_root / rel
    if not full_path.is_relative_to(approved_root) or not full_path.is_file():
        return f"ERROR: file not found or outside repository: {relative_path}"
    text = full_path.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_FILE_READ_CHARS:
        return text[:MAX_FILE_READ_CHARS] + f"\n...[truncated, {len(text)} total chars]"
    return text


@mcp.tool()
def run_java_tests(project_path: str, test_class: str | None = None) -> dict:
    """Run the real Maven/JUnit test suite for a project (sample app or a
    workspace's modified copy) and return structured, parsed results."""
    approved = _ensure_approved(project_path)
    result = _run_tests(approved, test_class=test_class)
    return result.model_dump()


@mcp.tool()
def get_integration_report(workspace_path: str) -> dict:
    """Read the report.json written by generate_report for a given run's
    workspace (expects workspace_path to be the .../workspaces/<run_id>/modified
    directory, or its parent)."""
    approved = _ensure_approved(workspace_path)
    run_dir = approved if approved.name != "modified" else approved.parent
    report_file = run_dir / "report.json"
    if not report_file.is_file():
        return {"error": f"No report.json found at {report_file}"}
    return json.loads(report_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    mcp.run()

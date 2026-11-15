"""Graph node: apply_patch (deterministic, no LLM).

Workspace safety per spec Phase 8: the uploaded/original repository is never
touched. Every run gets workspaces/<run_id>/{original,modified}; generated
files are written only into `modified`, after rejecting any path that is
absolute, escapes the workspace via "..", or isn't a plain relative file path.

Two pieces of state drive it:
- `pending_patch`: the files to write on THIS pass (the initial generation,
  or one repair's patch). Cleared once applied.
- `generated_files`: the cumulative set of every file written this run,
  latest content per path. Kept across repairs so later diagnosis/repair
  passes and the report see the whole change, not just the last patch.

What the report calls "created"/"modified" -- and the diff -- are computed
by comparing `modified` against `original` for every path touched this run,
i.e. from what is actually on disk, never from what the plan said it would do.
"""
from __future__ import annotations

import difflib
import json
import logging
import shutil
import uuid
from pathlib import Path

from agent.state import AgentState

logger = logging.getLogger("payshift.agent.apply_patch")

AI_ENGINE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = AI_ENGINE_ROOT.parent
WORKSPACES_ROOT = REPO_ROOT / "workspaces"

_COPY_IGNORE = shutil.ignore_patterns("target", "build", ".git", "node_modules", ".gradle", ".idea")


class UnsafePathError(ValueError):
    pass


def _validate_relative_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        raise UnsafePathError(f"Absolute path not allowed: {path_str}")
    if ".." in path.parts:
        raise UnsafePathError(f"Path traversal not allowed: {path_str}")
    return path


def is_test_source_path(path_str: str) -> bool:
    return "src/test/" in path_str.replace("\\", "/")


def apply_patch(state: AgentState) -> dict:
    run_id = state.get("run_id") or uuid.uuid4().hex[:12]
    workspace_root = WORKSPACES_ROOT / run_id
    original_dir = workspace_root / "original"
    modified_dir = workspace_root / "modified"

    repository_path = Path(state["repository_path"])
    workspace_root.mkdir(parents=True, exist_ok=True)
    if not original_dir.exists():
        shutil.copytree(repository_path, original_dir, dirs_exist_ok=True, ignore=_COPY_IGNORE)
    if not modified_dir.exists():
        shutil.copytree(repository_path, modified_dir, dirs_exist_ok=True, ignore=_COPY_IGNORE)

    # Callers that predate pending_patch (benchmark, older tests) pass only
    # generated_files; treat that as the patch to apply.
    pending = state.get("pending_patch")
    patch = pending if pending is not None else state.get("generated_files", [])

    touched = list(state.get("touched_paths", []))
    cumulative = {f["path"]: f["content"] for f in state.get("generated_files", [])}
    rejected: list[dict] = []

    for file in patch:
        try:
            rel_path = _validate_relative_path(file["path"])
        except UnsafePathError as e:
            logger.error("Refusing to apply generated file: %s", e)
            rejected.append({"path": file["path"], "reason": str(e)})
            continue

        target = modified_dir / rel_path
        if not target.resolve().is_relative_to(modified_dir.resolve()):
            logger.error("Refusing to apply file that escapes workspace: %s", file["path"])
            rejected.append({"path": file["path"], "reason": "escapes workspace"})
            continue

        # Protected tests: an EXISTING test file is never overwritten, whatever
        # step asked for it (a planner CREATE on an existing path, a repair that
        # "fixes" a failure by editing the test). New test files are fine.
        if is_test_source_path(str(rel_path)) and (original_dir / rel_path).exists():
            logger.error("Refusing to overwrite protected existing test file: %s", rel_path)
            rejected.append({"path": str(rel_path), "reason": "protected existing test file"})
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file["content"], encoding="utf-8")
        cumulative[str(rel_path)] = file["content"]
        if str(rel_path) not in touched:
            touched.append(str(rel_path))

    created, modified_paths, diff_parts = _compare_touched(original_dir, modified_dir, touched)

    changes_diff = "\n".join(diff_parts)
    (workspace_root / "changes.diff").write_text(changes_diff, encoding="utf-8")
    if "integration_plan" in state:
        (workspace_root / "plan.json").write_text(json.dumps(state["integration_plan"], indent=2), encoding="utf-8")

    return {
        "run_id": run_id,
        "workspace_path": str(modified_dir),
        "changes_diff": changes_diff,
        "pending_patch": None,
        "generated_files": [{"path": p, "content": c} for p, c in cumulative.items()],
        "touched_paths": touched,
        "applied_changes": {"created": created, "modified": modified_paths},
        "rejected_patch_files": rejected,
    }


def _compare_touched(original_dir: Path, modified_dir: Path, touched: list[str]):
    created, modified_paths, diff_parts = [], [], []
    for rel in sorted(touched):
        before_path, after_path = original_dir / rel, modified_dir / rel
        before = before_path.read_text(encoding="utf-8", errors="replace") if before_path.is_file() else None
        after = after_path.read_text(encoding="utf-8", errors="replace") if after_path.is_file() else None
        if before == after:
            continue  # rewritten back to its original content -- not a change
        if before is None:
            created.append(rel)
        else:
            modified_paths.append(rel)
        diff_parts.append("".join(difflib.unified_diff(
            (before or "").splitlines(keepends=True), (after or "").splitlines(keepends=True),
            fromfile="/dev/null" if before is None else f"a/{rel}", tofile=f"b/{rel}",
        )))
    return created, modified_paths, diff_parts

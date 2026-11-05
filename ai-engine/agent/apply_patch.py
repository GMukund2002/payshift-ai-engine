"""Graph node: apply_patch (deterministic, no LLM).

Workspace safety per spec Phase 8: the uploaded/original repository is never
touched. Every run gets workspaces/<run_id>/{original,modified}; generated
files are written only into `modified`, after rejecting any path that is
absolute, escapes the workspace via "..", or isn't a plain relative file path.
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


class UnsafePathError(ValueError):
    pass


def _validate_relative_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        raise UnsafePathError(f"Absolute path not allowed: {path_str}")
    if ".." in path.parts:
        raise UnsafePathError(f"Path traversal not allowed: {path_str}")
    return path


def apply_patch(state: AgentState) -> dict:
    run_id = state.get("run_id") or uuid.uuid4().hex[:12]
    workspace_root = WORKSPACES_ROOT / run_id
    original_dir = workspace_root / "original"
    modified_dir = workspace_root / "modified"

    repository_path = Path(state["repository_path"])
    workspace_root.mkdir(parents=True, exist_ok=True)
    if not original_dir.exists():
        shutil.copytree(repository_path, original_dir, dirs_exist_ok=True,
                         ignore=shutil.ignore_patterns("target", ".git", "node_modules"))
    if not modified_dir.exists():
        shutil.copytree(repository_path, modified_dir, dirs_exist_ok=True,
                         ignore=shutil.ignore_patterns("target", ".git", "node_modules"))

    diff_parts: list[str] = []
    applied_files: list[str] = []

    for file in state.get("generated_files", []):
        try:
            rel_path = _validate_relative_path(file["path"])
        except UnsafePathError as e:
            logger.error("Refusing to apply generated file: %s", e)
            continue

        target = modified_dir / rel_path
        if target.resolve().is_relative_to(modified_dir.resolve()) is False:
            logger.error("Refusing to apply file that escapes workspace: %s", file["path"])
            continue

        old_text = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
        new_text = file["content"]

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_text, encoding="utf-8")
        applied_files.append(str(rel_path))

        diff_parts.append("".join(difflib.unified_diff(
            old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}",
        )))

    changes_diff = "\n".join(diff_parts)
    (workspace_root / "changes.diff").write_text(changes_diff, encoding="utf-8")
    if "integration_plan" in state:
        (workspace_root / "plan.json").write_text(json.dumps(state["integration_plan"], indent=2), encoding="utf-8")

    return {
        "run_id": run_id,
        "workspace_path": str(modified_dir),
        "changes_diff": changes_diff,
    }

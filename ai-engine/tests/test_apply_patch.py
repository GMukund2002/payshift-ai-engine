import uuid
from pathlib import Path

from agent.apply_patch import WORKSPACES_ROOT, apply_patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERCHANT_APP = REPO_ROOT / "sample-apps" / "merchant-app"


def _state(generated_files, run_id=None):
    return {
        "repository_path": str(MERCHANT_APP),
        "run_id": run_id or uuid.uuid4().hex[:12],
        "generated_files": generated_files,
    }


def test_never_modifies_the_original_repository():
    original_pom = (MERCHANT_APP / "pom.xml").read_text()
    result = apply_patch(_state([{"path": "pom.xml", "content": "TAMPERED"}]))
    assert (MERCHANT_APP / "pom.xml").read_text() == original_pom  # untouched
    assert Path(result["workspace_path"], "pom.xml").read_text() == "TAMPERED"


def test_rejects_path_traversal():
    run_id = uuid.uuid4().hex[:12]
    result = apply_patch(_state([{"path": "../../../etc/evil.txt", "content": "pwned"}], run_id=run_id))
    workspace_root = WORKSPACES_ROOT / run_id
    assert not (workspace_root.parent.parent / "etc" / "evil.txt").exists()
    assert "evil.txt" not in result["changes_diff"]


def test_rejects_absolute_path():
    run_id = uuid.uuid4().hex[:12]
    result = apply_patch(_state([{"path": "/tmp/evil.txt", "content": "pwned"}], run_id=run_id))
    assert not Path("/tmp/evil.txt").exists() or Path("/tmp/evil.txt").read_text() != "pwned"
    assert "evil.txt" not in result["changes_diff"]


def test_produces_a_real_diff_for_a_new_file():
    run_id = uuid.uuid4().hex[:12]
    new_content = "package com.example;\n\npublic class NewGateway {}\n"
    result = apply_patch(_state(
        [{"path": "src/main/java/com/example/NewGateway.java", "content": new_content}], run_id=run_id,
    ))
    assert "NewGateway" in result["changes_diff"]
    assert Path(result["workspace_path"], "src/main/java/com/example/NewGateway.java").read_text() == new_content

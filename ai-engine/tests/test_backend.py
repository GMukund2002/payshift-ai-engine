"""HTTP-level tests for backend/main.py's input validation, access gate,
upload hardening and run-concurrency cap. The pipeline itself is stubbed out
(it is covered end to end by test_graph_end_to_end.py); what's under test
here is the API boundary a public deploy exposes."""
import io
import sys
import threading
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend import main as backend  # noqa: E402
from storage import db  # noqa: E402

SAMPLE_APP = str((REPO_ROOT / "sample-apps" / "merchant-app").resolve())


@pytest.fixture(autouse=True)
def isolated_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEMO_ACCESS_KEY", raising=False)
    monkeypatch.setattr(db, "LOCAL_DB_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(db, "_schema_ready", set())
    yield


@pytest.fixture
def client():
    return TestClient(backend.app)


def _zip(entries: dict[str, bytes], symlinks: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, target)
    return buf.getvalue()


def _run_body(**overrides):
    body = {"repo_path": SAMPLE_APP, "operation_mode": "ADD_PSP", "target_provider": "razorpay"}
    body.update(overrides)
    return body


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("bad", [
    {"operation_mode": "DELETE_EVERYTHING"},
    {"target_provider": "<img src=x onerror=alert(1)>"},
    {"target_provider": "../../etc"},
    {"target_provider": ""},
])
def test_run_rejects_invalid_input(client, bad):
    assert client.post("/api/run", json=_run_body(**bad)).status_code == 422


def test_run_rejects_repo_path_outside_allowed_roots(client):
    assert client.post("/api/run", json=_run_body(repo_path="/etc")).status_code == 400


# ---------------------------------------------------------------- access gate

@pytest.mark.parametrize("method,path,kwargs", [
    ("post", "/api/run", {"json": _run_body()}),
    ("post", "/api/analyze", {"json": {"repo_path": SAMPLE_APP}}),
    ("post", "/api/upload", {"files": {"file": ("x.zip", b"PK", "application/zip")}}),
])
def test_costly_endpoints_require_demo_key_when_configured(client, monkeypatch, method, path, kwargs):
    monkeypatch.setenv("DEMO_ACCESS_KEY", "s3cret")
    assert getattr(client, method)(path, **kwargs).status_code == 401
    assert getattr(client, method)(path, headers={"X-Demo-Key": "wrong"}, **kwargs).status_code == 401


# ---------------------------------------------------------------- uploads

def test_upload_extracts_regular_files_and_skips_symlinks(client):
    data = _zip({"proj/pom.xml": b"<project/>"}, symlinks={"proj/evil": "/etc/passwd"})
    res = client.post("/api/upload", files={"file": ("p.zip", data, "application/zip")})
    assert res.status_code == 200, res.text
    root = Path(res.json()["repo_path"])
    assert (root / "pom.xml").read_bytes() == b"<project/>"
    assert not (root / "evil").exists()


def test_upload_rejects_path_traversal(client):
    data = _zip({"../escape.txt": b"x"})
    res = client.post("/api/upload", files={"file": ("p.zip", data, "application/zip")})
    assert res.status_code == 400


def test_upload_enforces_actual_uncompressed_size(client, monkeypatch):
    monkeypatch.setattr(backend, "MAX_ZIP_UNCOMPRESSED_BYTES", 1000)
    data = _zip({"big.bin": b"\0" * 5000})  # compresses tiny, inflates past the limit
    res = client.post("/api/upload", files={"file": ("p.zip", data, "application/zip")})
    assert res.status_code == 400
    assert "size limit" in res.json()["detail"]


def test_upload_rejects_oversized_archive_without_extracting(client, monkeypatch):
    monkeypatch.setattr(backend, "MAX_UPLOAD_BYTES", 10)
    res = client.post("/api/upload", files={"file": ("p.zip", b"x" * 100, "application/zip")})
    assert res.status_code == 413


# ---------------------------------------------------------------- runs

def test_run_is_visible_as_running_before_first_poll_and_releases_its_slot(client, monkeypatch):
    finished = threading.Event()
    monkeypatch.setattr(backend, "_execute_pipeline_inner", lambda *a, **k: finished.wait(5))

    run_id = client.post("/api/run", json=_run_body()).json()["run_id"]
    status = client.get(f"/api/runs/{run_id}/status")
    assert status.status_code == 200
    assert status.json()["status"] == "RUNNING"

    finished.set()
    # The slot is released in a finally block once the worker thread returns.
    for _ in range(50):
        if backend._run_slots.acquire(timeout=0.1):
            backend._run_slots.release()
            break
    else:
        pytest.fail("run slot was never released")


def test_run_beyond_concurrency_cap_is_rejected(client):
    assert backend._run_slots.acquire(blocking=False)
    try:
        res = client.post("/api/run", json=_run_body())
        assert res.status_code == 429
    finally:
        backend._run_slots.release()


# ---------------------------------------------------------------- storage

def test_sqlite_migrates_a_legacy_table_without_progress_column(tmp_path, monkeypatch):
    import sqlite3
    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy)
    conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, operation_mode TEXT, target_provider TEXT, "
                 "existing_providers TEXT, final_status TEXT, created_at TEXT, report_json TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "LOCAL_DB_PATH", legacy)

    db.start_run(run_id="r1", operation_mode="ADD_PSP", target_provider="razorpay")
    db.update_run_progress(run_id="r1", operation_mode="ADD_PSP", target_provider="razorpay",
                           progress=[{"node": "inspect_repository"}])
    assert db.get_run_status("r1")["progress"] == [{"node": "inspect_repository"}]

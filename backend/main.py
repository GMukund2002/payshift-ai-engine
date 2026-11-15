"""FastAPI backend for PayShift AI.

Replaces the Streamlit frontend's role (frontend/app.py still exists for
local/CLI reference but is no longer what's deployed). Every endpoint here
calls the exact same backend the Streamlit app did -- the java-analyzer
subprocess, the live RAG pipeline, and the real LangGraph StateGraph -- this
is a thin HTTP wrapper, not a reimplementation. Serves the static webapp/
dashboard too, so the whole thing is one deployable service.

/api/run is fire-and-forget + polling (POST starts a background thread and
returns a run_id immediately; GET /api/runs/{id}/status is what the client
polls), not a long-lived SSE stream. Found necessary running this for real
on a memory-constrained free-tier deploy: holding one HTTP connection open
for several minutes is fragile there, and if the container hiccups at all
mid-stream the whole run was silently lost with nothing recorded and the
client hung forever on a dead connection. Polling survives that: progress is
persisted after every node (storage/db.py), so a crash-and-restart mid-run
shows up as a stuck "RUNNING" row instead of nothing, and the client just
sees a few failed polls before recovering -- degraded, not broken.

Running the actual graph in a dedicated worker THREAD, not an asyncio task
on the main loop, matters too: graph.stream() calls
blocking subprocess.run() (mvn) and blocking HTTP (the LLM client) deep
inside it, which would otherwise freeze the whole event loop -- including
every other request, like the /status polling itself -- for the run's full
duration.

A shared DEMO_ACCESS_KEY env var, if set, gates every endpoint that costs
money or writes to disk (/api/upload, /api/analyze, /api/run -- real paid
LLM calls, real JVM subprocesses, real files) so a public deploy can't be
used by strangers to spend someone else's OpenAI budget or fill its disk.
Unset -- the default for local dev -- means no gate.

PAYSHIFT_MAX_CONCURRENT_RUNS (default 1) caps how many pipeline runs execute
at once in this process: each holds a real Maven JVM, and two at once on a
small container is exactly the OOM scenario java_tools.py's heap cap exists
for. A run beyond the cap is rejected with 429 rather than queued silently.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import shutil
import sys
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logger = logging.getLogger("payshift.backend")

BACKEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_ROOT.parent
AI_ENGINE_ROOT = REPO_ROOT / "ai-engine"
WEBAPP_DIR = REPO_ROOT / "webapp"
sys.path.insert(0, str(AI_ENGINE_ROOT))

from agent.graph import build_graph  # noqa: E402
from llm.client import NullLLMClient, get_llm_client  # noqa: E402
from storage.db import backend_label, get_run_status, list_runs, save_run_report, start_run, update_run_progress  # noqa: E402
from tools.repository_tools import RepositoryAnalysisError, analyze_repository  # noqa: E402

SAMPLE_APP = REPO_ROOT / "sample-apps" / "merchant-app"
UPLOADS_DIR = REPO_ROOT / "workspaces" / "uploads"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024          # compressed archive as received
MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 20_000
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

MAX_CONCURRENT_RUNS = max(1, int(os.environ.get("PAYSHIFT_MAX_CONCURRENT_RUNS") or 1))
_run_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)

app = FastAPI(title="PayShift AI API")


def _require_demo_key(x_demo_key: str | None) -> None:
    required = os.environ.get("DEMO_ACCESS_KEY")
    if required and not hmac.compare_digest((x_demo_key or "").encode(), required.encode()):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Demo-Key header")


def _safe_extract_zip(data: bytes) -> Path:
    """Extracts member by member, counting the bytes actually written rather
    than trusting each entry's self-declared file_size (which a crafted
    archive can understate). Skips symlink entries outright."""
    import io
    dest = UPLOADS_DIR / uuid.uuid4().hex[:12]
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise ValueError(f"Archive has more than {MAX_ZIP_ENTRIES} entries")
            written = 0
            for info in infos:
                name = info.filename
                if name.startswith("/") or "\\" in name or ".." in Path(name).parts:
                    raise ValueError(f"Refusing unsafe zip entry: {name}")
                is_symlink = (info.external_attr >> 16) & 0o170000 == 0o120000
                if is_symlink:
                    continue
                target = dest / name
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    while chunk := src.read(64 * 1024):
                        written += len(chunk)
                        if written > MAX_ZIP_UNCOMPRESSED_BYTES:
                            raise ValueError("Archive exceeds the 100MB uncompressed size limit")
                        out.write(chunk)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    children = list(dest.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return dest


def _resolve_repo_path(repo_path: str) -> Path:
    """Only the bundled sample app or something this process itself extracted
    under workspaces/uploads may be analyzed/run -- never an arbitrary path a
    caller names, since this endpoint is reachable over the public internet."""
    resolved = Path(repo_path).resolve()
    allowed_roots = [SAMPLE_APP.resolve(), UPLOADS_DIR.resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail=f"Repository path not allowed: {repo_path}")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {repo_path}")
    return resolved


@app.get("/api/health")
def health():
    llm = get_llm_client()
    return {
        "status": "ok",
        "llm_configured": not isinstance(llm, NullLLMClient),
        "data_backend": backend_label(),
    }


@app.get("/api/sample-app")
def sample_app():
    return {"repo_path": str(SAMPLE_APP.resolve())}


@app.post("/api/upload")
async def upload(file: UploadFile, x_demo_key: str | None = Header(default=None)):
    _require_demo_key(x_demo_key)
    # Read at most one byte past the limit instead of the whole body, so an
    # oversized upload is rejected without first being buffered into memory.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
    try:
        extracted = await asyncio.to_thread(_safe_extract_zip, data)
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"repo_path": str(extracted)}


class AnalyzeRequest(BaseModel):
    repo_path: str = Field(max_length=1024)


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest, x_demo_key: str | None = Header(default=None)):
    _require_demo_key(x_demo_key)
    resolved = _resolve_repo_path(req.repo_path)
    try:
        analysis = analyze_repository(resolved)
    except RepositoryAnalysisError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return analysis.model_dump(by_alias=True)


class RunRequest(BaseModel):
    repo_path: str = Field(max_length=1024)
    operation_mode: Literal["ADD_PSP", "MIGRATE_PSP"]
    # Provider ids are opaque labels but end up in file paths, prompts and the
    # dashboard's run history, so keep them to a boring, safe alphabet.
    target_provider: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    target_provider_doc_url: str | None = Field(default=None, max_length=2048)


def _execute_pipeline_sync(run_id: str, repository_path: str, req: "RunRequest") -> None:
    """Runs entirely in a worker thread (see module docstring) -- blocking
    subprocess/HTTP calls here must never run on the main event loop.
    Releases the concurrency slot acquired by run_pipeline, whatever happens."""
    try:
        _execute_pipeline_inner(run_id, repository_path, req)
    finally:
        _run_slots.release()


def _execute_pipeline_inner(run_id: str, repository_path: str, req: "RunRequest") -> None:
    initial_state = {
        "repository_path": repository_path,
        "operation_mode": req.operation_mode,
        "target_provider": req.target_provider,
        "target_provider_doc_url": req.target_provider_doc_url,
        "run_id": run_id,
    }

    accumulated = dict(initial_state)
    nodes_completed: list[dict] = []
    try:
        llm = get_llm_client()
        graph = build_graph(llm)
        for event in graph.stream(initial_state, config={"recursion_limit": 100}):
            for node_name, update in event.items():
                accumulated.update(update)
                nodes_completed.append({
                    "node": node_name,
                    "blocked": bool(update.get("blocked")),
                    "blocker_reason": update.get("blocker_reason"),
                })
                update_run_progress(
                    run_id=run_id, operation_mode=req.operation_mode,
                    target_provider=req.target_provider, progress=nodes_completed,
                )
    except Exception as e:
        logger.exception("Pipeline run %s crashed", run_id)
        save_run_report(
            run_id=run_id, operation_mode=req.operation_mode, target_provider=req.target_provider,
            existing_providers=accumulated.get("existing_providers", []),
            final_status=f"CRASHED: {e}", report=None, progress=nodes_completed,
        )
        return

    save_run_report(
        run_id=run_id,
        operation_mode=req.operation_mode,
        target_provider=req.target_provider,
        existing_providers=accumulated.get("existing_providers", []),
        final_status=accumulated.get("final_status") or accumulated.get("blocker_reason"),
        report=accumulated.get("report"),
        progress=nodes_completed,
    )


@app.post("/api/run")
async def run_pipeline(req: RunRequest, x_demo_key: str | None = Header(default=None)):
    _require_demo_key(x_demo_key)
    resolved = _resolve_repo_path(req.repo_path)
    if not _run_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail=f"{MAX_CONCURRENT_RUNS} run(s) already in progress on this server; try again when it finishes.",
        )
    try:
        run_id = uuid.uuid4().hex[:12]
        # Record the run BEFORE returning its id, so the client's very first
        # status poll finds a RUNNING row instead of a 404.
        await asyncio.to_thread(
            start_run, run_id=run_id, operation_mode=req.operation_mode, target_provider=req.target_provider,
        )
        # Fire-and-forget: start the real work in its own worker thread and return
        # immediately. The client polls /api/runs/{run_id}/status for progress --
        # see the module docstring for why this replaced a long-lived SSE stream.
        # A plain thread rather than asyncio.create_task(to_thread(...)): the run
        # (and the release of its concurrency slot) must not depend on an asyncio
        # task that the event loop could drop or cancel before it ever starts.
        threading.Thread(
            target=_execute_pipeline_sync, args=(run_id, str(resolved), req),
            name=f"payshift-run-{run_id}", daemon=True,
        ).start()
    except BaseException:
        _run_slots.release()
        raise
    return {"run_id": run_id}


@app.get("/api/runs")
def runs(limit: int = Query(default=20, ge=1, le=200)):
    return list_runs(limit=limit)


@app.get("/api/runs/{run_id}/status")
def run_status(run_id: str):
    status = get_run_status(run_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return status


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    status = get_run_status(run_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return status


# Static dashboard -- mounted last so it doesn't shadow the /api/* routes above.
app.mount("/", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")

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

Running the actual graph in a background THREAD (asyncio.to_thread), not
just an asyncio task on the main loop, matters too: graph.stream() calls
blocking subprocess.run() (mvn) and blocking HTTP (the LLM client) deep
inside it, which would otherwise freeze the whole event loop -- including
every other request, like the /status polling itself -- for the run's full
duration.

A shared DEMO_ACCESS_KEY env var, if set, gates the one costly endpoint
(/api/run, which makes real paid LLM calls and runs real compile/test
subprocesses) so a public deploy can't be used to spend someone else's
OpenAI budget by strangers hitting the URL. Unset -- the default for local
dev -- means no gate.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="PayShift AI API")


def _require_demo_key(x_demo_key: str | None) -> None:
    required = os.environ.get("DEMO_ACCESS_KEY")
    if required and x_demo_key != required:
        raise HTTPException(status_code=401, detail="Missing or invalid X-Demo-Key header")


def _safe_extract_zip(data: bytes) -> Path:
    import io
    dest = UPLOADS_DIR / uuid.uuid4().hex[:12]
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        total_size = 0
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"Refusing unsafe zip entry: {name}")
            total_size += info.file_size
            if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ValueError("Archive exceeds the 100MB uncompressed size limit")
        zf.extractall(dest)
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
async def upload(file: UploadFile):
    data = await file.read()
    try:
        extracted = _safe_extract_zip(data)
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"repo_path": str(extracted)}


class AnalyzeRequest(BaseModel):
    repo_path: str


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    resolved = _resolve_repo_path(req.repo_path)
    try:
        analysis = analyze_repository(resolved)
    except RepositoryAnalysisError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return analysis.model_dump(by_alias=True)


class RunRequest(BaseModel):
    repo_path: str
    operation_mode: str
    target_provider: str
    target_provider_doc_url: str | None = None


def _execute_pipeline_sync(run_id: str, repository_path: str, req: "RunRequest") -> None:
    """Runs entirely in a worker thread (see module docstring) -- blocking
    subprocess/HTTP calls here must never run on the main event loop."""
    initial_state = {
        "repository_path": repository_path,
        "operation_mode": req.operation_mode,
        "target_provider": req.target_provider,
        "target_provider_doc_url": req.target_provider_doc_url,
        "run_id": run_id,
    }
    start_run(run_id=run_id, operation_mode=req.operation_mode, target_provider=req.target_provider)

    accumulated = dict(initial_state)
    nodes_completed: list[dict] = []
    try:
        llm = get_llm_client()
        graph = build_graph(llm)
        for event in graph.stream(initial_state, config={"recursion_limit": 50}):
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
    run_id = uuid.uuid4().hex[:12]
    # Fire-and-forget: start the real work in a background thread and return
    # immediately. The client polls /api/runs/{run_id}/status for progress --
    # see the module docstring for why this replaced a long-lived SSE stream.
    asyncio.create_task(asyncio.to_thread(_execute_pipeline_sync, run_id, str(resolved), req))
    return {"run_id": run_id}


@app.get("/api/runs")
def runs(limit: int = 20):
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

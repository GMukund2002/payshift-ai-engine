"""FastAPI backend for PayShift AI.

Replaces the Streamlit frontend's role (frontend/app.py still exists for
local/CLI reference but is no longer what's deployed). Every endpoint here
calls the exact same backend the Streamlit app did -- the java-analyzer
subprocess, the live RAG pipeline, and the real LangGraph StateGraph -- this
is a thin HTTP wrapper, not a reimplementation. Serves the static webapp/
dashboard too, so the whole thing is one deployable service.

A shared DEMO_ACCESS_KEY env var, if set, gates the one costly endpoint
(/api/run, which makes real paid LLM calls and runs real compile/test
subprocesses) so a public deploy can't be used to spend someone else's
OpenAI budget by strangers hitting the URL. Unset -- the default for local
dev -- means no gate.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
import zipfile
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BACKEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_ROOT.parent
AI_ENGINE_ROOT = REPO_ROOT / "ai-engine"
WEBAPP_DIR = REPO_ROOT / "webapp"
sys.path.insert(0, str(AI_ENGINE_ROOT))

from agent.graph import build_graph  # noqa: E402
from llm.client import NullLLMClient, get_llm_client  # noqa: E402
from storage.db import backend_label, get_run_report, list_runs, save_run_report  # noqa: E402
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


@app.post("/api/run")
async def run_pipeline(req: RunRequest, x_demo_key: str | None = Header(default=None)):
    _require_demo_key(x_demo_key)
    resolved = _resolve_repo_path(req.repo_path)
    llm = get_llm_client()
    graph = build_graph(llm)
    run_id = uuid.uuid4().hex[:12]
    initial_state = {
        "repository_path": str(resolved),
        "operation_mode": req.operation_mode,
        "target_provider": req.target_provider,
        "target_provider_doc_url": req.target_provider_doc_url,
        "run_id": run_id,
    }

    async def events() -> AsyncIterator[str]:
        accumulated = dict(initial_state)
        yield f"data: {json.dumps({'type': 'start', 'run_id': run_id})}\n\n"
        for event in graph.stream(initial_state, config={"recursion_limit": 50}):
            for node_name, update in event.items():
                accumulated.update(update)
                payload = {
                    "type": "node",
                    "node": node_name,
                    "blocked": bool(update.get("blocked")),
                    "blocker_reason": update.get("blocker_reason"),
                }
                yield f"data: {json.dumps(payload)}\n\n"

        save_run_report(
            run_id=run_id,
            operation_mode=req.operation_mode,
            target_provider=req.target_provider,
            existing_providers=accumulated.get("existing_providers", []),
            final_status=accumulated.get("final_status") or accumulated.get("blocker_reason"),
            report=accumulated.get("report"),
        )
        yield f"data: {json.dumps({'type': 'done', 'run_id': run_id, 'report': accumulated.get('report'), 'blocked': accumulated.get('blocked', False), 'blocker_reason': accumulated.get('blocker_reason')})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/runs")
def runs(limit: int = 20):
    return list_runs(limit=limit)


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    report = get_run_report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Run not found or has no stored report")
    return report


# Static dashboard -- mounted last so it doesn't shadow the /api/* routes above.
app.mount("/", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")

"""Run-history persistence, including in-progress status for polling.

Separate from everything the agent graph does: this is telemetry (what ran,
when, with what result), not a correctness guardrail, so unlike the rest of
the pipeline it fails OPEN -- a persistence hiccup is logged and swallowed
rather than blocking or failing a real run.

Two backends behind one interface, selected by the DATABASE_URL env var:
- Set (e.g. a Supabase/Neon Postgres connection string): real managed cloud
  Postgres, so run history survives redeploys and is shared across whoever
  hits the deployed app.
- Unset: a local SQLite file (ai-engine/storage/local_runs.db, gitignored)
  so the app has a working "data" layer with zero setup for local demos.

A run is now written incrementally -- start_run() when it begins,
update_run_progress() after every node, save_run_report() at the end --
instead of only once at completion. Found necessary running this for real on
a memory-constrained free-tier deploy: a container crash mid-run used to lose
the run entirely (nothing in history, client hung on a dead stream forever).
Now the row always reflects the last progress actually persisted, so a crash
shows as a stuck "RUNNING" row instead of nothing, and the client (polling,
not a long-lived stream) just sees a few failed poll attempts and recovers
once a new instance is up, rather than hanging indefinitely.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("payshift.storage")

LOCAL_DB_PATH = Path(__file__).resolve().parent / "local_runs.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    operation_mode TEXT,
    target_provider TEXT,
    existing_providers TEXT,
    final_status TEXT,
    created_at TEXT,
    report_json TEXT,
    progress_json TEXT
)
"""


def backend_label() -> str:
    return "Postgres (cloud)" if os.environ.get("DATABASE_URL") else "SQLite (local)"


def _connect():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        import psycopg2  # imported lazily so sqlite-only usage never needs it installed
        conn = psycopg2.connect(database_url)
        placeholder = "%s"
    else:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        placeholder = "?"
    cur = conn.cursor()
    cur.execute(_SCHEMA)
    # Migration for a table created before progress_json existed. Both SQLite
    # and Postgres support ALTER TABLE ... ADD COLUMN; neither's version here
    # is guaranteed to support "IF NOT EXISTS" on it, so just swallow the
    # "already exists" error rather than checking first (TOCTOU-safe, and
    # this runs rarely -- once per connection, cached nowhere).
    try:
        cur.execute("ALTER TABLE runs ADD COLUMN progress_json TEXT")
    except Exception:
        pass
    conn.commit()
    return conn, placeholder


def _upsert(
    *, run_id: str, operation_mode: str, target_provider: str,
    existing_providers: list[str], final_status: str | None,
    report: dict | None, progress: list[dict] | None,
) -> None:
    conn, ph = _connect()
    try:
        cur = conn.cursor()
        values = (
            run_id, operation_mode, target_provider, json.dumps(existing_providers or []),
            final_status, datetime.now(timezone.utc).isoformat(),
            json.dumps(report) if report is not None else None,
            json.dumps(progress if progress is not None else []),
        )
        if ph == "%s":
            cur.execute(
                f"INSERT INTO runs (run_id, operation_mode, target_provider, existing_providers, "
                f"final_status, created_at, report_json, progress_json) "
                f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}) "
                f"ON CONFLICT (run_id) DO UPDATE SET "
                f"final_status = EXCLUDED.final_status, report_json = EXCLUDED.report_json, "
                f"progress_json = EXCLUDED.progress_json, existing_providers = EXCLUDED.existing_providers",
                values,
            )
        else:
            cur.execute(
                f"INSERT INTO runs (run_id, operation_mode, target_provider, existing_providers, "
                f"final_status, created_at, report_json, progress_json) "
                f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}) "
                f"ON CONFLICT(run_id) DO UPDATE SET "
                f"final_status = excluded.final_status, report_json = excluded.report_json, "
                f"progress_json = excluded.progress_json, existing_providers = excluded.existing_providers",
                values,
            )
        conn.commit()
    finally:
        conn.close()


def start_run(*, run_id: str, operation_mode: str, target_provider: str) -> None:
    """Called the moment a run begins, before any node has executed, so it
    shows up in history immediately as RUNNING rather than only on completion."""
    try:
        _upsert(
            run_id=run_id, operation_mode=operation_mode, target_provider=target_provider,
            existing_providers=[], final_status="RUNNING", report=None, progress=[],
        )
    except Exception:
        logger.warning("Could not record run start for %s on %s -- continuing without it",
                        run_id, backend_label(), exc_info=True)


def update_run_progress(
    *, run_id: str, operation_mode: str, target_provider: str, progress: list[dict],
) -> None:
    """Called after every node completes. Keeps final_status as RUNNING;
    save_run_report() is what sets the real terminal status."""
    try:
        _upsert(
            run_id=run_id, operation_mode=operation_mode, target_provider=target_provider,
            existing_providers=[], final_status="RUNNING", report=None, progress=progress,
        )
    except Exception:
        logger.warning("Could not persist progress for run %s on %s -- continuing without it",
                        run_id, backend_label(), exc_info=True)


def save_run_report(
    *, run_id: str, operation_mode: str, target_provider: str,
    existing_providers: list[str], final_status: str | None, report: dict | None,
    progress: list[dict] | None = None,
) -> None:
    """Best-effort: a DB problem is logged, never raised, so it can't turn a
    real pipeline run into a failure just because telemetry couldn't write."""
    try:
        _upsert(
            run_id=run_id, operation_mode=operation_mode, target_provider=target_provider,
            existing_providers=existing_providers, final_status=final_status, report=report,
            progress=progress,
        )
    except Exception:
        logger.warning("Could not persist run %s to %s -- continuing without it", run_id, backend_label(), exc_info=True)


def list_runs(limit: int = 20) -> list[dict]:
    try:
        conn, ph = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT run_id, operation_mode, target_provider, existing_providers, final_status, created_at "
                f"FROM runs ORDER BY created_at DESC LIMIT {ph}",
                (limit,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception:
        logger.warning("Could not list runs from %s", backend_label(), exc_info=True)
        return []

    return [
        {
            "run_id": r[0], "operation_mode": r[1], "target_provider": r[2],
            "existing_providers": json.loads(r[3]) if r[3] else [],
            "final_status": r[4], "created_at": r[5],
        }
        for r in rows
    ]


def get_run_report(run_id: str) -> dict | None:
    try:
        conn, ph = _connect()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT report_json FROM runs WHERE run_id = {ph}", (run_id,))
            row = cur.fetchone()
        finally:
            conn.close()
    except Exception:
        logger.warning("Could not fetch run %s from %s", run_id, backend_label(), exc_info=True)
        return None

    if not row or not row[0]:
        return None
    return json.loads(row[0])


def get_run_status(run_id: str) -> dict | None:
    """What the frontend polls: current status, nodes completed so far, and
    the final report once there is one. Returns None if the run_id is unknown
    (never started, or persistence failed at start_run time)."""
    try:
        conn, ph = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT final_status, progress_json, report_json FROM runs WHERE run_id = {ph}",
                (run_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
    except Exception:
        logger.warning("Could not fetch status for run %s from %s", run_id, backend_label(), exc_info=True)
        return None

    if not row:
        return None
    final_status, progress_json, report_json = row
    return {
        "status": final_status,
        "progress": json.loads(progress_json) if progress_json else [],
        "report": json.loads(report_json) if report_json else None,
    }

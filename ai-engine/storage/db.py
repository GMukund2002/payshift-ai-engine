"""Run-history persistence.

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

Both paths hit the exact same schema and the exact same call sites in
main.py / frontend/app.py -- swapping backends is a config change, not a
code change, the same pattern already used for the LLM client.
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
    report_json TEXT
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
    conn.cursor().execute(_SCHEMA)
    conn.commit()
    return conn, placeholder


def save_run_report(
    *, run_id: str, operation_mode: str, target_provider: str,
    existing_providers: list[str], final_status: str | None, report: dict | None,
) -> None:
    """Best-effort: a DB problem is logged, never raised, so it can't turn a
    real pipeline run into a failure just because telemetry couldn't write."""
    try:
        conn, ph = _connect()
        try:
            cur = conn.cursor()
            on_conflict = "ON CONFLICT (run_id) DO NOTHING" if ph == "%s" else ""
            insert_or = "INSERT" if ph == "%s" else "INSERT OR IGNORE"
            cur.execute(
                f"{insert_or} INTO runs (run_id, operation_mode, target_provider, existing_providers, "
                f"final_status, created_at, report_json) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}) "
                f"{on_conflict}",
                (
                    run_id, operation_mode, target_provider, json.dumps(existing_providers or []),
                    final_status, datetime.now(timezone.utc).isoformat(), json.dumps(report) if report else None,
                ),
            )
            conn.commit()
        finally:
            conn.close()
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

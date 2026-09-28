"""Cost Ledger — AD-20 single-writer ledger for token telemetry.

Public surface (Story 4.1):
- `CostRecord` frozen dataclass carrying {op_id, project_id, run_id?, step?,
  tokens_in, tokens_out, duration_ms?, recorded_at, signed_hash}.
- `append(...) -> CostRecord` — atomic INSERT-or-FAILURE.
- `read(op_id) -> CostRecord | None`.
- `sum_for_project(project_id) -> int` — total tokens_in + tokens_out.
- `sum_for_run(project_id, run_id) -> int`.
- `CostLedgerImmutable` exception.

AD-20 binding:
- Append-only; edit/delete returns `cost_ledger_immutable`.
- Single ledger keyed by ULID; the dashboard reads this ledger (NOT
  Herdr events).
- `signed_hash` covers `canonical_bytes(record_with_id)` per AD-17.
"""

from __future__ import annotations

import sqlite3
import ulid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness.canonical import canonical_sha256


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "var" / "harness.sqlite"


# --- Exceptions -----------------------------------------------------------


class CostLedgerError(Exception):
    """Base for all cost_ledger errors."""


class CostLedgerImmutable(CostLedgerError):
    """Edit/delete attempt on a persisted cost row."""


# --- Dataclass ------------------------------------------------------------


@dataclass(frozen=True)
class CostRecord:
    op_id: str  # ULID; assigned by append if absent
    project_id: str
    run_id: str | None
    step: str | None
    tokens_in: int
    tokens_out: int
    duration_ms: int | None
    recorded_at: str  # ISO 8601 UTC
    signed_hash: str = ""  # sha256: of canonical_bytes(record_with_id)


# --- Helpers --------------------------------------------------------------


def _open_db(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_table(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS cost_ledger (
            op_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            run_id TEXT,
            step TEXT,
            tokens_in INTEGER NOT NULL DEFAULT 0,
            tokens_out INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER,
            recorded_at TEXT NOT NULL,
            signed_hash TEXT NOT NULL
        )
        """.strip()
    )
    db.commit()


# --- Public API ------------------------------------------------------------


def append(
    project_id: str,
    *,
    run_id: str | None = None,
    step: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    duration_ms: int | None = None,
    db: Path | None = None,
) -> CostRecord:
    """Append a cost record. AD-20: append-only."""
    db_path = db or DEFAULT_DB
    op_id = str(ulid.ULID.from_datetime(datetime.now(timezone.utc)))
    recorded_at = datetime.now(timezone.utc).isoformat()
    record_dict = {
        "op_id": op_id,
        "project_id": project_id,
        "run_id": run_id,
        "step": step,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "duration_ms": duration_ms,
        "recorded_at": recorded_at,
    }
    signed_hash = (
        "sha256:" + canonical_sha256(record_dict).split(":", 1)[1]
    )
    record_dict["signed_hash"] = signed_hash

    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        # AD-20: refuse overwrite (append-only).
        cur = conn.execute(
            "SELECT 1 FROM cost_ledger WHERE op_id = ?", (op_id,)
        ).fetchone()
        if cur is not None:
            raise CostLedgerImmutable(f"op_id collision: {op_id}")
        conn.execute(
            """
            INSERT INTO cost_ledger (
                op_id, project_id, run_id, step,
                tokens_in, tokens_out, duration_ms, recorded_at, signed_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """.strip(),
            (
                op_id, project_id, run_id, step,
                tokens_in, tokens_out, duration_ms, recorded_at, signed_hash,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return CostRecord(
        op_id=op_id, project_id=project_id, run_id=run_id, step=step,
        tokens_in=tokens_in, tokens_out=tokens_out, duration_ms=duration_ms,
        recorded_at=recorded_at, signed_hash=signed_hash,
    )


def read(op_id: str, *, db: Path | None = None) -> CostRecord | None:
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT op_id, project_id, run_id, step, tokens_in, tokens_out, "
            "duration_ms, recorded_at, signed_hash FROM cost_ledger WHERE op_id = ?",
            (op_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return CostRecord(
        op_id=row[0], project_id=row[1], run_id=row[2], step=row[3],
        tokens_in=row[4], tokens_out=row[5], duration_ms=row[6],
        recorded_at=row[7], signed_hash=row[8],
    )


def sum_for_project(project_id: str, *, db: Path | None = None) -> int:
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) "
            "FROM cost_ledger WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


def sum_for_run(project_id: str, run_id: str, *, db: Path | None = None) -> int:
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) "
            "FROM cost_ledger WHERE project_id = ? AND run_id = ?",
            (project_id, run_id),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


__all__ = [
    "CostRecord",
    "CostLedgerError",
    "CostLedgerImmutable",
    "DEFAULT_DB",
    "append",
    "read",
    "sum_for_project",
    "sum_for_run",
]
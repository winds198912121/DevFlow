"""Run Event Log — AD-14 single-writer surface for run state transitions.

Public surface (Story 2.10):
- `RunEvent` frozen dataclass carrying the AD-14 schema:
  `{event_id, project_id, run_id, step, executor_tuple, executor_tuple_hash,
   started_at, ended_at, outcome, gate_mode, cost_tokens_in, cost_tokens_out,
   confirm_id?, error_record_id?, acknowledgement_id?}`.
- `write(event) -> RunEvent` — atomic INSERT-or-FAILURE.
- `list_for_run(run_id) -> tuple[RunEvent, ...]` — chronological list.
- `RunEventError`, `RunEventAlreadyExists` exceptions.
- `DEFAULT_DB` constant path = `var/devflow.sqlite`.

AD-14 binding:
- Every harness state transition writes ONE row.
- Run state is reconstructable from the log alone.
- The dashboard (Epic 4) reads `cost_tokens_in`/`cost_tokens_out` from
  these rows (not from any separate cost table — AD-20).
"""

from __future__ import annotations

import sqlite3

from harness import migrate as _migrate
import ulid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "var" / "devflow.sqlite"


# --- Exceptions -----------------------------------------------------------


class RunEventError(Exception):
    """Base for all run_event_log errors."""


class RunEventAlreadyExists(RunEventError):
    """Two `write` calls produced the same `event_id` (ULID collision)."""


# --- Dataclass ------------------------------------------------------------


Outcome = Literal["pass", "fail", "error", "skipped"]
GateMode = Literal["enforced", "skipped"]


@dataclass(frozen=True)
class RunEvent:
    """A run state transition (AD-14 schema).

    All optional fields default to None; the caller populates only what
    applies to the specific transition (e.g. a step-start event has no
    `ended_at` / `outcome`).
    """

    event_id: str  # ULID
    project_id: str
    run_id: str
    step: str | None  # None for run-level events (e.g. run_start, run_end)
    executor_tuple: str  # JSON-serialized (AD-10 contract)
    executor_tuple_hash: str  # sha256 of canonical_bytes(executor_tuple)
    started_at: str  # ISO 8601 UTC
    ended_at: str | None = None
    outcome: Outcome | None = None
    gate_mode: GateMode | None = None
    cost_tokens_in: int = 0
    cost_tokens_out: int = 0
    confirm_id: str | None = None
    error_record_id: str | None = None
    acknowledgement_id: str | None = None


# --- Helpers --------------------------------------------------------------


def _open_db(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_table(db: sqlite3.Connection) -> None:
    """Create `run_events` for callers that have not run migrations.

    Production callers use `migrate.run_migrations`; this covers tests and
    first-run paths that open a store before the harness boots. The DDL comes
    from `_MIGRATIONS` — including `idx_run_events_run_id`, which the previous
    hand-copied version omitted.
    """
    _migrate.ensure_tables(db, "run_events")


def write(event: RunEvent, *, db: Path | None = None) -> RunEvent:
    """Persist a `RunEvent`. Atomic INSERT-or-FAILURE (ULID collision)."""
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO run_events (
                event_id, project_id, run_id, step,
                executor_tuple, executor_tuple_hash,
                started_at, ended_at, outcome, gate_mode,
                cost_tokens_in, cost_tokens_out,
                confirm_id, error_record_id, acknowledgement_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """.strip(),
            (
                event.event_id, event.project_id, event.run_id, event.step,
                event.executor_tuple, event.executor_tuple_hash,
                event.started_at, event.ended_at, event.outcome,
                event.gate_mode, event.cost_tokens_in, event.cost_tokens_out,
                event.confirm_id, event.error_record_id,
                event.acknowledgement_id,
            ),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise RunEventAlreadyExists(f"event_id collision: {event.event_id}")
    finally:
        conn.close()
    return event


def list_for_run(run_id: str, *, db: Path | None = None) -> tuple[RunEvent, ...]:
    """Return all events for `run_id` sorted chronologically.

    Chronological = `started_at` ASC (with `event_id` ASC as the tiebreaker
    when two events share a timestamp). The returned tuple carries full
    event records (not just IDs) so callers can read the body without
    a separate round-trip.
    """
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        rows = conn.execute(
            """
            SELECT event_id FROM run_events
            WHERE run_id = ?
            ORDER BY started_at ASC, event_id ASC
            """.strip(),
            (run_id,),
        ).fetchall()
        ids = tuple(r[0] for r in rows)
    finally:
        conn.close()
    return tuple(e for e in (read(i, db=db) for i in ids) if e is not None)


def read(event_id: str, *, db: Path | None = None) -> RunEvent | None:
    """Read a single `RunEvent` by its ULID. Returns None if not found."""
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            """
            SELECT event_id, project_id, run_id, step,
                   executor_tuple, executor_tuple_hash,
                   started_at, ended_at, outcome, gate_mode,
                   cost_tokens_in, cost_tokens_out,
                   confirm_id, error_record_id, acknowledgement_id
            FROM run_events WHERE event_id = ?
            """.strip(),
            (event_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return RunEvent(
        event_id=row[0], project_id=row[1], run_id=row[2], step=row[3],
        executor_tuple=row[4], executor_tuple_hash=row[5],
        started_at=row[6], ended_at=row[7], outcome=row[8],
        gate_mode=row[9], cost_tokens_in=row[10],
        cost_tokens_out=row[11], confirm_id=row[12],
        error_record_id=row[13], acknowledgement_id=row[14],
    )


def generate_event_id() -> str:
    """Generate a fresh ULID for a new run event."""
    return str(ulid.ULID.from_datetime(datetime.now(timezone.utc)))


__all__ = [
    "RunEvent",
    "RunEventError",
    "RunEventAlreadyExists",
    "Outcome",
    "GateMode",
    "DEFAULT_DB",
    "write",
    "read",
    "list_for_run",
    "generate_event_id",
]

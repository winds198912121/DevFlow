"""Error Store — append-only ledger of step failures.

Public surface (Story 3.1):
- `ErrorCategory` Literal — the closed enum from spec-devflow/failure-modes.md.
- `ErrorRecord` frozen dataclass carrying the FR-13 / PRD addendum §5 schema.
- `append(record) -> ErrorRecord` — atomic INSERT-or-FAILURE; refuses to
  overwrite an existing record_id.
- `read(record_id) -> ErrorRecord | None` — reads a single record.
- `list_for(project_id, run_id, step=None) -> tuple[ErrorRecord, ...]`.
- `ErrorStoreError`, `ErrorStoreImmutable`, `InvalidErrorCategory`
  exceptions.

AD-4 binding:
- Records are immutable post-write; edit/delete attempts return
  `error_store_immutable`.
- Single append-only ledger keyed by ULID.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import ulid

from harness.canonical import canonical_sha256


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "var" / "harness.sqlite"


# Closed enum per spec-devflow/failure-modes.md.
ErrorCategory = Literal[
    "requirement",
    "research",
    "design",
    "coding",
    "testing",
    "review",
    "agent",
    "llm",
    "skill",
    "tool",
    "environment",
    "integration",
]
_VALID_CATEGORIES = frozenset({
    "requirement", "research", "design", "coding", "testing", "review",
    "agent", "llm", "skill", "tool", "environment", "integration",
})


# --- Exceptions -----------------------------------------------------------


class ErrorStoreError(Exception):
    """Base for all error_store errors."""


class ErrorStoreImmutable(ErrorStoreError):
    """Edit/delete attempt on a persisted error record (AD-4)."""


class InvalidErrorCategory(ErrorStoreError):
    """Category is not in the closed enum."""


# --- Dataclass ------------------------------------------------------------


@dataclass(frozen=True)
class ErrorRecord:
    """A single step failure (FR-13 / PRD addendum §5 schema)."""

    record_id: str  # ULID; assigned by append() if absent
    project_id: str
    run_id: str
    step: str
    attempt: int
    category: ErrorCategory
    root_cause: tuple[str, ...]
    correction: tuple[str, ...]
    retry: tuple[dict, ...]
    result: str  # "fail" / "error" / etc.
    recorded_at: str  # ISO 8601 UTC
    hash: str = ""  # sha256: of canonical_bytes(record_with_id) — filled by append

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "step": self.step,
            "attempt": self.attempt,
            "category": self.category,
            "root_cause": list(self.root_cause),
            "correction": list(self.correction),
            "retry": list(self.retry),
            "result": self.result,
            "recorded_at": self.recorded_at,
            "hash": self.hash,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "ErrorRecord":
        return cls(
            record_id=row[0],
            project_id=row[1],
            run_id=row[2],
            step=row[3],
            attempt=row[4],
            category=row[5],
            root_cause=tuple(json.loads(row[6])),
            correction=tuple(json.loads(row[7])),
            retry=tuple(json.loads(row[8])),
            result=row[9],
            recorded_at=row[10],
            hash=row[11],
        )


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
        CREATE TABLE IF NOT EXISTS error_records (
            record_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            step TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            category TEXT NOT NULL,
            root_cause_json TEXT NOT NULL,
            correction_json TEXT NOT NULL,
            retry_json TEXT NOT NULL,
            result TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            hash TEXT NOT NULL
        )
        """.strip()
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_error_records_lookup
            ON error_records (project_id, run_id, step)
        """.strip()
    )
    db.commit()


def _validate_category(category: str) -> None:
    if category not in _VALID_CATEGORIES:
        raise InvalidErrorCategory(
            f"category {category!r} not in {sorted(_VALID_CATEGORIES)}"
        )


# --- Public API ------------------------------------------------------------


def append(
    record: ErrorRecord,
    *,
    db: Path | None = None,
) -> ErrorRecord:
    """Persist an `ErrorRecord`. AD-4: append-only; refuses to overwrite."""
    _validate_category(record.category)
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        record_id = record.record_id or str(ulid.ULID.from_datetime(datetime.now(timezone.utc)))
        record_dict = {**record.to_dict(), "record_id": record_id}
        # Compute the hash (sha256: of canonical_bytes(record_with_id)).
        record_dict["hash"] = "sha256:" + canonical_sha256(record_dict).split(":", 1)[1]
        # Refuse to overwrite an existing record_id.
        cur = conn.execute(
            "SELECT 1 FROM error_records WHERE record_id = ?", (record_id,)
        ).fetchone()
        if cur is not None:
            raise ErrorStoreImmutable(f"record_id collision: {record_id}")
        conn.execute(
            """
            INSERT INTO error_records (
                record_id, project_id, run_id, step, attempt, category,
                root_cause_json, correction_json, retry_json, result,
                recorded_at, hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """.strip(),
            (
                record_dict["record_id"], record_dict["project_id"],
                record_dict["run_id"], record_dict["step"], record_dict["attempt"],
                record_dict["category"], json.dumps(record_dict["root_cause"]),
                json.dumps(record_dict["correction"]),
                json.dumps(record_dict["retry"]), record_dict["result"],
                record_dict["recorded_at"], record_dict["hash"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return ErrorRecord.from_row((
        record_dict["record_id"], record_dict["project_id"],
        record_dict["run_id"], record_dict["step"], record_dict["attempt"],
        record_dict["category"], json.dumps(record_dict["root_cause"]),
        json.dumps(record_dict["correction"]),
        json.dumps(record_dict["retry"]), record_dict["result"],
        record_dict["recorded_at"], record_dict["hash"],
    ))


def read(record_id: str, *, db: Path | None = None) -> ErrorRecord | None:
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT record_id, project_id, run_id, step, attempt, category, "
            "root_cause_json, correction_json, retry_json, result, "
            "recorded_at, hash FROM error_records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
    finally:
        conn.close()
    return ErrorRecord.from_row(row) if row else None


def list_for(
    project_id: str,
    run_id: str,
    step: str | None = None,
    *,
    db: Path | None = None,
) -> tuple[ErrorRecord, ...]:
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        if step is None:
            rows = conn.execute(
                "SELECT record_id, project_id, run_id, step, attempt, category, "
                "root_cause_json, correction_json, retry_json, result, "
                "recorded_at, hash FROM error_records "
                "WHERE project_id = ? AND run_id = ? "
                "ORDER BY record_id ASC",
                (project_id, run_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT record_id, project_id, run_id, step, attempt, category, "
                "root_cause_json, correction_json, retry_json, result, "
                "recorded_at, hash FROM error_records "
                "WHERE project_id = ? AND run_id = ? AND step = ? "
                "ORDER BY record_id ASC",
                (project_id, run_id, step),
            ).fetchall()
    finally:
        conn.close()
    return tuple(ErrorRecord.from_row(r) for r in rows)


def query(
    project_id: str,
    *,
    run_id: str | None = None,
    step: str | None = None,
    category: str | None = None,
    since: str | None = None,
    until: str | None = None,
    db: Path | None = None,
) -> tuple[ErrorRecord, ...]:
    """FR-25 filter surface: whole-project error query with AND-composed filters.

    `list_for` is run-scoped; the dashboard's error view is project-scoped
    (Story 4.5), so this adds the project-wide variant. Every filter is
    optional and all supplied filters must match (AND, never OR); an empty
    filter set returns every error for `project_id`.

    `category` outside the closed AD-4 enum raises `InvalidErrorCategory`
    rather than silently returning nothing — a typo'd filter must not read as
    "no errors" (Story 4.5 turns this into `category_not_found`).
    `since`/`until` are inclusive ISO-8601 bounds compared lexicographically
    against `recorded_at`, which is stored as a UTC ISO-8601 string and so
    sorts chronologically.

    The `executor_tuple` dimension is deliberately absent: an executor tuple
    lives inside the `retry` JSON blob, not in a column, so it is refined by
    the caller after retrieval (`harness.dashboard_service.list_errors`).
    """
    if category is not None:
        _validate_category(category)
    db_path = db or DEFAULT_DB
    clauses = ["project_id = ?"]
    params: list[str] = [project_id]
    for column, value, op in (
        ("run_id", run_id, "="),
        ("step", step, "="),
        ("category", category, "="),
        ("recorded_at", since, ">="),
        ("recorded_at", until, "<="),
    ):
        if value is not None:
            clauses.append(f"{column} {op} ?")
            params.append(value)
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT record_id, project_id, run_id, step, attempt, category, "
            "root_cause_json, correction_json, retry_json, result, "
            "recorded_at, hash FROM error_records "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY record_id ASC",
            tuple(params),
        ).fetchall()
    finally:
        conn.close()
    return tuple(ErrorRecord.from_row(r) for r in rows)


__all__ = [
    "ErrorRecord",
    "ErrorCategory",
    "ErrorStoreError",
    "ErrorStoreImmutable",
    "InvalidErrorCategory",
    "DEFAULT_DB",
    "append",
    "read",
    "list_for",
    "query",
]


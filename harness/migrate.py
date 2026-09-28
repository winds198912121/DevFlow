"""Migration framework — the sole writer to the `_migrations` table.

`run_migrations(db)` reads the current `schema_version` from `_migrations`,
applies any pending migrations in `_MIGRATIONS` order, and stamps each
applied migration's row. Future stories append their migrations to
`_MIGRATIONS` (which is validated at module-import time for unique
versions and monotonic sequence).

This module is the sole writer to `_migrations` (mirrors the AD-22
"Skill Bump Registry has exactly two writers" pattern, with the migration
runner being a third single-writer for a different table). The canonical
sha256 path (`harness.canonical.canonical_sha256`) computes each
migration's `sql_hash` so the runner can detect drift on every re-run.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from harness.canonical import canonical_sha256


# --- Exceptions -----------------------------------------------------------


class MigrationError(Exception):
    """Base for all migration-runner errors."""


class FutureSchemaVersion(MigrationError):
    """DB's schema_version is greater than this harness's max known version.

    Operator must upgrade the harness or restore a backup.
    """

    def __init__(self, db_version: int, max_known: int) -> None:
        super().__init__(
            f"future_schema_version: db has schema_version={db_version}, "
            f"harness knows up to {max_known}"
        )
        self.db_version = db_version
        self.max_known = max_known


class MigrationCorrupted(MigrationError):
    """A previously-applied migration's SQL no longer matches its recorded hash.

    The DB row's sql_hash differs from `canonical_sha256(migration_sql)`.
    Operator must restore from backup or hand-edit.
    """

    def __init__(self, version: int, recorded_hash: str, computed_hash: str) -> None:
        super().__init__(
            f"migration_corrupted: version {version} recorded hash {recorded_hash} "
            f"!= computed hash {computed_hash}"
        )
        self.version = version
        self.recorded_hash = recorded_hash
        self.computed_hash = computed_hash


class DuplicateMigrationVersion(MigrationError):
    """Two migrations in `_MIGRATIONS` share a version. Raised at import time."""

    def __init__(self, version: int) -> None:
        super().__init__(f"duplicate_migration_version: version {version} appears more than once")
        self.version = version


class MigrationGap(MigrationError):
    """Versions in `_MIGRATIONS` are not contiguous (e.g. 1, 2, 4). Raised at import time."""

    def __init__(self, gap_version: int) -> None:
        super().__init__(f"migration_gap: no migration for version {gap_version}")
        self.gap_version = gap_version


# --- Migration list (sole source of truth) -------------------------------
#
# Each tuple: (version, description, sql). Version is positive int, monotonic.
# Future stories append their migrations here.
#
# Initial migration creates the `_migrations` ledger table itself.

_MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "init",
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            sql_hash TEXT NOT NULL
        )
        """.strip(),
    ),
    (
        2,
        "add artifacts table",
        """
        CREATE TABLE artifacts (
            id TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            payload BLOB NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            locked_at TEXT,
            signature TEXT
        )
        """.strip(),
    ),
    (
        3,
        "add project_edit_locks table (AD-18)",
        """
        CREATE TABLE project_edit_locks (
            project_id TEXT PRIMARY KEY,
            acquired_at TEXT NOT NULL,
            acquired_by TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """.strip(),
    ),
    (
        4,
        "add project_yaml_edits table (Story 2.9, Run Event Log stub)",
        """
        CREATE TABLE project_yaml_edits (
            project_id TEXT NOT NULL,
            edit_id TEXT PRIMARY KEY,
            prev_yaml_hash TEXT,
            new_yaml_hash TEXT,
            edited_by TEXT NOT NULL,
            edited_at TEXT NOT NULL,
            intent TEXT NOT NULL,
            prev_executor_tuple TEXT,
            new_executor_tuple TEXT
        )
        """.strip(),
    ),
    (
        5,
        "add run_events table (Story 2.10)",
        """
        CREATE TABLE run_events (
            event_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            step TEXT,
            executor_tuple TEXT NOT NULL,
            executor_tuple_hash TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            outcome TEXT,
            gate_mode TEXT,
            cost_tokens_in INTEGER NOT NULL DEFAULT 0,
            cost_tokens_out INTEGER NOT NULL DEFAULT 0,
            confirm_id TEXT,
            error_record_id TEXT,
            acknowledgement_id TEXT
        )
        """.strip(),
    ),
    (
        6,
        "add delivery_receipts index (Story 2.10)",
        """
        CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events (run_id)
        """.strip(),
    ),
    (
        7,
        "add error_records table (Story 3.1)",
        """
        CREATE TABLE error_records (
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
        """.strip(),
    ),
    (
        8,
        "add error_records indexes (Story 3.1)",
        """
        CREATE INDEX IF NOT EXISTS idx_error_records_lookup
            ON error_records (project_id, run_id, step)
        """.strip(),
    ),
    (
        9,
        "add regression set + benchmark tables (Story 3.4)",
        """
        CREATE TABLE regression_set_runs (
            run_event_id TEXT PRIMARY KEY,
            step TEXT NOT NULL,
            project_size_tier TEXT NOT NULL,
            artifact_contract_version TEXT NOT NULL,
            metric_value REAL NOT NULL,
            metric_definition TEXT NOT NULL,
            added_at TEXT NOT NULL,
            removed_at TEXT,
            added_by TEXT NOT NULL
        )
        """.strip(),
    ),
    (
        10,
        "add benchmark_runs table (Story 3.4)",
        """
        CREATE TABLE benchmark_runs (
            benchmark_id TEXT PRIMARY KEY,
            step TEXT NOT NULL,
            project_size_tier TEXT NOT NULL,
            artifact_contract_version TEXT,
            metric_definition TEXT NOT NULL,
            computed_at TEXT NOT NULL,
            result_json TEXT NOT NULL
        )
        """.strip(),
    ),
    (
        11,
        "add regression_set_removals table (Story 3.7)",
        """
        CREATE TABLE regression_set_removals (
            removed_run_id TEXT PRIMARY KEY,
            removed_at TEXT NOT NULL,
            removed_by TEXT NOT NULL,
            reason TEXT NOT NULL
        )
        """.strip(),
    ),
    (
        12,
        "add skill_bumps table (Story 3.5)",
        """
        CREATE TABLE skill_bumps (
            bump_id TEXT PRIMARY KEY,
            skill_name TEXT NOT NULL,
            new_version TEXT NOT NULL,
            previous_version TEXT NOT NULL,
            state TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            promoted_at TEXT,
            promoted_by TEXT,
            regression_run_id TEXT
        )
        """.strip(),
    ),
]


def _compute_sql_hash(sql: str) -> str:
    """Hash the migration SQL via the canonical sha256 path (AD-17)."""
    return canonical_sha256(sql)


def _validate_migrations() -> None:
    """Check the migration list for duplicates and gaps. Raises at module import."""
    seen: set[int] = set()
    for version, _desc, _sql in _MIGRATIONS:
        if version in seen:
            raise DuplicateMigrationVersion(version)
        seen.add(version)
    # Check gaps (contiguous 1..N).
    expected = 1
    for version, _desc, _sql in _MIGRATIONS:
        if version != expected:
            raise MigrationGap(expected)
        expected += 1


_validate_migrations()


# --- The runner ----------------------------------------------------------


def _ensure_migrations_table(db: sqlite3.Connection) -> None:
    """Create `_migrations` if it doesn't exist; idempotent."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            sql_hash TEXT NOT NULL
        )
        """.strip()
    )


def _current_version(db: sqlite3.Connection) -> int:
    """Return the highest `version` row in `_migrations`, or 0 if empty."""
    _ensure_migrations_table(db)
    row = db.execute("SELECT COALESCE(MAX(version), 0) FROM _migrations").fetchone()
    return int(row[0]) if row else 0


def _applied_versions(db: sqlite3.Connection) -> dict[int, str]:
    """Return {version: sql_hash} for every row in `_migrations`."""
    rows = db.execute("SELECT version, sql_hash FROM _migrations").fetchall()
    return {int(v): str(h) for v, h in rows}


def run_migrations(db: sqlite3.Connection) -> None:
    """Apply any pending migrations to `db`. Idempotent: re-runs are no-ops.

    Raises:
        FutureSchemaVersion: DB's `schema_version` > max version in `_MIGRATIONS`.
        MigrationCorrupted: An applied migration's stored `sql_hash` does not match
            the canonical sha256 of the migration's SQL.
    """
    current = _current_version(db)
    max_known = _MIGRATIONS[-1][0] if _MIGRATIONS else 0

    # Verify all already-applied migrations match their recorded hash BEFORE
    # the future-schema check. If a DB at schema_version=3 has a corrupted
    # v1 row, the operator needs the corruption report (more actionable)
    # before the future-schema report ("upgrade the harness").
    applied = _applied_versions(db)
    for version, _desc, sql in _MIGRATIONS:
        if version > current:
            continue  # not yet applied
        sql_hash = _compute_sql_hash(sql)
        recorded = applied.get(version)
        if recorded is None:
            continue
        if recorded != sql_hash:
            raise MigrationCorrupted(version, recorded, sql_hash)

    if current > max_known:
        raise FutureSchemaVersion(current, max_known)

    # Apply any pending migrations.
    now = datetime.now(timezone.utc).isoformat()
    for version, description, sql in _MIGRATIONS:
        if version <= current:
            continue
        sql_hash = _compute_sql_hash(sql)
        db.execute(sql)
        db.execute(
            "INSERT INTO _migrations (version, description, applied_at, sql_hash) VALUES (?, ?, ?, ?)",
            (version, description, now, sql_hash),
        )
        db.commit()
        current = version


# --- Default DB connection helper -----------------------------------------


def open_default_db(path: str | Path = "var/harness.sqlite") -> sqlite3.Connection:
    """Open (or create) the harness's default SQLite DB with the standard pragmas.

    Sets WAL mode, foreign keys, and a busy timeout. Caller is responsible
    for closing the connection (or use it as a context manager).
    """
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_path))
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    # PRAGMA journal_mode takes effect on the next transaction; commit an
    # empty transaction so the WAL sidecar (-wal) file is created on disk
    # rather than waiting for the first real write.
    db.commit()
    return db

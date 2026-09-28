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

    if current > max_known:
        raise FutureSchemaVersion(current, max_known)

    # Verify all already-applied migrations match their recorded hash.
    applied = _applied_versions(db)
    for version, _desc, sql in _MIGRATIONS:
        if version > current:
            continue  # not yet applied
        sql_hash = _compute_sql_hash(sql)
        recorded = applied.get(version)
        if recorded is None:
            # Version > current but no row? Can't happen if current = MAX(version).
            continue
        if recorded != sql_hash:
            raise MigrationCorrupted(version, recorded, sql_hash)

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

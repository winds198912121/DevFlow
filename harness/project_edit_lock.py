"""Project Edit Lock — AD-18 single-writer lock for project YAML edits.

Public surface (Story 2.9):
- `ProjectEditLock` frozen dataclass: `(project_id, acquired_at, acquired_by,
  expires_at)`.
- `acquire(project_id, acquired_by, *, ttl_seconds=300, db=DEFAULT_DB) ->
  ProjectEditLock` — atomic INSERT-or-FAILURE. If a live lock exists,
  raises `LockHeld`; if an expired lock exists, steals it.
- `release(project_id, *, acquired_by=None, db=DEFAULT_DB) -> bool` —
  removes the lock; returns True if a row was removed.
- `LockHeld`, `LockExpired` exceptions.
- `DEFAULT_DB` constant path = `var/devflow.sqlite` (the spine's
  cross-cutting tables live here per AD-18 (a) + AD-20).

The lock is keyed on `project_id` (a project has at most one active lock).
AD-18 (b): lock release is explicit OR expires after 5 minutes (the
default `ttl_seconds`; dashboards may pass longer TTLs).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "var" / "devflow.sqlite"

DEFAULT_TTL_SECONDS = 300


# --- Exceptions ------------------------------------------------------------


class ProjectEditLockError(Exception):
    """Base for all project_edit_lock errors."""


class LockHeld(ProjectEditLockError):
    """A live (non-expired) lock already exists for the project.

    Per AD-18 (e): the loser is told who holds the lock.
    """

    def __init__(self, project_id: str, holder: str, expires_at: str) -> None:
        super().__init__(
            f"project_locked: project_id={project_id!r} held by {holder!r} "
            f"until {expires_at!r}"
        )
        self.project_id = project_id
        self.holder = holder
        self.expires_at = expires_at


class LockExpired(ProjectEditLockError):
    """The lock TTL has elapsed. Caller should re-acquire."""


class ProjectLocked(LockHeld):
    """A live `project_edit_lock` is held by another caller.

    AD-18 (e): the loser is told who holds the lock. Subclass of
    `LockHeld` so callers that catch the broader lock exception also
    catch this one. The story 2.9 plan's `ProjectLocked` name is the
    canonical public surface; `LockHeld` is the underlying exception.
    """


# --- Dataclass -------------------------------------------------------------


@dataclass(frozen=True)
class ProjectEditLock:
    """The held state of a project_edit_lock row."""

    project_id: str
    acquired_at: str  # ISO 8601 UTC
    acquired_by: str
    expires_at: str  # ISO 8601 UTC


# --- Helpers ---------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_expired(expires_at: str, *, now_iso: str | None = None) -> bool:
    """True iff `expires_at` is strictly before `now_iso` (or current time)."""
    now = now_iso or _now_iso()
    return expires_at < now


def _open_db(db: Path) -> sqlite3.Connection:
    """Open the lock DB with the standard pragmas; create parent dir."""
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_table(db: sqlite3.Connection) -> None:
    """Make sure the lock table exists (the migration may not have run for
    v1 callers that open DEFAULT_DB before migrate is invoked)."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS project_edit_locks (
            project_id TEXT PRIMARY KEY,
            acquired_at TEXT NOT NULL,
            acquired_by TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """.strip()
    )
    db.commit()


# --- Acquire / Release -----------------------------------------------------


def acquire(
    project_id: str,
    acquired_by: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    db: Path | None = None,
    _depth: int = 0,
) -> ProjectEditLock:
    """Acquire a `project_edit_lock` for `project_id`.

    Atomic INSERT-or-FAILURE: if a live lock exists, raises
    `ProjectLocked` (subclass of `LockHeld`); if an expired lock
    exists, UPDATEs the row and returns the new `ProjectEditLock`.

    The race-recovery branch (row vanished between INSERT and SELECT)
    recurses once — guarded by `_depth` to prevent unbounded recursion
    if another writer is racing in a loop.
    """
    if _depth > 1:
        raise LockHeld(project_id, "race-detected", _now_iso())
    db_path = db or DEFAULT_DB
    now = _now_iso()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO project_edit_locks
                (project_id, acquired_at, acquired_by, expires_at)
            VALUES (?, ?, ?, ?)
            """.strip(),
            (project_id, now, acquired_by, expires_at),
        )
        conn.commit()
        if cur.rowcount == 1:
            return ProjectEditLock(
                project_id=project_id,
                acquired_at=now,
                acquired_by=acquired_by,
                expires_at=expires_at,
            )
        row = conn.execute(
            "SELECT acquired_by, expires_at FROM project_edit_locks WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return acquire(
                project_id,
                acquired_by,
                ttl_seconds=ttl_seconds,
                db=db,
                _depth=_depth + 1,
            )
        holder, existing_expires = row
        if not _is_expired(existing_expires, now_iso=now):
            raise ProjectLocked(project_id, holder, existing_expires)
        conn.execute(
            """
            UPDATE project_edit_locks
            SET acquired_at = ?, acquired_by = ?, expires_at = ?
            WHERE project_id = ? AND expires_at = ?
            """.strip(),
            (now, acquired_by, expires_at, project_id, existing_expires),
        )
        conn.commit()
        return ProjectEditLock(
            project_id=project_id,
            acquired_at=now,
            acquired_by=acquired_by,
            expires_at=expires_at,
        )
    finally:
        conn.close()


def release(
    project_id: str,
    *,
    acquired_by: str | None = None,
    db: Path | None = None,
) -> None:
    """Release the lock for `project_id`.

    If `acquired_by` is supplied, only the holder can release (prevents
    the second operator from releasing the first operator's lock).
    Returns None silently on no-op (the operator may call release twice
    or after expiry; the action is idempotent).
    """
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        if acquired_by is not None:
            conn.execute(
                "DELETE FROM project_edit_locks "
                "WHERE project_id = ? AND acquired_by = ?",
                (project_id, acquired_by),
            )
        else:
            conn.execute(
                "DELETE FROM project_edit_locks WHERE project_id = ?",
                (project_id,),
            )
        conn.commit()
    finally:
        conn.close()


def _with_lock(project_id: str, acquired_by: str, *, db: Path | None = None):
    """Context manager: acquire on enter, release on exit (best-effort)."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        lock = acquire(project_id, acquired_by, db=db)
        try:
            yield lock
        finally:
            release(project_id, acquired_by=acquired_by, db=db)

    return _ctx()


__all__ = [
    "ProjectEditLock",
    "ProjectEditLockError",
    "LockHeld",
    "LockExpired",
    "ProjectLocked",
    "DEFAULT_DB",
    "DEFAULT_TTL_SECONDS",
    "acquire",
    "release",
    "_with_lock",
]

"""Executor swap — FR-7 / CAP-2 harness-side handler.

Public surface (Story 2.9):
- `swap_executor_take_lock(project_id, edited_by, *, prev_executor_tuple,
  new_executor_tuple, intent, db=DEFAULT_DB) -> SwapReceipt` — under a
  project_edit_lock, records `{prev_yaml_hash, new_yaml_hash, edited_by,
  edited_at, intent, prev_executor_tuple, new_executor_tuple}` in the
  `project_yaml_edits` table (Story 2.10's Run Event Log stub).
- `SwapReceipt` frozen dataclass.
- `SwapRefused`, `SwapUnderLockHeld` exceptions.

AD-18 + AD-21 + FR-7 are the binding rules:
- AD-18: project_edit_lock is the only writer of project YAML; swap
  takes the lock.
- AD-21: the swap action is one of the dashboard's enumerated writes;
  the harness owns the lock + receipt.
- FR-7: prior step's locked artifacts are retained (the marker-file
  scheme enforces this); the prior executor's artifacts are NOT
  deleted.

The `project_yaml_edits` table is the Run Event Log stub. Story 2.10
absorbs these rows into the Run Event Log table.
"""

from __future__ import annotations

import sqlite3
import ulid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness.canonical import canonical_sha256
from harness.project_edit_lock import (
    DEFAULT_DB,
    ProjectLocked,
    acquire as _acquire_lock,
    release as _release_lock,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --- Exceptions ------------------------------------------------------------


class SwapError(Exception):
    """Base for swap errors."""


class SwapRefused(SwapError):
    """The swap was refused (e.g. unchanged executor tuple, malformed
    arguments). Not the same as `SwapUnderLockHeld` (a concurrency issue)."""


class SwapUnderLockHeld(SwapError):
    """Another swap holds the project_edit_lock.

    Per AD-18 (e): the loser is told who holds the lock. We wrap the
    lock module's `LockHeld` so callers can catch it uniformly.
    """


# --- Dataclass ------------------------------------------------------------


@dataclass(frozen=True)
class SwapReceipt:
    """The persisted receipt of a swap.

    Mirrors the schema of `project_yaml_edits` (Story 2.10's Run Event
    Log stub). The `prev_executor_tuple` and `new_executor_tuple` are
    JSON strings (ruamel.yaml-safe).
    """

    project_id: str
    edit_id: str  # ULID
    prev_yaml_hash: str
    new_yaml_hash: str
    edited_by: str
    edited_at: str  # ISO 8601 UTC
    intent: str
    prev_executor_tuple: str  # JSON
    new_executor_tuple: str  # JSON


# --- Helpers --------------------------------------------------------------


def _hash_yaml(project_id: str) -> str:
    """Compute the sha256 hash of the current project YAML (AD-17).

    The project YAML lives at `<project_root>/var/projects/<project_id>/project.yaml`.
    Resolved via `PROJECT_ROOT` (not a CWD-relative path) so the hash is
    stable regardless of the caller's working directory.

    The text branch of `canonical_bytes` is used (NFC + LF + trailing
    newline), not the binary branch, so a YAML saved with CRLF hashes
    the same as the same YAML saved with LF (AD-17's canonicalization
    guarantee). If the file is missing, the hash is the empty-string
    sha256 (a sentinel; the swap still records the receipt).
    """
    from harness.canonical import canonical_bytes

    path = PROJECT_ROOT / "var" / "projects" / project_id / "project.yaml"
    if not path.exists():
        return canonical_sha256(b"")
    # Text branch (NFC + LF + trailing newline) per AD-17.
    return canonical_sha256(path.read_text(encoding="utf-8"))


def _ensure_edits_table(db: sqlite3.Connection) -> None:
    """Make sure the `project_yaml_edits` table exists (mirrors the
    migration #4 SQL). Used by callers that open DEFAULT_DB before
    `migrate.run_migrations` has been invoked.
    """
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS project_yaml_edits (
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
        """.strip()
    )
    db.commit()


def _open_db(db: Path) -> sqlite3.Connection:
    """Open the lock DB with the standard pragmas; create parent dir."""
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# --- Public API -----------------------------------------------------------


def swap_executor_take_lock(
    project_id: str,
    edited_by: str,
    *,
    prev_executor_tuple: str,
    new_executor_tuple: str,
    intent: str,
    db: Path | None = None,
) -> SwapReceipt:
    """Perform a mid-project executor swap under the project_edit_lock.

    The function:
      1. Acquires the project_edit_lock (raises `LockHeld` on conflict).
      2. Computes `prev_yaml_hash` from the current project YAML.
      3. Computes `new_yaml_hash` (here, equal to `prev_yaml_hash` —
         the swap does not modify the YAML in v1; the operator
         manually edits the YAML AFTER the swap, which is a separate
         `acquire`-then-write flow owned by the dashboard).
      4. Inserts a `project_yaml_edits` row with the receipt.
      5. Releases the lock.

    Returns the persisted `SwapReceipt`. Raises `SwapUnderLockHeld`
    (wrapping `LockHeld`) on concurrency; `SwapRefused` on bad args.
    """
    db_path = db or DEFAULT_DB
    if not prev_executor_tuple or not new_executor_tuple:
        raise SwapRefused("executor_tuple_empty")
    if prev_executor_tuple == new_executor_tuple:
        raise SwapRefused("executor_tuple_unchanged")

    try:
        _acquire_lock(project_id, edited_by, db=db_path)
    except ProjectLocked as e:
        raise SwapUnderLockHeld(str(e)) from e
    try:
        prev_yaml_hash = _hash_yaml(project_id)
        new_yaml_hash = prev_yaml_hash  # see step 3 above
        edit_id = str(ulid.ULID.from_datetime(datetime.now(timezone.utc)))
        edited_at = datetime.now(timezone.utc).isoformat()

        conn = _open_db(db_path)
        try:
            _ensure_edits_table(conn)
            conn.execute(
                """
                INSERT INTO project_yaml_edits (
                    project_id, edit_id, prev_yaml_hash, new_yaml_hash,
                    edited_by, edited_at, intent,
                    prev_executor_tuple, new_executor_tuple
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """.strip(),
                (
                    project_id, edit_id, prev_yaml_hash, new_yaml_hash,
                    edited_by, edited_at, intent,
                    prev_executor_tuple, new_executor_tuple,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return SwapReceipt(
            project_id=project_id,
            edit_id=edit_id,
            prev_yaml_hash=prev_yaml_hash,
            new_yaml_hash=new_yaml_hash,
            edited_by=edited_by,
            edited_at=edited_at,
            intent=intent,
            prev_executor_tuple=prev_executor_tuple,
            new_executor_tuple=new_executor_tuple,
        )
    finally:
        # Best-effort release: the lock TTL also guarantees eventual
        # release if the holder dies before this call.
        _release_lock(project_id, acquired_by=edited_by, db=db_path)


__all__ = [
    "SwapReceipt",
    "SwapError",
    "SwapRefused",
    "SwapUnderLockHeld",
    "swap_executor_take_lock",
]


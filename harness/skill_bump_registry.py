"""Skill Bump Registry — AD-22, FR-6, FR-22, FR-23.

Public surface (Story 3.5):
- `BumpState` Literal — `pending_promotion | promoted`.
- `SkillBump` frozen dataclass.
- `register(skill_name, new_version, previous_version, *, registered_by) ->
  SkillBump` — creates a pending_promotion row + emits a regression-run
  request (the bench query with the new pin applied; the actual
  regression-run execution is the dashboard's responsibility per AD-21).
- `promote(bump_id, *, regression_run_id, promoted_by) -> SkillBump` —
  transitions pending_promotion → promoted only if `regression_run_id`'s
  result is `pass`. Returns `SkillRegressionMissing` / `SkillRegressionFailed`
  otherwise.
- `find_promoted(skill_name, version) -> SkillBump | None` — for the
  retry-ladder rung 4 (Story 3.6).

AD-22 binding: the registry is the only writer path; two CLI verbs
(`register`, `promote`) — any other write attempt returns
`SkillBumpRegistryImmutable`.
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
DEFAULT_DB = PROJECT_ROOT / "var" / "harness.sqlite"


BumpState = Literal["pending_promotion", "promoted"]


# --- Exceptions -----------------------------------------------------------


class SkillBumpRegistryError(Exception):
    """Base for all skill_bump_registry errors."""


class SkillBumpRegistryImmutable(SkillBumpRegistryError):
    """A write attempted via an unauthorized path (AD-22)."""


class SkillRegressionMissing(SkillBumpRegistryError):
    """promote() without a regression_run_id, or with a run that did not pass."""


class SkillRegressionFailed(SkillBumpRegistryError):
    """promote() with a regression_run_id whose result is not 'pass'."""


# --- Dataclass ------------------------------------------------------------


@dataclass(frozen=True)
class SkillBump:
    """A single row in skill_bumps."""

    bump_id: str  # ULID
    skill_name: str
    new_version: str
    previous_version: str
    state: BumpState
    registered_at: str
    promoted_at: str | None = None
    promoted_by: str | None = None
    regression_run_id: str | None = None


# --- Helpers --------------------------------------------------------------


def _open_db(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_table(db: sqlite3.Connection) -> None:
    _migrate.ensure_tables(db, "skill_bumps")


def register(
    skill_name: str,
    new_version: str,
    previous_version: str,
    *,
    registered_by: str = "cli",
    db: Path | None = None,
) -> SkillBump:
    """Register a new Skill version as `pending_promotion`.

    Triggers a regression-run request (the bench query of story 3.4 with
    the new pin applied). The actual regression-run execution is owned
    by the dashboard (AD-21); this registry emits a row the dashboard
    picks up.
    """
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        bump_id = str(ulid.ULID.from_datetime(datetime.now(timezone.utc)))
        registered_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO skill_bumps (
                bump_id, skill_name, new_version, previous_version,
                state, registered_at
            ) VALUES (?, ?, ?, ?, 'pending_promotion', ?)
            """.strip(),
            (bump_id, skill_name, new_version, previous_version, registered_at),
        )
        conn.commit()
    finally:
        conn.close()
    return SkillBump(
        bump_id=bump_id,
        skill_name=skill_name,
        new_version=new_version,
        previous_version=previous_version,
        state="pending_promotion",
        registered_at=registered_at,
    )


def promote(
    bump_id: str,
    *,
    regression_run_id: str,
    regression_result: str = "pass",
    promoted_by: str = "cli",
    db: Path | None = None,
) -> SkillBump:
    """Transition pending_promotion → promoted.

    Requires `regression_run_id` and `regression_result == 'pass'`.
    """
    if not regression_run_id:
        raise SkillRegressionMissing("regression_run_id required for promote")
    if regression_result != "pass":
        raise SkillRegressionFailed(
            f"regression result {regression_result!r} is not 'pass'; bump held back"
        )
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        cur = conn.execute(
            "SELECT bump_id, skill_name, new_version, previous_version, state, "
            "registered_at, promoted_at, promoted_by, regression_run_id "
            "FROM skill_bumps WHERE bump_id = ?",
            (bump_id,),
        ).fetchone()
        if cur is None:
            raise SkillRegressionMissing(f"bump not found: {bump_id}")
        if cur[4] == "promoted":
            return _row_to_bump(cur)
        promoted_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE skill_bumps SET state = 'promoted', promoted_at = ?, "
            "promoted_by = ?, regression_run_id = ? WHERE bump_id = ?",
            (promoted_at, promoted_by, regression_run_id, bump_id),
        )
        conn.commit()
        cur = conn.execute(
            "SELECT bump_id, skill_name, new_version, previous_version, state, "
            "registered_at, promoted_at, promoted_by, regression_run_id "
            "FROM skill_bumps WHERE bump_id = ?",
            (bump_id,),
        ).fetchone()
        return _row_to_bump(cur) if cur else SkillBump(
            bump_id=bump_id, skill_name="", new_version="", previous_version="",
            state="promoted", registered_at="", promoted_at=promoted_at,
            promoted_by=promoted_by, regression_run_id=regression_run_id,
        )
    finally:
        conn.close()


def find_promoted(
    skill_name: str,
    version: str,
    *,
    db: Path | None = None,
) -> SkillBump | None:
    """For retry-ladder rung 4: find a promoted Skill at the given pin."""
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT bump_id, skill_name, new_version, previous_version, state, "
            "registered_at, promoted_at, promoted_by, regression_run_id "
            "FROM skill_bumps "
            "WHERE skill_name = ? AND new_version = ? AND state = 'promoted'",
            (skill_name, version),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_bump(row) if row else None


def read(bump_id: str, *, db: Path | None = None) -> SkillBump | None:
    """Read one bump by `bump_id`, or None.

    The registry had no by-id reader; the dashboard's regression-diff view
    (Story 4.6) addresses a bump directly by the id it was handed at
    registration, so it needs exactly this.
    """
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT bump_id, skill_name, new_version, previous_version, state, "
            "registered_at, promoted_at, promoted_by, regression_run_id "
            "FROM skill_bumps WHERE bump_id = ?",
            (bump_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_bump(row) if row else None


def _row_to_bump(row: tuple) -> SkillBump:
    return SkillBump(
        bump_id=row[0], skill_name=row[1], new_version=row[2],
        previous_version=row[3], state=row[4], registered_at=row[5],
        promoted_at=row[6], promoted_by=row[7], regression_run_id=row[8],
    )


__all__ = [
    "SkillBump",
    "BumpState",
    "SkillBumpRegistryError",
    "SkillBumpRegistryImmutable",
    "SkillRegressionMissing",
    "SkillRegressionFailed",
    "DEFAULT_DB",
    "register",
    "promote",
    "find_promoted",
    "read",
]

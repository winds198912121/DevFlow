"""Cost Guard — AD-8 / NFR-Cost-2 per-tier ceilings + cost_overrun_ack.

Public surface (Story 4.2):
- `Decision` Literal — `continue | pause`.
- `DEFAULT_CEILINGS` — per-tier token limits (trivial=5e5, session=5e6,
  epic=5e7, project=2e8).
- `ProjectOverride` — per-project override of the tier default.
- `set_override(project_id, ceiling)` / `get_ceiling(project_id, tier)`.
- `check(project_id, *, tier, db) -> Decision` — returns `pause` when the
  accumulated cost exceeds the ceiling; `continue` otherwise.
- `ack_pause(project_id) -> None` — clears the paused flag (operator ack).
- `is_paused(project_id) -> bool`.

The cost_overrun_ack verb is one of the 6 allowed dashboard writes per
AD-21 (Epic 4 story 3's surface). The guard persists the paused state
in a SQLite table at `var/harness.sqlite` (table `cost_guard_pauses`).
"""

from __future__ import annotations

import sqlite3

from harness import migrate as _migrate
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from datetime import datetime

from harness.cost_ledger import sum_for_project


Decision = Literal["continue", "pause"]


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "var" / "harness.sqlite"


# Per-tier default ceilings (logged tokens = tokens_in + tokens_out).
DEFAULT_CEILINGS = {
    "trivial": 500_000,
    "session": 5_000_000,
    "epic": 50_000_000,
    "project": 200_000_000,
}
_SKILL_BUMP_MULTIPLIER = 3  # AD-8: skill-bump regressions get 3× the step's ceiling


# --- Helpers --------------------------------------------------------------


def _open_db(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_table(db: sqlite3.Connection) -> None:
    _migrate.ensure_tables(db, "cost_guard_overrides", "cost_guard_pauses")


def get_ceiling(project_id: str, tier: str, *, db: Path | None = None) -> int:
    """Project override (if set) else the tier default."""
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT ceiling FROM cost_guard_overrides WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        return int(row[0])
    return DEFAULT_CEILINGS.get(tier, DEFAULT_CEILINGS["epic"])


def set_override(
    project_id: str, ceiling: int, *, db: Path | None = None
) -> None:
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO cost_guard_overrides (project_id, ceiling)
            VALUES (?, ?)
            """.strip(),
            (project_id, ceiling),
        )
        conn.commit()
    finally:
        conn.close()


def check(
    project_id: str,
    *,
    tier: str = "epic",
    is_skill_bump: bool = False,
    db: Path | None = None,
) -> Decision:
    """Check whether `project_id` has exceeded its tier's ceiling.

    Returns `pause` when `cost_sum_for_project >= ceiling`; `continue`
    otherwise. Skill-bump regression runs get 3× the normal ceiling
    (AD-8).
    """
    db_path = db or DEFAULT_DB
    if is_paused(project_id, db=db_path):
        return "pause"
    ceiling = get_ceiling(project_id, tier, db=db_path)
    if is_skill_bump:
        ceiling *= _SKILL_BUMP_MULTIPLIER
    total = sum_for_project(project_id, db=db_path)
    if total >= ceiling:
        # Record the pause state so subsequent invocations return `pause`.
        conn = _open_db(db_path)
        try:
            _ensure_table(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO cost_guard_pauses
                    (project_id, paused_at)
                VALUES (?, ?)
                """.strip(),
                (project_id, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()
        return "pause"
    return "continue"


def is_paused(project_id: str, *, db: Path | None = None) -> bool:
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT 1 FROM cost_guard_pauses WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def ack_pause(project_id: str, *, db: Path | None = None) -> None:
    """Clear the paused flag (operator cost_overrun_ack)."""
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        conn.execute(
            "DELETE FROM cost_guard_pauses WHERE project_id = ?",
            (project_id,),
        )
        conn.commit()
    finally:
        conn.close()


def clear_override(project_id: str, *, db: Path | None = None) -> None:
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        conn.execute(
            "DELETE FROM cost_guard_overrides WHERE project_id = ?",
            (project_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now().isoformat()


__all__ = [
    "Decision",
    "DEFAULT_CEILINGS",
    "DEFAULT_DB",
    "get_ceiling",
    "set_override",
    "clear_override",
    "check",
    "ack_pause",
    "is_paused",
]
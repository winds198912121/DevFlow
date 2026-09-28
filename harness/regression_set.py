"""Regression Set + Benchmark query — FR-18, FR-20, FR-21, NFR-Reliab-3, AD-7.

Public surface (Story 3.4):
- `ComparableRun` frozen dataclass (one row in regression_set_runs).
- `ComparableKey` namedtuple — `(step, project_size_tier,
  artifact_contract_version)` — the cell key.
- `add(run_event_id, step, project_size_tier, artifact_contract_version,
   metric_value, metric_definition, added_by) -> ComparableRun`.
- `bench_query(step, project_size_tier, artifact_contract_version=None,
   *, k=3) -> BenchResult` — returns a recommendation OR raises.
- `BenchRecommendation` frozen dataclass.
- `BenchInsufficient`, `NonComparableSet`, `RegressionSetRemoveRequiresReason`
  exceptions.

AD-7 binding:
- `add` is append-only: re-adding the same `run_event_id` is a no-op
  (the row stays at its first-add timestamp).
- Raw success rate is NOT the primary metric; the metric is recorded
  per `add` call (default: `acceptance_coverage.fr_passed / fr_total`).

NFR-Reliab-3 binding:
- `bench_query` returns `BenchInsufficient` when the comparable-run
  count is below `k` (default 3).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "var" / "harness.sqlite"


# --- Exceptions -----------------------------------------------------------


class RegressionSetError(Exception):
    """Base for all regression_set errors."""


class BenchInsufficient(RegressionSetError):
    """Comparable-run count for the cell is below the K floor."""


class NonComparableSet(RegressionSetError):
    """Mixing project_size_tiers or contract versions without an explicit override."""


class RegressionSetRemoveRequiresReason(RegressionSetError):
    """Remove without a justification."""


# --- Dataclass ------------------------------------------------------------


class ComparableKey(NamedTuple):
    """A comparable-cell key."""
    step: str
    project_size_tier: str
    artifact_contract_version: str


@dataclass(frozen=True)
class ComparableRun:
    """One row in the regression_set_runs table."""

    run_event_id: str
    step: str
    project_size_tier: str
    artifact_contract_version: str
    metric_value: float
    metric_definition: str
    added_at: str
    removed_at: str | None = None
    added_by: str = ""


@dataclass(frozen=True)
class BenchRecommendation:
    """The output of a successful bench query."""

    step: str
    project_size_tier: str
    artifact_contract_version: str
    metric_definition: str
    contributing_runs: tuple[str, ...]  # run_event_ids
    metric_summary: float  # mean of metric_value across contributing runs


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
        CREATE TABLE IF NOT EXISTS regression_set_runs (
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
        """.strip()
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_runs (
            benchmark_id TEXT PRIMARY KEY,
            step TEXT NOT NULL,
            project_size_tier TEXT NOT NULL,
            artifact_contract_version TEXT,
            metric_definition TEXT NOT NULL,
            computed_at TEXT NOT NULL,
            result_json TEXT NOT NULL
        )
        """.strip()
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS regression_set_removals (
            removed_run_id TEXT PRIMARY KEY,
            removed_at TEXT NOT NULL,
            removed_by TEXT NOT NULL,
            reason TEXT NOT NULL
        )
        """.strip()
    )
    db.commit()


# --- Public API ------------------------------------------------------------


def add(
    run_event_id: str,
    step: str,
    project_size_tier: str,
    artifact_contract_version: str,
    metric_value: float,
    metric_definition: str,
    added_by: str,
    *,
    db: Path | None = None,
) -> ComparableRun:
    """Add a run to the regression set. Append-only — re-add is a no-op."""
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        cur = conn.execute(
            "SELECT 1 FROM regression_set_runs WHERE run_event_id = ?",
            (run_event_id,),
        ).fetchone()
        if cur is not None:
            # No-op: re-add returns the existing row.
            row = conn.execute(
                "SELECT run_event_id, step, project_size_tier, artifact_contract_version, "
                "metric_value, metric_definition, added_at, removed_at, added_by "
                "FROM regression_set_runs WHERE run_event_id = ?",
                (run_event_id,),
            ).fetchone()
            return _row_to_comparable(row)
        added_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO regression_set_runs (
                run_event_id, step, project_size_tier, artifact_contract_version,
                metric_value, metric_definition, added_at, added_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """.strip(),
            (
                run_event_id, step, project_size_tier,
                artifact_contract_version, metric_value, metric_definition,
                added_at, added_by,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return ComparableRun(
        run_event_id=run_event_id,
        step=step,
        project_size_tier=project_size_tier,
        artifact_contract_version=artifact_contract_version,
        metric_value=metric_value,
        metric_definition=metric_definition,
        added_at=added_at,
        added_by=added_by,
    )


def _row_to_comparable(row: tuple) -> ComparableRun:
    return ComparableRun(
        run_event_id=row[0], step=row[1], project_size_tier=row[2],
        artifact_contract_version=row[3], metric_value=row[4],
        metric_definition=row[5], added_at=row[6], removed_at=row[7],
        added_by=row[8],
    )


def bench_query(
    step: str,
    project_size_tier: str,
    artifact_contract_version: str | None = None,
    *,
    k: int = 3,
    db: Path | None = None,
) -> BenchRecommendation:
    """Query the regression set for a (step, tier, contract) cell.

    Returns a `BenchRecommendation` when at least `k` comparable runs
    exist; raises `BenchInsufficient` otherwise. Cross-tier or
    cross-contract mixing (without an explicit override) raises
    `NonComparableSet`.
    """
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        if artifact_contract_version is not None:
            rows = conn.execute(
                """
                SELECT run_event_id, step, project_size_tier, artifact_contract_version,
                       metric_value, metric_definition, added_at, removed_at, added_by
                FROM regression_set_runs
                WHERE step = ? AND project_size_tier = ?
                  AND artifact_contract_version = ?
                  AND removed_at IS NULL
                ORDER BY added_at ASC
                """.strip(),
                (step, project_size_tier, artifact_contract_version),
            ).fetchall()
            metric_def = "see-row"
            if rows:
                metric_def = rows[0][5]
        else:
            # Mixed contract versions: refuse (NonComparableSet) unless
            # all rows happen to share a metric_definition (degenerate
            # case the caller can re-query explicitly with the version).
            rows = conn.execute(
                """
                SELECT run_event_id, step, project_size_tier, artifact_contract_version,
                       metric_value, metric_definition, added_at, removed_at, added_by
                FROM regression_set_runs
                WHERE step = ? AND project_size_tier = ?
                  AND removed_at IS NULL
                ORDER BY added_at ASC
                """.strip(),
                (step, project_size_tier),
            ).fetchall()
            distinct_contracts = {r[3] for r in rows}
            if len(distinct_contracts) > 1:
                raise NonComparableSet(
                    f"mixed contract versions {distinct_contracts}; "
                    "specify artifact_contract_version explicitly"
                )
            if not rows:
                metric_def = ""
            else:
                metric_def = rows[0][5]
    finally:
        conn.close()
    if len(rows) < k:
        raise BenchInsufficient(
            f"comparable_run_count={len(rows)} < k={k} for step={step} "
            f"tier={project_size_tier} contract={artifact_contract_version}"
        )
    contributing = tuple(r[0] for r in rows)
    metric_summary = sum(r[4] for r in rows) / len(rows)
    return BenchRecommendation(
        step=step,
        project_size_tier=project_size_tier,
        artifact_contract_version=(
            artifact_contract_version if artifact_contract_version is not None
            else (rows[0][3] if rows else "")
        ),
        metric_definition=metric_def,
        contributing_runs=contributing,
        metric_summary=metric_summary,
    )


def remove(
    run_event_id: str,
    *,
    reason: str | None = None,
    removed_by: str = "",
    db: Path | None = None,
) -> bool:
    """Tombstone a regression-set row. Requires `reason` (NFR-Reliab-3 audit)."""
    if not reason:
        raise RegressionSetRemoveRequiresReason("reason required for remove")
    db_path = db or DEFAULT_DB
    conn = _open_db(db_path)
    try:
        _ensure_table(conn)
        # Idempotent: if the row was already removed (removed_at != NULL),
        # skip the audit row.
        cur = conn.execute(
            "SELECT removed_at FROM regression_set_runs WHERE run_event_id = ?",
            (run_event_id,),
        ).fetchone()
        if cur is None:
            return False
        if cur[0] is not None:
            return False  # already tombstoned
        conn.execute(
            "UPDATE regression_set_runs SET removed_at = ? WHERE run_event_id = ?",
            (datetime.now(timezone.utc).isoformat(), run_event_id),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO regression_set_removals
                (removed_run_id, removed_at, removed_by, reason)
            VALUES (?, ?, ?, ?)
            """.strip(),
            (run_event_id, datetime.now(timezone.utc).isoformat(), removed_by, reason),
        )
        conn.commit()
        return True
    finally:
        conn.close()


__all__ = [
    "ComparableRun",
    "ComparableKey",
    "BenchRecommendation",
    "RegressionSetError",
    "BenchInsufficient",
    "NonComparableSet",
    "RegressionSetRemoveRequiresReason",
    "DEFAULT_DB",
    "add",
    "bench_query",
    "remove",
]


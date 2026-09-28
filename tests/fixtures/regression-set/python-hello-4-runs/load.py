"""Regression-set fixture loader — Story 3.8.

Reads `tests/fixtures/regression-set/python-hello-4-runs/run_summary.json`
and populates `var/harness.sqlite` (regression_set_runs table) via
`harness.regression_set.add`. The fixture provides 4 comparable runs on
the python-hello fixture at `trivial` tier so `bench_query` returns a
recommendation.

Public surface:
- `REGRESSION_SET_FIXTURE_DIR` constant path.
- `FIXTURE_STEP`, `FIXTURE_TIER`, `FIXTURE_CONTRACT` constants.
- `load(*, db=DEFAULT_DB) -> int` — idempotent: re-loading is a no-op.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.regression_set import add as _rs_add
from harness.regression_set import DEFAULT_DB


REGRESSION_SET_FIXTURE_DIR = (
    Path(__file__).resolve().parent
)
FIXTURE_SUMMARY_PATH = REGRESSION_SET_FIXTURE_DIR / "run_summary.json"

FIXTURE_STEP = "coding"
FIXTURE_TIER = "trivial"
FIXTURE_CONTRACT = "v1"


def _read_summary() -> dict[str, Any]:
    return json.loads(FIXTURE_SUMMARY_PATH.read_text(encoding="utf-8"))


def _existing_ids(db_path: Path) -> set[str]:
    """Return the set of run_event_ids already in regression_set_runs."""
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT run_event_id FROM regression_set_runs"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def load(*, db: Path | None = None) -> int:
    """Populate the regression set from the fixture summary.

    Returns the count of newly-added runs (0 if the fixture was already
    loaded — `add()` is a no-op on re-add per AD-7 / Story 3.4).

    Pre-loads the existing ids from the DB so the return value reflects
    ONLY the run_event_ids added in this call (vs. the existing
    `add()`-as-no-op behavior which always returns the same row).
    """
    summary = _read_summary()
    db_path = db or DEFAULT_DB
    existing_before = _existing_ids(db_path)
    fixture_ids = {run["run_event_id"] for run in summary["runs"]}
    for run in summary["runs"]:
        _rs_add(
            run["run_event_id"],
            step=summary["step"],
            project_size_tier=summary["project_size_tier"],
            artifact_contract_version=summary["artifact_contract_version"],
            metric_value=run["metric_value"],
            metric_definition=summary["metric_definition"],
            added_by=summary.get("added_by", "fixture"),
            db=db,
        )
    existing_after = _existing_ids(db_path)
    newly_added = existing_after - existing_before
    # The fixture always expects 4 fixture ids; if any are missing,
    # the load was incomplete (the caller may want to flag).
    assert newly_added <= fixture_ids, (
        f"unexpected new ids: {newly_added - fixture_ids}"
    )
    return len(newly_added)


__all__ = [
    "REGRESSION_SET_FIXTURE_DIR",
    "FIXTURE_SUMMARY_PATH",
    "FIXTURE_STEP",
    "FIXTURE_TIER",
    "FIXTURE_CONTRACT",
    "load",
]

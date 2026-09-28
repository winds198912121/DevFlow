"""Retry Ladder — FR-15, AD-6, AD-22.

Public surface (Story 3.3):
- `RungResult` Literal — `ok | fail | error | paused`.
- `RungOutcome` frozen dataclass.
- `RungRecord` frozen dataclass (one entry on a step's `retry[]`).
- `advance(step_state, *, db) -> RungOutcome` — moves the ladder one rung.

Rung order per FR-15:
  (1) same Agent + same LLM + same Skill (initial state).
  (2) same Agent + different LLM.
  (3) different Agent + better LLM (recommendation via `bench_query`).
  (4) different Agent + different LLM + promoted Skill (deferred rung;
      story 3.6 closes the gap).
  (5) human intervention (operator-initiated, never auto).

Every rung attempt is recorded on the step's `retry[]` (the ErrorRecord's
retry list).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from harness.error_store import ErrorRecord, append as _es_append
from harness.regression_set import bench_query as _bench
from harness.skill_bump_registry import (
    find_promoted as _find_promoted,
    SkillRegressionMissing,
)


RungResult = Literal["ok", "fail", "error", "paused"]


@dataclass(frozen=True)
class RungRecord:
    """A single attempt at a rung."""

    rung_number: int  # 1..5
    executor_tuple: str  # JSON-serialized
    result: RungResult
    timestamp: str  # ISO 8601 UTC


@dataclass(frozen=True)
class RungOutcome:
    """The next step the operator / harness should take."""

    next_rung: int | None  # None = done (success or human-pause)
    executor_tuple: str  # JSON-serialized
    result: RungResult
    error_record: ErrorRecord | None


# --- Helpers --------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_STEP_CATEGORY_MAP = {
    "research": "research",
    "design": "design",
    "coding": "coding",
    "testing": "testing",
    "review": "review",
    "delivery": "delivery",
}


def _step_category(step: str) -> str:
    """Map a step name to the closed error-category enum (or 'coding' fallback)."""
    return _STEP_CATEGORY_MAP.get(step, "coding")


def _open_db(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# --- Rung helpers ---------------------------------------------------------


def rung_1_same(state: dict, executor_pool: list[dict]) -> dict | None:
    """Rung 1: same Agent + same LLM + same Skill (re-attempt)."""
    if not executor_pool:
        return None
    return executor_pool[0]


def rung_2_same_agent_diff_llm(state: dict, executor_pool: list[dict]) -> dict | None:
    """Rung 2: same Agent + different LLM."""
    agent = state.get("agent")
    if not agent:
        return None
    candidates = [
        e for e in executor_pool
        if e.get("agent") == agent and e.get("model") != state.get("model")
    ]
    return candidates[0] if candidates else None


def rung_3_diff_agent_better_llm(
    state: dict, executor_pool: list[dict], *, step: str, tier: str
) -> dict | None:
    """Rung 3: different Agent + better LLM (or any non-self LLM fallback)."""
    current_agent = state.get("agent")
    candidates = [e for e in executor_pool if e.get("agent") != current_agent]
    if not candidates:
        return None
    # Try bench recommendation; fall back to the first non-self agent.
    # The bench metric gives ranking semantics in a follow-on story.
    try:
        _bench(step, tier, db=None)
    except Exception:
        pass
    return candidates[0]


def rung_4_promoted_skill(
    state: dict, skill_name: str, new_version: str, *, db: Path | None = None
) -> dict:
    """Rung 4: different Agent + different LLM + promoted Skill.

    Story 3.5 closes this gap; raises SkillRegressionMissing if no
    promoted Skill exists at the requested pin.
    """
    bump = _find_promoted(skill_name, new_version, db=db)
    if bump is None:
        raise SkillRegressionMissing(
            f"no promoted Skill at pin {skill_name}@{new_version}; "
            "rung 4 paused for operator action"
        )
    # The new pin is on the bump; the executor tuple is the bump's
    # `new_version` (a string). v1 returns a placeholder tuple; a future
    # story will resolve a full agent/LLM/skill tuple from the bump.
    return {"rung": 4, "skill_pin": f"{skill_name}@{new_version}", "bump_id": bump.bump_id}


# --- Public API ------------------------------------------------------------


def advance(
    project_id: str,
    run_id: str,
    step: str,
    *,
    executor_pool: list[dict],
    current_executor: dict,
    rung_history: list[RungRecord] | None = None,
    skill_name: str | None = None,
    skill_version: str | None = None,
    db: Path | None = None,
) -> RungOutcome:
    """Advance the ladder one rung. Records the attempt on `retry[]`."""
    rung_history = list(rung_history or [])
    next_rung_num = (rung_history[-1].rung_number if rung_history else 0) + 1
    state = dict(current_executor)
    state["project_id"] = project_id
    state["run_id"] = run_id
    state["step"] = step

    if next_rung_num == 1:
        candidate = rung_1_same(state, executor_pool)
        result: RungResult = "fail"
    elif next_rung_num == 2:
        candidate = rung_2_same_agent_diff_llm(state, executor_pool)
        result = "fail"
    elif next_rung_num == 3:
        candidate = rung_3_diff_agent_better_llm(
            state, executor_pool, step=step, tier=current_executor.get("tier", "epic"),
        )
        result = "fail"
    elif next_rung_num == 4:
        # Story 3.5 / 3.6 closes rung 4. v1 stub: raise immediately.
        try:
            candidate = rung_4_promoted_skill(
                state, skill_name or "", skill_version or "",
                db=db,
            )
            result = "fail"
        except SkillRegressionMissing as exc:
            return _record_and_pause(
                project_id, run_id, step, 4, current_executor, str(exc),
                db=db,
            )
    elif next_rung_num >= 5:
        # Rung 5: human intervention; never auto.
        return _record_and_pause(
            project_id, run_id, step, 5, current_executor,
            "rung 5 paused for human intervention",
            db=db,
        )
    else:
        candidate = None

    if candidate is None:
        return _record_and_pause(
            project_id, run_id, step, next_rung_num, current_executor,
            f"no candidate for rung {next_rung_num}",
            db=db,
        )

    # Record the attempt on retry[] (best-effort — error_store.write
    # never fails on missing fields).
    record = ErrorRecord(
        record_id="",
        project_id=project_id,
        run_id=run_id,
        step=step,
        attempt=len(rung_history) + 1,
        category=_step_category(step),
        root_cause=(f"rung {next_rung_num} attempt",),
        correction=(),
        retry=(
            {
                "rung": next_rung_num,
                "executor_tuple": str(candidate),
                "result": result,
                "timestamp": _now_iso(),
            },
        ),
        result=result,
        recorded_at=_now_iso(),
    )
    persisted = _es_append(record, db=db)
    return RungOutcome(
        next_rung=next_rung_num + 1,
        executor_tuple=str(candidate),
        result=result,
        error_record=persisted,
    )


def _record_and_pause(
    project_id: str,
    run_id: str,
    step: str,
    rung_num: int,
    current_executor: dict,
    reason: str,
    *,
    db: Path | None,
) -> RungOutcome:
    """Append a `paused` rung record and return the paused outcome."""
    record = ErrorRecord(
        record_id="",
        project_id=project_id,
        run_id=run_id,
        step=step,
        attempt=rung_num,
        category=_step_category(step),
        root_cause=(reason,),
        correction=(),
        retry=(
            {
                "rung": rung_num,
                "executor_tuple": str(current_executor),
                "result": "paused",
                "timestamp": _now_iso(),
            },
        ),
        result="paused",
        recorded_at=_now_iso(),
    )
    persisted = _es_append(record, db=db)
    return RungOutcome(
        next_rung=None,
        executor_tuple=str(current_executor),
        result="paused",
        error_record=persisted,
    )


__all__ = [
    "RungResult",
    "RungRecord",
    "RungOutcome",
    "advance",
    "rung_1_same",
    "rung_2_same_agent_diff_llm",
    "rung_3_diff_agent_better_llm",
    "rung_4_promoted_skill",
]

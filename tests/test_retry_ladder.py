"""Tests for harness.retry_ladder (Story 3.3)."""

from __future__ import annotations

import pytest

from harness.error_store import DEFAULT_DB as _ES_DB
from harness.retry_ladder import (
    advance,
    rung_1_same,
    rung_2_same_agent_diff_llm,
    rung_3_diff_agent_better_llm,
    rung_4_promoted_skill,
)


@pytest.fixture(autouse=True)
def _clean_db():
    if _ES_DB.exists():
        _ES_DB.unlink()
    for ext in (".sqlite-wal", ".sqlite-shm"):
        p = _ES_DB.with_suffix(ext)
        if p.exists():
            p.unlink()
    yield
    if _ES_DB.exists():
        _ES_DB.unlink()
    for ext in (".sqlite-wal", ".sqlite-shm"):
        p = _ES_DB.with_suffix(ext)
        if p.exists():
            p.unlink()


def test_rung_1_returns_first_executor():
    pool = [{"agent": "codex", "model": "gpt-5", "skills": ["x"]}]
    assert rung_1_same({}, pool) == pool[0]


def test_rung_2_returns_same_agent_diff_llm():
    pool = [
        {"agent": "codex", "model": "gpt-5", "skills": ["x"]},
        {"agent": "codex", "model": "gpt-4", "skills": ["x"]},
    ]
    state = {"agent": "codex", "model": "gpt-5"}
    out = rung_2_same_agent_diff_llm(state, pool)
    assert out["model"] == "gpt-4"


def test_rung_3_returns_non_self_agent():
    pool = [
        {"agent": "codex", "model": "gpt-5"},
        {"agent": "claude-code", "model": "opus"},
    ]
    state = {"agent": "codex", "model": "gpt-5"}
    out = rung_3_diff_agent_better_llm(
        state, pool, step="coding", tier="trivial"
    )
    assert out["agent"] == "claude-code"


def test_rung_4_raises_when_no_promoted_bump():
    """Without a promoted Skill bump, rung_4 raises SkillRegressionMissing."""
    from harness.skill_bump_registry import SkillRegressionMissing
    with pytest.raises(SkillRegressionMissing):
        rung_4_promoted_skill(
            {"agent": "codex", "model": "gpt-5"},
            "bmad-build", "9.9.9",
        )


def test_advance_records_each_rung_on_retry_array():
    pool = [
        {"agent": "codex", "model": "gpt-5"},
        {"agent": "claude-code", "model": "opus"},
        {"agent": "pi", "model": "sonnet"},
    ]
    outcome = advance(
        project_id="p1",
        run_id="R1",
        step="coding",
        executor_pool=pool,
        current_executor=pool[0],
    )
    assert outcome.error_record is not None
    assert outcome.error_record.retry[0]["rung"] == 1


def test_advance_reaches_rung_5_and_pauses_for_human():
    pool = [
        {"agent": "codex", "model": "gpt-5"},
        {"agent": "claude-code", "model": "opus"},
    ]
    # Simulate being on rung 4 by passing a history of 3 attempts.
    from harness.retry_ladder import RungRecord
    history = [
        RungRecord(rung_number=1, executor_tuple="{}", result="fail",
                    timestamp="2026-09-28T00:00:00+00:00"),
        RungRecord(rung_number=2, executor_tuple="{}", result="fail",
                    timestamp="2026-09-28T00:00:01+00:00"),
        RungRecord(rung_number=3, executor_tuple="{}", result="fail",
                    timestamp="2026-09-28T00:00:02+00:00"),
    ]
    outcome = advance(
        project_id="p1",
        run_id="R1",
        step="coding",
        executor_pool=pool,
        current_executor=pool[0],
        rung_history=history,
    )
    assert outcome.result == "paused"
    assert outcome.next_rung is None

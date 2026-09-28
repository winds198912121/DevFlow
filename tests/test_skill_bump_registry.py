"""Tests for harness.skill_bump_registry (Story 3.5)."""

from __future__ import annotations

import pytest

from harness.skill_bump_registry import (
    DEFAULT_DB,
    SkillRegressionFailed,
    SkillRegressionMissing,
    find_promoted,
    promote,
    register,
)


@pytest.fixture(autouse=True)
def _clean_db():
    if DEFAULT_DB.exists():
        DEFAULT_DB.unlink()
    for ext in (".sqlite-wal", ".sqlite-shm"):
        p = DEFAULT_DB.with_suffix(ext)
        if p.exists():
            p.unlink()
    yield
    if DEFAULT_DB.exists():
        DEFAULT_DB.unlink()
    for ext in (".sqlite-wal", ".sqlite-shm"):
        p = DEFAULT_DB.with_suffix(ext)
        if p.exists():
            p.unlink()


def test_register_creates_pending_bump():
    bump = register("bmad-build", "0.5.0", "0.4.2", registered_by="cli")
    assert bump.state == "pending_promotion"
    assert bump.bump_id


def test_promote_without_regression_run_raises_missing():
    bump = register("bmad-build", "0.5.0", "0.4.2")
    with pytest.raises(SkillRegressionMissing):
        promote(bump.bump_id, regression_run_id="")


def test_promote_with_failed_regression_raises_failed():
    bump = register("bmad-build", "0.5.0", "0.4.2")
    with pytest.raises(SkillRegressionFailed):
        promote(
            bump.bump_id,
            regression_run_id="run_001",
            regression_result="fail",
        )


def test_promote_with_passing_regression_flips_to_promoted():
    bump = register("bmad-build", "0.5.0", "0.4.2")
    promoted = promote(
        bump.bump_id,
        regression_run_id="run_002",
        regression_result="pass",
        promoted_by="ops",
    )
    assert promoted.state == "promoted"
    assert promoted.promoted_by == "ops"


def test_find_promoted_returns_none_for_pending():
    bump = register("bmad-build", "0.5.0", "0.4.2")
    assert find_promoted("bmad-build", "0.5.0") is None


def test_find_promoted_returns_promoted_bump():
    bump = register("bmad-build", "0.5.0", "0.4.2")
    promote(bump.bump_id, regression_run_id="run_002", regression_result="pass")
    found = find_promoted("bmad-build", "0.5.0")
    assert found is not None
    assert found.state == "promoted"


def test_promote_is_idempotent():
    bump = register("bmad-build", "0.5.0", "0.4.2")
    promoted1 = promote(bump.bump_id, regression_run_id="run_002",
                        regression_result="pass", promoted_by="ops")
    promoted2 = promote(bump.bump_id, regression_run_id="run_002",
                        regression_result="pass", promoted_by="ops")
    assert promoted1.bump_id == promoted2.bump_id
    assert promoted1.state == promoted2.state == "promoted"

"""Tests for harness.cost_guard (Story 4.2)."""

from __future__ import annotations

import pytest

from harness.cost_guard import (
    DEFAULT_CEILINGS,
    DEFAULT_DB,
    ack_pause,
    check,
    clear_override,
    get_ceiling,
    is_paused,
    set_override,
)
from harness.cost_ledger import append as _cost_append


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


def test_get_ceiling_returns_default_per_tier():
    assert get_ceiling("any-project", "trivial") == DEFAULT_CEILINGS["trivial"]
    assert get_ceiling("any-project", "epic") == DEFAULT_CEILINGS["epic"]


def test_set_override_changes_ceiling():
    set_override("p1", 1_000_000)
    assert get_ceiling("p1", "trivial") == 1_000_000
    clear_override("p1")
    assert get_ceiling("p1", "trivial") == DEFAULT_CEILINGS["trivial"]


def test_check_returns_continue_below_ceiling():
    _cost_append("p1", tokens_in=100, tokens_out=50)
    assert check("p1", tier="trivial") == "continue"


def test_check_returns_pause_at_ceiling():
    """trivial ceiling is 500,000 tokens; record 500k and verify pause."""
    _cost_append("p1", tokens_in=300_000, tokens_out=200_000)
    decision = check("p1", tier="trivial")
    assert decision == "pause"
    # The pause state is persisted; a second check returns pause too.
    assert is_paused("p1")
    assert check("p1", tier="trivial") == "pause"


def test_ack_pause_clears_pause_state():
    _cost_append("p1", tokens_in=300_000, tokens_out=200_000)
    check("p1", tier="trivial")
    assert is_paused("p1")
    ack_pause("p1")
    assert not is_paused("p1")


def test_skill_bump_3x_ceiling():
    """Skill-bump regressions get 3× the normal ceiling (AD-8)."""
    # trivial default = 500_000. Skill-bump ceiling = 1_500_000.
    # Record 1_000_000 — passes normal, fails skill-bump (1_000_000 < 1_500_000 = pause)
    _cost_append("p1", tokens_in=600_000, tokens_out=400_000)
    # First check (normal) — passes (1,000,000 < 500_000? no, equal -> pause normal).
    # To isolate, set a higher override:
    set_override("p1", 1_200_000)
    assert check("p1", tier="trivial") == "continue"
    # With is_skill_bump=True, ceiling is 1_200_000 * 3 = 3_600_000; same cost passes.
    assert check("p1", tier="trivial", is_skill_bump=True) == "continue"

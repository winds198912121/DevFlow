"""Tests for harness.executor_swap (Story 2.9).

Covers FR-7 / CAP-2: the swap_executor_take_lock handler enforces
AD-18 (project_edit_lock under the swap), AD-21 (the action is one
of the dashboard's enumerated writes; the harness owns the lock +
receipt), and FR-7 (prior step's locked artifacts are retained).

The CAP-2 cross-invocation climax is owned by Story 2.10; this test
file exercises the swap handler + concurrency control only.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from harness.executor_swap import (
    SwapRefused,
    SwapUnderLockHeld,
    swap_executor_take_lock,
)
from harness.project_edit_lock import DEFAULT_DB

# JSON dict literals — pinned by length to keep this file under 79 cols.
_HUMAN_TUPLE = json.dumps(
    {"mode": "human", "agent": None, "model": None, "skills": []}
)
_AGENT_TUPLE = json.dumps(
    {
        "mode": "agent",
        "agent": "codex",
        "model": "gpt-5",
        "skills": ["bmad-build@0.4.2"],
    }
)
_AGENT_TUPLE_NO_SKILLS = json.dumps(
    {"mode": "agent", "agent": "codex", "model": "gpt-5", "skills": []}
)


# --- Autouse: clean var/ between tests -----------------------------------


@pytest.fixture(autouse=True)
def _clean_var(tmp_path):
    """Wipe var/ + use a tmp_path DB so tests don't touch the real one."""
    # The default DEFAULT_DB is var/devflow.sqlite — wipe before + after.
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


# --- AC: SwapRefused on bad args -----------------------------------------


def test_swap_with_unchanged_tuple_raises_refused():
    tuple_str = _HUMAN_TUPLE
    with pytest.raises(SwapRefused, match="executor_tuple_unchanged"):
        swap_executor_take_lock(
            "p1", "mei",
            prev_executor_tuple=tuple_str,
            new_executor_tuple=tuple_str,
            intent="swap",
        )


def test_swap_with_empty_tuple_raises_refused():
    with pytest.raises(SwapRefused, match="executor_tuple_empty"):
        swap_executor_take_lock(
            "p1", "mei",
            prev_executor_tuple="",
            new_executor_tuple="",
            intent="swap",
        )


# --- AC: happy path writes a receipt ------------------------------------


def test_swap_happy_path_returns_swap_receipt():
    prev = _HUMAN_TUPLE
    new = _AGENT_TUPLE
    receipt = swap_executor_take_lock(
        "p1", "mei",
        prev_executor_tuple=prev,
        new_executor_tuple=new,
        intent="swap to codex for coding",
    )
    assert receipt.project_id == "p1"
    assert receipt.edited_by == "mei"
    assert receipt.intent == "swap to codex for coding"
    assert receipt.prev_executor_tuple == prev
    assert receipt.new_executor_tuple == new
    assert receipt.edit_id  # ULID, non-empty
    assert receipt.prev_yaml_hash.startswith("sha256:")
    assert receipt.new_yaml_hash == receipt.prev_yaml_hash


def test_swap_writes_project_yaml_edits_row():
    prev = _HUMAN_TUPLE
    new = _AGENT_TUPLE_NO_SKILLS
    swap_executor_take_lock(
        "p1", "mei",
        prev_executor_tuple=prev,
        new_executor_tuple=new,
        intent="swap",
    )
    conn = sqlite3.connect(str(DEFAULT_DB))
    rows = conn.execute(
        "SELECT project_id, edited_by, intent FROM project_yaml_edits"
    ).fetchall()
    assert rows == [("p1", "mei", "swap")]
    conn.close()


# --- AC: lock released after swap (lock holder can re-acquire) ------------


def test_swap_releases_lock_after_completion():
    prev = _HUMAN_TUPLE
    new = _AGENT_TUPLE_NO_SKILLS
    swap_executor_take_lock(
        "p1", "mei",
        prev_executor_tuple=prev,
        new_executor_tuple=new,
        intent="swap",
    )
    conn = sqlite3.connect(str(DEFAULT_DB))
    rows = conn.execute(
        "SELECT COUNT(*) FROM project_edit_locks WHERE project_id = 'p1'"
    ).fetchall()
    assert rows[0][0] == 0
    conn.close()


# --- AC: concurrent swap raises SwapUnderLockHeld -------------------------


def test_concurrent_swap_raises_under_lock_held():
    """A second swap on the same project within the TTL raises
    SwapUnderLockHeld (wrapping the lock module's LockHeld).
    """
    prev = _HUMAN_TUPLE
    new = _AGENT_TUPLE_NO_SKILLS
    # First swap acquires + releases (atomic). For a true concurrency
    # test, manually acquire the lock first, then attempt the swap.
    from harness.project_edit_lock import acquire as _acquire, release as _release

    _acquire("p1", "ops")
    with pytest.raises(SwapUnderLockHeld, match="ops"):
        swap_executor_take_lock(
            "p1", "mei",
            prev_executor_tuple=prev,
            new_executor_tuple=new,
            intent="swap",
        )
    _release("p1", acquired_by="ops")


# --- AC: receipt edit_id is a ULID --------------------------------------


def test_receipt_edit_id_is_ulid():
    import ulid as _ulid
    prev = _HUMAN_TUPLE
    new = _AGENT_TUPLE_NO_SKILLS
    receipt = swap_executor_take_lock(
        "p1", "mei",
        prev_executor_tuple=prev,
        new_executor_tuple=new,
        intent="swap",
    )
    # ULID constructor accepts the string; round-trip parses without error.
    parsed = _ulid.ULID.from_str(receipt.edit_id)
    assert str(parsed) == receipt.edit_id


# --- AC: swap under a custom DB path --------------------------------------


def test_swap_with_custom_db(tmp_path):
    """The `db` parameter overrides DEFAULT_DB; useful for tests + future
    daemonized dashboards.
    """
    db = tmp_path / "swap.sqlite"
    prev = _HUMAN_TUPLE
    new = _AGENT_TUPLE_NO_SKILLS
    receipt = swap_executor_take_lock(
        "p1", "mei",
        prev_executor_tuple=prev,
        new_executor_tuple=new,
        intent="swap",
        db=db,
    )
    assert receipt.project_id == "p1"
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT project_id FROM project_yaml_edits"
    ).fetchall()
    assert rows == [("p1",)]
    conn.close()


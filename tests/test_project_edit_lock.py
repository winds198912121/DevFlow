"""Tests for harness.project_edit_lock (Story 2.9).

Covers AD-18: project_edit_lock is the sole writer of the
`project_edit_locks` table at var/devflow.sqlite. Acquire is atomic;
release is gated by the holder; TTL expiry allows lock stealing.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from harness.project_edit_lock import (
    DEFAULT_DB,
    LockHeld,
    acquire,
    release,
)


# --- Autouse: clean var/ between tests -----------------------------------


@pytest.fixture(autouse=True)
def _clean_var():
    """Wipe var/devflow.sqlite between tests."""
    if DEFAULT_DB.exists():
        DEFAULT_DB.unlink()
    if DEFAULT_DB.with_suffix(".sqlite-wal").exists():
        DEFAULT_DB.with_suffix(".sqlite-wal").unlink()
    if DEFAULT_DB.with_suffix(".sqlite-shm").exists():
        DEFAULT_DB.with_suffix(".sqlite-shm").unlink()
    yield
    if DEFAULT_DB.exists():
        DEFAULT_DB.unlink()
    for ext in (".sqlite-wal", ".sqlite-shm"):
        p = DEFAULT_DB.with_suffix(ext)
        if p.exists():
            p.unlink()


# --- AC: acquire inserts a row -------------------------------------------


def test_acquire_returns_project_edit_lock():
    lock = acquire("p1", "mei")
    assert lock.project_id == "p1"
    assert lock.acquired_by == "mei"
    assert lock.expires_at > lock.acquired_at


def test_acquire_writes_row_to_sqlite(tmp_path):
    db = tmp_path / "test.sqlite"
    acquire("p1", "mei", db=db)
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT project_id, acquired_by FROM project_edit_locks"
    ).fetchall()
    assert rows == [("p1", "mei")]


# --- AC: live lock blocks concurrent acquire ----------------------------


def test_acquire_when_held_raises_lock_held():
    acquire("p1", "mei")
    with pytest.raises(LockHeld, match="mei"):
        acquire("p1", "ops")


# --- AC: expired lock can be stolen -------------------------------------


def test_acquire_after_ttl_steals_stale_lock():
    """A lock with TTL=1 second expires; a second acquire steals it."""
    acquire("p1", "first", ttl_seconds=1)
    time.sleep(1.1)
    second = acquire("p1", "second", ttl_seconds=300)
    assert second.acquired_by == "second"


# --- AC: release removes the row ---------------------------------------


def test_release_by_holder_removes_row():
    acquire("p1", "mei")
    release("p1", acquired_by="mei")  # returns None silently
    # Second acquire by a different caller succeeds.
    second = acquire("p1", "ops")
    assert second.acquired_by == "ops"


def test_release_by_non_holder_does_not_remove():
    acquire("p1", "mei")
    release("p1", acquired_by="non_holder")  # returns None silently
    # Mei still holds the lock.
    with pytest.raises(LockHeld):
        acquire("p1", "ops")


def test_release_without_holder_is_admin():
    acquire("p1", "mei")
    release("p1")  # admin release — returns None silently
    # Second acquire succeeds.
    second = acquire("p1", "ops")
    assert second.acquired_by == "ops"


def test_release_when_no_lock_is_noop():
    release("p1")  # no-op on missing lock; returns None silently


# --- AC: lock holder is named in LockHeld (AD-18 (e)) --------------------


def test_lock_held_message_names_holder():
    acquire("p1", "mei@team")
    with pytest.raises(LockHeld) as exc_info:
        acquire("p1", "ops")
    assert exc_info.value.holder == "mei@team"
    assert exc_info.value.project_id == "p1"


# --- AC: idempotent acquire on the same (project, holder) within TTL ----


def test_reacquire_same_holder_raises_after_ttl():
    acquire("p1", "mei", ttl_seconds=1)
    # Same holder within TTL — still raises (the lock is held).
    with pytest.raises(LockHeld):
        acquire("p1", "mei", ttl_seconds=1)
    time.sleep(1.1)
    # After TTL — same holder can re-acquire (steals the stale lock).
    lock = acquire("p1", "mei", ttl_seconds=300)
    assert lock.acquired_by == "mei"

"""Tests for harness.cost_ledger (Story 4.1)."""

from __future__ import annotations

import pytest

from harness.cost_ledger import (
    DEFAULT_DB,
    CostLedgerImmutable,
    append,
    read,
    sum_for_project,
    sum_for_run,
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


def test_append_returns_record_and_persists():
    rec = append("p1", run_id="R1", step="coding", tokens_in=100, tokens_out=50)
    assert rec.op_id
    fetched = read(rec.op_id)
    assert fetched is not None
    assert fetched.tokens_in == 100
    assert fetched.tokens_out == 50
    assert fetched.signed_hash.startswith("sha256:")


def test_sum_for_project_returns_total():
    append("p1", run_id="R1", tokens_in=100, tokens_out=50)
    append("p1", run_id="R1", tokens_in=200, tokens_out=100)
    assert sum_for_project("p1") == 450


def test_sum_for_run_filters_by_run():
    append("p1", run_id="R1", tokens_in=100, tokens_out=50)
    append("p1", run_id="R2", tokens_in=1000, tokens_out=500)
    assert sum_for_run("p1", "R1") == 150
    assert sum_for_run("p1", "R2") == 1500


def test_append_idempotent_under_same_ulid_collision_raises_immutable(monkeypatch):
    """Two appends that produce the same ULID: the second raises.

    Uses pytest's `monkeypatch` so `ULID.from_datetime` is restored to the
    real classmethod after the test. A manual save/restore reads the
    already-patched attribute and silently makes the patch permanent,
    which poisons every later ULID in the process (artifact_store,
    acknowledgement_store, ...).
    """
    import harness.cost_ledger as cl
    fixed = cl.ulid.ULID()
    monkeypatch.setattr(cl.ulid.ULID, "from_datetime", lambda dt: fixed)
    append("p1", run_id="R1", tokens_in=10, tokens_out=5)
    with pytest.raises(CostLedgerImmutable):
        append("p1", run_id="R1", tokens_in=20, tokens_out=10)

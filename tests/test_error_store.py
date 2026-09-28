"""Tests for harness.error_store (Story 3.1)."""

from __future__ import annotations

import pytest

from harness.error_store import (
    DEFAULT_DB,
    ErrorRecord,
    ErrorStoreImmutable,
    InvalidErrorCategory,
    append,
    list_for,
    read,
)


@pytest.fixture(autouse=True)
def _clean_db():
    """Wipe var/harness.sqlite between tests."""
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


def _record(**overrides) -> ErrorRecord:
    base = dict(
        record_id="",
        project_id="p1",
        run_id="R1",
        step="coding",
        attempt=1,
        category="coding",
        root_cause=("syntax error",),
        correction=("fix line 42",),
        retry=(),
        result="fail",
        recorded_at="2026-09-28T00:00:00+00:00",
    )
    base.update(overrides)
    return ErrorRecord(**base)


def test_append_returns_ulid_and_persists():
    rec = append(_record())
    assert rec.record_id  # ULID, non-empty
    fetched = read(rec.record_id)
    assert fetched is not None
    assert fetched.project_id == "p1"
    assert fetched.category == "coding"


def test_invalid_category_raises():
    with pytest.raises(InvalidErrorCategory):
        append(_record(category="not_in_enum"))


def test_list_for_filters_by_project_run_step():
    a = append(_record(step="coding"))
    append(_record(step="testing", project_id="p1", run_id="R2"))
    append(_record(step="coding", project_id="p2"))
    listed = list_for("p1", "R1", step="coding")
    assert {r.record_id for r in listed} == {a.record_id}


def test_read_missing_returns_none():
    assert read("NONEXISTENT") is None


def test_same_record_id_appended_twice_raises():
    rec = append(_record())
    with pytest.raises(ErrorStoreImmutable):
        dup_dict = _record().to_dict()
        dup_dict["record_id"] = rec.record_id
        append(ErrorRecord(**dup_dict))


def test_retry_array_round_trips():
    rec = append(_record(retry=({"rung": 1, "result": "fail"},)))
    fetched = read(rec.record_id)
    assert fetched is not None
    assert len(fetched.retry) == 1
    assert fetched.retry[0]["rung"] == 1

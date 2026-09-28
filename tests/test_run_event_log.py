"""Tests for harness.run_event_log (Story 2.10)."""

from __future__ import annotations

import shutil

import pytest

from harness.run_event_log import (
    DEFAULT_DB,
    RunEvent,
    RunEventAlreadyExists,
    generate_event_id,
    list_for_run,
    read,
    write,
)


@pytest.fixture(autouse=True)
def _clean_db():
    """Wipe var/devflow.sqlite between tests."""
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


def _event(
    run_id: str = "R1",
    step: str = "research",
    event_id: str | None = None,
    started_at: str = "2026-09-28T00:00:00+00:00",
) -> RunEvent:
    return RunEvent(
        event_id=event_id or generate_event_id(),
        project_id="p1",
        run_id=run_id,
        step=step,
        executor_tuple="{}",
        executor_tuple_hash="sha256:" + "0" * 64,
        started_at=started_at,
    )


def test_write_returns_event():
    event = _event()
    returned = write(event)
    assert returned.event_id == event.event_id


def test_read_returns_event():
    event = _event()
    write(event)
    read_back = read(event.event_id)
    assert read_back == event


def test_read_missing_returns_none():
    assert read("NONEXISTENT") is None


def test_list_for_run_returns_chronological():
    # Distinct started_at values guarantee the ORDER BY ordering is
    # independent of the ULID's random part.
    a = _event(
        event_id=generate_event_id(), started_at="2026-09-28T00:00:00+00:00"
    )
    b = _event(
        event_id=generate_event_id(),
        step="coding",
        started_at="2026-09-28T00:00:01+00:00",
    )
    c = _event(
        event_id=generate_event_id(),
        step="design",
        started_at="2026-09-28T00:00:02+00:00",
    )
    write(a)
    write(b)
    write(c)
    listed = list_for_run("R1")
    assert [e.event_id for e in listed] == [a.event_id, b.event_id, c.event_id]
    assert [e.step for e in listed] == ["research", "coding", "design"]


def test_duplicate_event_id_raises():
    event = _event(event_id="FIXED01")
    write(event)
    with pytest.raises(RunEventAlreadyExists):
        write(event)


def test_run_event_log_isolated_per_run():
    """Events for different runs are kept separate."""
    write(_event(run_id="R1"))
    write(_event(run_id="R2"))
    assert list_for_run("R1") != ()
    assert list_for_run("R2") != ()
    assert set(list_for_run("R1")).isdisjoint(set(list_for_run("R2")))


"""Tests for harness.herdr_ingest (Story 4.8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.herdr_ingest import (
    DEFAULT_MIRROR,
    DEFAULT_STREAM,
    MalformedHerdrEvent,
    read_mirror_events,
    tail,
)


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path):
    """Wipe var/herdr + var/herdr_mirror.sqlite between tests."""
    if DEFAULT_STREAM.exists():
        DEFAULT_STREAM.unlink()
    if DEFAULT_MIRROR.exists():
        DEFAULT_MIRROR.unlink()
    for ext in (".sqlite-wal", ".sqlite-shm"):
        p = DEFAULT_MIRROR.with_suffix(ext)
        if p.exists():
            p.unlink()
    yield
    if DEFAULT_STREAM.exists():
        DEFAULT_STREAM.unlink()
    if DEFAULT_MIRROR.exists():
        DEFAULT_MIRROR.unlink()
    for ext in (".sqlite-wal", ".sqlite-shm"):
        p = DEFAULT_MIRROR.with_suffix(ext)
        if p.exists():
            p.unlink()


def test_tail_appends_events_to_mirror():
    DEFAULT_STREAM.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_STREAM.write_text(
        '{"event_id": "h1", "project_id": "p1", "step": "coding", '
        '"event_type": "agent_progress", "recorded_at": "2026-09-28T00:00:00+00:00"}\n'
        '{"event_id": "h2", "project_id": "p2", "event_type": "cost_warning", '
        '"recorded_at": "2026-09-28T00:00:01+00:00"}\n',
        encoding="utf-8",
    )
    n = tail()
    assert n == 2
    events = read_mirror_events()
    assert len(events) == 2
    assert {e.event_id for e in events} == {"h1", "h2"}


def test_tail_is_idempotent():
    DEFAULT_STREAM.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_STREAM.write_text(
        '{"event_id": "h1", "event_type": "x", "recorded_at": "2026-09-28T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    assert tail() == 1
    assert tail() == 0  # second call reads from the saved position; nothing new


def test_tail_appends_only_new_lines():
    DEFAULT_STREAM.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_STREAM.write_text(
        '{"event_id": "h1", "event_type": "x", "recorded_at": "2026-09-28T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    tail()
    # Append a second event.
    with DEFAULT_STREAM.open("a", encoding="utf-8") as f:
        f.write(
            '{"event_id": "h2", "event_type": "y", "recorded_at": "2026-09-28T00:00:01+00:00"}\n'
        )
    assert tail() == 1
    assert {e.event_id for e in read_mirror_events()} == {"h1", "h2"}


def test_missing_stream_returns_zero_without_raising():
    """Herdr outage MUST NOT block harness run invocation (AD-9)."""
    assert not DEFAULT_STREAM.exists()
    assert tail() == 0


def test_malformed_event_raises():
    DEFAULT_STREAM.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_STREAM.write_text("not-valid-json\n", encoding="utf-8")
    with pytest.raises(MalformedHerdrEvent):
        tail()


def test_read_mirror_events_filters_by_project():
    DEFAULT_STREAM.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_STREAM.write_text(
        '{"event_id": "h1", "project_id": "p1", "event_type": "x", '
        '"recorded_at": "2026-09-28T00:00:00+00:00"}\n'
        '{"event_id": "h2", "project_id": "p2", "event_type": "y", '
        '"recorded_at": "2026-09-28T00:00:01+00:00"}\n',
        encoding="utf-8",
    )
    tail()
    p1_events = read_mirror_events(project_id="p1")
    assert {e.event_id for e in p1_events} == {"h1"}

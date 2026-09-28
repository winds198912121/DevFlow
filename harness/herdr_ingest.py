"""Herdr Ingest — AD-9 / AD-19 advisory stream tail.

Public surface (Story 4.8):
- `tail(stream_path, *, mirror_db_path) -> int` — appends new events from
  the Herdr stream JSONL file to `var/herdr_mirror.sqlite`. Idempotent
  on file-position (a `mirror_position` table records the byte offset
  consumed so far).
- `MalformedHerdrEvent` exception.
- `read_mirror_events(mirror_db, *, project_id=None, since=None) ->
  tuple[HerdrMirrorEvent, ...]`.

AD-9 + AD-19 binding:
- Herdr events are advisory only; no `row` canonical state derives from
  them (NFR-Privacy-1).
- Herdr outage MUST NOT block harness run invocation (NFR-Reliab-2):
  a missing stream is silently treated as "no new events".
- The mirror schema is closed (no derived fields, no join keys per
  AD-19 (b) + (c)).

The Herdr stream is a JSONL file at `var/herdr/stream.jsonl` by default
(per the spine Stack table). The harness-side ingest is a file-tail;
the Herdr sidecar is out of scope for this story (Epic 3.5 owns the
Herdr daemon).
"""

from __future__ import annotations

import json
import sqlite3

from harness import migrate as _migrate
from dataclasses import dataclass
from pathlib import Path
from typing import Any



PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STREAM = PROJECT_ROOT / "var" / "herdr" / "stream.jsonl"
DEFAULT_MIRROR = PROJECT_ROOT / "var" / "herdr_mirror.sqlite"


class MalformedHerdrEvent(Exception):
    """A line in the Herdr stream is not valid JSON / has the wrong shape."""


@dataclass(frozen=True)
class HerdrMirrorEvent:
    """A single advisory event projected into the read-only mirror."""

    event_id: str  # Herdr's own id (not a ULID)
    project_id: str | None
    step: str | None
    event_type: str
    payload_json: str  # raw JSON string of the event body
    recorded_at: str  # Herdr's recorded_at (NOT a harness timestamp)


def _open_mirror(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    _migrate.ensure_tables(conn, "herdr_mirror_events", "herdr_mirror_position")


def _read_position(conn: sqlite3.Connection, stream_path: Path) -> int:
    row = conn.execute(
        "SELECT byte_offset FROM herdr_mirror_position WHERE stream_path = ?",
        (str(stream_path),),
    ).fetchone()
    return int(row[0]) if row else 0


def _write_position(
    conn: sqlite3.Connection, stream_path: Path, byte_offset: int
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO herdr_mirror_position (stream_path, byte_offset)
        VALUES (?, ?)
        """.strip(),
        (str(stream_path), byte_offset),
    )


def tail(
    stream_path: Path | str = DEFAULT_STREAM,
    *,
    mirror_db: Path | str = DEFAULT_MIRROR,
) -> int:
    """Tail the JSONL Herdr stream; append new events to the mirror.

    Returns the count of new events ingested. A missing stream is
    silently treated as "no new events" (AD-9 + NFR-Reliab-2).
    """
    stream = Path(stream_path)
    db_path = Path(mirror_db)

    if not stream.exists():
        # AD-9 / NFR-Reliab-2: Herdr outage does not block the harness.
        return 0

    conn = _open_mirror(db_path)
    try:
        _ensure_tables(conn)
        last = _read_position(conn, stream)
        ingested = 0
        malformed: MalformedHerdrEvent | None = None
        with stream.open("rb") as fh:
            fh.seek(last)
            while True:
                line_bytes = fh.readline()
                if not line_bytes:
                    break
                try:
                    obj = json.loads(line_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    malformed = MalformedHerdrEvent(
                        f"herdr line at offset {last} malformed: {e}"
                    )
                else:
                    if not isinstance(obj, dict) or "event_id" not in obj:
                        malformed = MalformedHerdrEvent(
                            f"herdr line at offset {last} missing event_id"
                        )
                    else:
                        payload_json = json.dumps(obj, sort_keys=True)
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO herdr_mirror_events (
                                event_id, project_id, step, event_type,
                                payload_json, recorded_at
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """.strip(),
                            (
                                obj["event_id"],
                                obj.get("project_id"),
                                obj.get("step"),
                                obj.get("event_type", "unknown"),
                                payload_json,
                                obj.get("recorded_at", ""),
                            ),
                        )
                        ingested += 1
                # The offset advances past every consumed line, including a
                # rejected one. Advancing only on success meant the position
                # never moved past a malformed line, so every later tail()
                # re-read the same bytes and raised forever — the ingest was
                # permanently stuck behind one bad line, the exact failure
                # Story 4.8's "does not block subsequent events" forbids.
                last += len(line_bytes)
                if malformed is not None:
                    break
            # Commit before surfacing the rejection so the events read before
            # the bad line survive it, and the stored offset matches what was
            # actually consumed.
            _write_position(conn, stream, last)
            conn.commit()
    finally:
        conn.close()
    if malformed is not None:
        raise malformed
    return ingested


def read_mirror_events(
    *,
    mirror_db: Path | str = DEFAULT_MIRROR,
    project_id: str | None = None,
    since: str | None = None,
) -> tuple[HerdrMirrorEvent, ...]:
    db_path = Path(mirror_db)
    if not db_path.exists():
        return ()
    conn = _open_mirror(db_path)
    try:
        _ensure_tables(conn)
        where: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        if since is not None:
            where.append("recorded_at >= ?")
            params.append(since)
        sql = (
            "SELECT event_id, project_id, step, event_type, payload_json, "
            "recorded_at FROM herdr_mirror_events"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY recorded_at ASC"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return tuple(
        HerdrMirrorEvent(
            event_id=r[0], project_id=r[1], step=r[2], event_type=r[3],
            payload_json=r[4], recorded_at=r[5],
        )
        for r in rows
    )


__all__ = [
    "HerdrMirrorEvent",
    "MalformedHerdrEvent",
    "DEFAULT_STREAM",
    "DEFAULT_MIRROR",
    "tail",
    "read_mirror_events",
]
"""Tests for harness.artifact_store — covers the I/O Matrix in the 2.2 plan."""

from __future__ import annotations

import sqlite3

import pytest

from harness import artifact_store
from harness.artifact_store import (
    ArtifactCorrupt,
    ArtifactCorrupted,
    ArtifactNotFound,
    is_locked,
    lock,
    put_pending,
    read,
)
from harness.migrate import open_default_db, run_migrations


@pytest.fixture
def db():
    """Fresh in-memory DB with migration #2 applied."""
    db = sqlite3.connect(":memory:")
    run_migrations(db)
    return db


# --- AC 1: put_pending + lock returns sha256 prefix ---------------------


def test_put_pending_and_lock_returns_sha256_prefix(db):
    aid = put_pending(db, b"hello")
    out = lock(db, aid)
    assert out.startswith("sha256:")
    assert len(out.split(":", 1)[1]) == 64


# --- AC 2: idempotent lock -----------------------------------------------


def test_lock_is_idempotent(db):
    aid = put_pending(db, b"hello")
    h1 = lock(db, aid)
    h2 = lock(db, aid)
    assert h1 == h2


# --- AC 3: read returns locked payload -----------------------------------


def test_read_returns_locked_payload(db):
    aid = put_pending(db, b"hello world")
    h = lock(db, aid)
    assert read(db, h) == b"hello world"


# --- AC 4: tampered payload raises ArtifactCorrupt -----------------------


def test_read_raises_artifact_corrupt_on_payload_tamper(db):
    aid = put_pending(db, b"hello")
    h = lock(db, aid)
    # Simulate a disk-level bit-flip or hand-edit by updating the payload column.
    db.execute("UPDATE artifacts SET payload = ? WHERE id = ?", (b"tampered", aid))
    db.commit()
    with pytest.raises(ArtifactCorrupt):
        read(db, h)


# --- AC 5: tampered signature raises ArtifactCorrupted ------------------


def test_read_raises_artifact_corrupted_on_signature_tamper(db):
    aid = put_pending(db, b"hello")
    h = lock(db, aid)
    # Flip a single byte in the signature column.
    db.execute(
        "UPDATE artifacts SET signature = ? WHERE id = ?",
        (b"\x00" * 64, aid),
    )
    db.commit()
    with pytest.raises(ArtifactCorrupted):
        read(db, h)


# --- AC 6: canonical-bytes key ordering -----------------------------------


def test_canonical_bytes_key_ordering_produces_same_hash(db):
    # The artifact store stores BLOB payloads; SQLite does not support
    # binding a dict directly. We canonicalize the dicts to bytes via
    # harness.canonical.canonical_bytes (which sorts dict keys) and store
    # those bytes. The locked hash should match because the two dicts
    # canonicalize to the same bytes.
    from harness.canonical import canonical_bytes
    payload = canonical_bytes({"b": 1, "a": 2})
    aid_a = put_pending(db, payload)
    aid_b = put_pending(db, canonical_bytes({"a": 2, "b": 1}))
    h_a = lock(db, aid_a)
    h_b = lock(db, aid_b)
    assert h_a == h_b
    # And the stored bytes are the canonical form (sorted keys).
    assert read(db, h_a) == payload


# --- AC 7: read unknown hash raises ArtifactNotFound ---------------------


def test_read_unknown_hash_raises_not_found(db):
    with pytest.raises(ArtifactNotFound):
        read(db, "sha256:0000000000000000000000000000000000000000000000000000000000000000")


# --- AC 8: empty payload known-answer hash ------------------------------


def test_empty_payload_known_answer_hash(db):
    aid = put_pending(db, b"")
    h = lock(db, aid)
    assert h == "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert read(db, h) == b""


# --- AC 9: pending artifact not addressable by hash ----------------------


def test_pending_artifact_not_addressable_by_hash(db):
    put_pending(db, b"hello")
    # No lock was called, so no locked row with any hash exists.
    with pytest.raises(ArtifactNotFound):
        read(db, "sha256:0000000000000000000000000000000000000000000000000000000000000000")


# --- Bonus coverage: is_locked + open_default_db -----------------------------


def test_is_locked_returns_true_after_lock_false_before(db):
    aid = put_pending(db, b"hello")
    assert not is_locked(db, "sha256:0000000000000000000000000000000000000000000000000000000000000000")
    h = lock(db, aid)
    assert is_locked(db, h)


def test_open_default_db_then_run_migrations_creates_artifacts_table():
    # open_default_db does NOT auto-run migrations (separation of connection
    # lifecycle from migration lifecycle, per Story 2.1). The caller runs
    # run_migrations explicitly after open.
    import tempfile, os
    from harness.migrate import run_migrations
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "harness.sqlite")
        db = open_default_db(db_path)
        try:
            # Before migrations: artifacts table does not exist.
            row = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'"
            ).fetchone()
            assert row is None
            # After migrations: artifacts table exists.
            run_migrations(db)
            row = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'"
            ).fetchone()
            assert row is not None
        finally:
            db.close()


def test_lock_tampered_payload_after_lock_raises_artifact_corrupt(db):
    # Same as AC 4 but at lock time (post-lock tamper detected on re-lock).
    aid = put_pending(db, b"original")
    lock(db, aid)
    db.execute("UPDATE artifacts SET payload = ? WHERE id = ?", (b"tampered", aid))
    db.commit()
    with pytest.raises(ArtifactCorrupt):
        lock(db, aid)


def test_lock_artifact_not_found_raises():
    db = sqlite3.connect(":memory:")
    run_migrations(db)
    with pytest.raises(ArtifactNotFound):
        lock(db, "non-existent-id")

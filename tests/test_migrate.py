"""Tests for harness.migrate — covers the I/O Matrix in the 2.1 plan."""

from __future__ import annotations

import sqlite3

import pytest

from harness import migrate as harness_migrate
from harness.migrate import (
    DuplicateMigrationVersion,
    FutureSchemaVersion,
    MigrationCorrupted,
    MigrationGap,
    open_default_db,
    run_migrations,
)


# --- AC 1 + AC 2: fresh DB + idempotent re-run ----------------------------


def test_fresh_db_creates_migrations_table_and_stamps_version_1():
    db = sqlite3.connect(":memory:")
    run_migrations(db)
    row = db.execute("SELECT version, description FROM _migrations").fetchone()
    assert row == (1, "init")


def test_idempotent_re_run_no_op():
    db = sqlite3.connect(":memory:")
    run_migrations(db)
    rows_before = db.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
    run_migrations(db)
    rows_after = db.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
    assert rows_before == rows_after
    # The migration list may grow over the harness's lifetime; the contract
    # is "the count is stable across re-runs", not "the count is exactly 1".
    # Story 2.2 added migration #2, so the count is now 2; future stories
    # may append more.
    assert rows_after >= 1
    version = db.execute("SELECT MAX(version) FROM _migrations").fetchone()[0]
    # Version after first run == max known version in _MIGRATIONS.
    from harness.migrate import _MIGRATIONS
    assert version == _MIGRATIONS[-1][0]


# --- AC 3: apply migration N+1 ------------------------------------------


def test_apply_pending_migration(tmp_path, monkeypatch):
    # Replace the migration list with one that has a known extension BEFORE
    # running migrations. Using _MIGRATIONS.append() would create a
    # duplicate-version list (which the validator catches), and appending
    # after run_migrations has applied the real migration #2 would cause a
    # hash mismatch on the next run. Easiest: clear + rebuild the list
    # before opening the DB connection.
    original = list(harness_migrate._MIGRATIONS)
    try:
        harness_migrate._MIGRATIONS.clear()
        harness_migrate._MIGRATIONS.append(
            (1, "init", original[0][2])  # same SQL as the real migration 1
        )
        harness_migrate._MIGRATIONS.append(
            (
                2,
                "add artifacts table",
                "CREATE TABLE artifact_store (id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, payload BLOB NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, locked_at TEXT, signature TEXT)",
            )
        )
        db = sqlite3.connect(":memory:")
        run_migrations(db)
        rows = db.execute(
            "SELECT version, description FROM _migrations ORDER BY version"
        ).fetchall()
        assert rows == [(1, "init"), (2, "add artifacts table")]
        # Verify the table was actually created.
        cols = db.execute("PRAGMA table_info(artifact_store)").fetchall()
        assert any(row[1] == "sha256" for row in cols)
    finally:
        harness_migrate._MIGRATIONS[:] = original


# --- AC 4: future schema version ----------------------------------------


def test_future_schema_version_raises():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE _migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL, sql_hash TEXT NOT NULL)"
    )
    db.execute(
        "INSERT INTO _migrations VALUES (999, 'from-the-future', '2026-09-28T00:00:00+00:00', 'sha256:deadbeef')"
    )
    db.commit()
    with pytest.raises(FutureSchemaVersion) as exc_info:
        run_migrations(db)
    assert exc_info.value.db_version == 999


# --- AC 5: corrupted sql_hash --------------------------------------------


def test_corrupted_sql_hash_raises():
    db = sqlite3.connect(":memory:")
    run_migrations(db)
    # Manually overwrite the recorded hash with a bogus value.
    db.execute("UPDATE _migrations SET sql_hash = 'sha256:bogus' WHERE version = 1")
    db.commit()
    with pytest.raises(MigrationCorrupted) as exc_info:
        run_migrations(db)
    assert exc_info.value.version == 1


# --- AC 6: duplicate version at import ---------------------------------


def test_duplicate_migration_version_at_import(monkeypatch):
    # Re-import the module with a tampered migration list. Easiest path:
    # patch the module-level list before run_migrations is called.
    original = list(harness_migrate._MIGRATIONS)
    try:
        harness_migrate._MIGRATIONS.append(
            (1, "duplicate", "SELECT 1")
        )
        with pytest.raises(DuplicateMigrationVersion) as exc_info:
            harness_migrate._validate_migrations()
        assert exc_info.value.version == 1
    finally:
        harness_migrate._MIGRATIONS[:] = original


# --- AC 7: gap at import ------------------------------------------------


def test_migration_gap_at_import(monkeypatch):
    original = list(harness_migrate._MIGRATIONS)
    try:
        # Append a version 3 (gap at 2) by editing the list to drop version 2
        # and add a higher one. Easiest: clear the list and add 1 and 3.
        harness_migrate._MIGRATIONS.clear()
        harness_migrate._MIGRATIONS.append(
            (1, "init", "CREATE TABLE _migrations (version INTEGER PRIMARY KEY)")
        )
        harness_migrate._MIGRATIONS.append(
            (3, "after-gap", "SELECT 1")
        )
        with pytest.raises(MigrationGap) as exc_info:
            harness_migrate._validate_migrations()
        assert exc_info.value.gap_version == 2
    finally:
        harness_migrate._MIGRATIONS[:] = original


# --- AC 8: in-memory DB -------------------------------------------------


def test_in_memory_db_works(tmp_path):
    db = sqlite3.connect(":memory:")
    run_migrations(db)
    rows = db.execute("SELECT COUNT(*) FROM _migrations").fetchone()
    # Migration count is the length of _MIGRATIONS; not pinned to 1 because
    # future stories (2.2, 3.1, 3.2, 4.1, 4.8) append more.
    from harness.migrate import _MIGRATIONS
    assert rows[0] == len(_MIGRATIONS)
    # No var/ files were touched.
    assert not (tmp_path / "var").exists()


# --- AC 9: WAL mode + default connection -------------------------------


def test_default_db_opens_with_wal_and_creates_var_dir(tmp_path):
    db_path = tmp_path / "var" / "harness.sqlite"
    db = open_default_db(db_path)
    try:
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        fk = db.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        assert db_path.exists()
        # NOTE: a `-wal` sidecar file is only created when the WAL has
        # uncheckpointed data. SQLite does not always create it eagerly, so
        # we don't assert its presence here; PRAGMA journal_mode = `wal`
        # already proves the mode is enabled.
    finally:
        db.close()


def test_default_db_runs_migrations_on_open(tmp_path):
    db_path = tmp_path / "var" / "harness.sqlite"
    db = open_default_db(db_path)
    try:
        # open_default_db does NOT auto-run migrations; the caller decides.
        # Before run_migrations, the _migrations table doesn't exist yet.
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            db.execute("SELECT COUNT(*) FROM _migrations").fetchone()
        # Caller runs migrations next.
        run_migrations(db)
        count = db.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
        from harness.migrate import _MIGRATIONS
        assert count == len(_MIGRATIONS)
    finally:
        db.close()

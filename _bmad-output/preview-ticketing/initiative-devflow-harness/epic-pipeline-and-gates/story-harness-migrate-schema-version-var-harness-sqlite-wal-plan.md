---
title: 'harness.migrate + schema_version + var/harness.sqlite (WAL)'
type: 'feature'
ticket: '9'
created: '2026-09-28'
status: 'built'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
baseline_revision: '8eec015'
route: 'full'
route_source: 'auto'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context:
  - '_bmad-output/specs/spec-devflow/SPEC.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every Epic 2 / Epic 3 / Epic 4 story that writes to the canonical stores (artifact_store in 2.2, error_store / event_log in 3.1/3.2, cost_ledger in 4.1, run_events in 2.7) needs a way to evolve the SQLite schema over the lifetime of the harness without breaking existing installs. Story 1.1 planted `var/` as the runtime artifact directory; Story 1.4 added the layer-boundary lint that requires `var/<layer>/` to exist as a deploy-marker; this story plants the SQLite file + a migration framework so future stories can add tables via numbered migrations without losing existing data.

**Approach:** New module `harness/migrate.py` exporting `run_migrations(db: sqlite3.Connection) -> None`. The migration runner reads `schema_version` from a single `_migrations` table; if the row's version is greater than what this harness knows about, raise `FutureSchemaVersion` (the operator must upgrade the harness or restore a backup). The runner then applies any pending migrations in order, each migration being a `(version, description, sql)` tuple. The initial migration stamps `schema_version=1` with no other tables. Future stories (2.2 / 3.1 / 3.2 / 4.1) add their own migrations via `_MIGRATIONS.append((2, "add artifact_store", "..."))` etc. — the same runner picks them up.

## Boundaries & Constraints

**Always:**
- The migration runner is idempotent: running twice produces no change on the second run.
- The runner refuses to migrate down (FutureSchemaVersion if `schema_version` > max known version).
- The runner is connection-scoped (takes `sqlite3.Connection`, doesn't manage connection lifecycle) so tests can use `:memory:`.
- `var/harness.sqlite` is the canonical store path. WAL mode is enabled on connection; foreign keys are enforced (`PRAGMA foreign_keys = ON`).
- Migrations are `(version, description, sql)` tuples in a list. Version is `int` (positive, monotonically increasing). Description is human-readable (logged on apply). SQL is `str` (executed as a single statement — multi-statement migrations are split into multiple tuples).
- The `_migrations` table has `(version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL, sql_hash TEXT NOT NULL)` — `sql_hash` is the canonical sha256 of the migration SQL, computed via `harness.canonical.canonical_sha256` (AD-17 sole sha256 path).
- Every migration insert also writes a run event to the canonical run_event_log (AD-14) once that table exists; until then (schema_version 1), the runner only writes to `_migrations`.

**Never:**
- Drop or modify a migration that has already been applied (AD-4: append-only ledger).
- Apply a migration outside the current `schema_version + 1..N` range.
- Allow two migrations with the same version number.
- Allow a migration's SQL to differ from what `sql_hash` records (idempotency check).
- Use SQLite's built-in migration tracking (`PRAGMA user_version`) — `harness.migrate` owns its `_migrations` table to keep the harness's migration metadata in a single canonical place.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (first run, fresh DB) | `var/harness.sqlite` does not exist; `db` connection passed in | Creates the `_migrations` table; stamps `schema_version=1` with the initial migration's row; returns None | No error |
| Happy path (idempotent re-run) | DB exists with `schema_version=1` | `_migrations` row already present; runner sees no pending migrations; returns None | No error |
| Happy path (apply migration N+1) | DB has `schema_version=2`; runner has migrations 1..3 | Applies migration 3, stamps `schema_version=3`; returns None | No error |
| Error (future schema version) | DB has `schema_version=999`; runner knows migrations 1..3 | Raises `FutureSchemaVersion(999, 3)` | Propagates; caller sees the error |
| Error (corrupt sql_hash) | DB has `schema_version=2` with `sql_hash=X`; migration 2's SQL hashes to `Y != X` | Raises `MigrationCorrupted(2, X, Y)` | Propagates; operator must restore from backup or hand-edit |
| Error (duplicate version in migrations list) | Two tuples both with `version=2` | Raises `DuplicateMigrationVersion(2)` at module-import time | Propagates at startup |
| Error (gap in version sequence) | Migrations list contains versions 1, 2, 4 (gap at 3) | Raises `MigrationGap(3)` at module-import time | Propagates at startup |
| Edge (WAL mode already on) | DB connection already has WAL enabled | Runner leaves WAL as-is (idempotent PRAGMA) | No error |
| Edge (in-memory DB) | `db = sqlite3.connect(":memory:")` | Runner applies migrations to the in-memory DB; no var/ file written | No error |

</frozen-after-approval>

## Code Map

- `harness/migrate.py` (new) — `FutureSchemaVersion`, `MigrationCorrupted`, `DuplicateMigrationVersion`, `MigrationGap` exceptions; `_MIGRATIONS` list (initial entry: `(1, "init", "CREATE TABLE _migrations (...)")`); `run_migrations(db)` runner; `_apply_migration(db, version, description, sql)` helper; `_compute_sql_hash(sql)` helper that calls `harness.canonical.canonical_sha256`.
- `tests/test_migrate.py` (new) — covers the I/O Matrix rows: fresh DB / idempotent re-run / apply migration N+1 / future schema version / corrupt sql_hash / duplicate version / gap in sequence / in-memory DB. ~9 tests.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) — Glossary term `Skill Bump Registry` references "exactly two writers"; the `_migrations` table here is a third "writer" (the migration runner), so this story adds a documented exception: the migration runner is the sole writer to `_migrations` and no other code path may touch it.
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) — AD-4 ("Append-Only Immutable Log") applies to the `_migrations` table; AD-17 ("Canonical Serialization Is a Single Library Function") applies to `sql_hash`.

## Tasks & Acceptance

**Execution:**
- [ ] `harness/migrate.py` -- exception types + `_MIGRATIONS` list with the initial migration + `run_migrations` runner -- the migration framework.
- [ ] `tests/test_migrate.py` -- 9 tests covering the I/O Matrix rows.
- [ ] First-run integration: open `var/harness.sqlite` (creating `var/` if missing), run migrations, verify `schema_version=1` row exists, verify the file has the `WAL` mode header set.

**Acceptance Criteria:**
- Given a fresh `var/` directory, when `run_migrations(db)` is called against a connection to `var/harness.sqlite`, then the `_migrations` table exists with one row at `schema_version=1` and the row's `description` is "init".
- Given the same DB, when `run_migrations` is called a second time, then no SQL is executed (no new row inserted, `schema_version` still 1).
- Given a DB with `schema_version=1`, when a second migration is appended to `_MIGRATIONS` and `run_migrations` is called, then the second migration runs and `schema_version` becomes 2.
- Given a DB with `schema_version=999`, when `run_migrations` is called, then `FutureSchemaVersion(999, <max_known>)` is raised.
- Given a DB with `schema_version=1` and a manually-corrupted `sql_hash` on row 1, when `run_migrations` is called, then `MigrationCorrupted(1, ...)` is raised.
- Given the `_MIGRATIONS` list contains two entries with the same version, when the module is imported, then `DuplicateMigrationVersion(<v>)` is raised.
- Given the `_MIGRATIONS` list contains versions 1, 2, 4 (gap at 3), when the module is imported, then `MigrationGap(3)` is raised.
- Given `:memory:` SQLite DB, when migrations are run, then the in-memory DB has the `_migrations` table populated with the initial row.
- Given `var/harness.sqlite` opened with the runner's standard connect helper, when `PRAGMA journal_mode` is queried, then the value is `wal`.

## Implementation Notes

- Decision (2026-09-28): The initial migration's SQL uses `CREATE TABLE IF NOT EXISTS _migrations (...).` First implementation omitted the `IF NOT EXISTS` clause, which caused a `table _migrations already exists` error on second invocation when `_ensure_migrations_table` ran first (creating the table) and then `_MIGRATIONS[0]`'s CREATE TABLE ran again. Adding `IF NOT EXISTS` makes the migration idempotent at the SQL level too.
- Decision (2026-09-28): `open_default_db` now calls `db.commit()` after the PRAGMAs so the WAL sidecar file (`-wal`) is created eagerly on first open rather than waiting for the first real write. The test originally asserted the `-wal` file exists, but SQLite on macOS does not always create it eagerly even with WAL enabled — the `PRAGMA journal_mode = wal` response is the canonical signal. Test updated to assert journal_mode only.
- Decision (2026-09-28): `run_migrations` now checks `MigrationCorrupted` BEFORE `FutureSchemaVersion`. If a DB is at schema_version=3 with a corrupted v1 row, the operator needs the corruption report (more actionable — fix the row or restore from backup) before the future-schema report ("upgrade the harness"). The order swap is operationally important: corruptions are local to this harness version, future-schema requires upgrading. Local-first ordering surfaces the simpler fix first.
- Decision (2026-09-28): `open_default_db` does NOT auto-run migrations. The caller (Epic 2/3/4 stories, the dashboard backend, the check-baseline hook) explicitly calls `run_migrations(db)` after opening. This separates connection lifecycle from migration lifecycle; tests can use `:memory:` DBs without a var/ file ever being touched.
- Surprise (2026-09-28): Test `test_default_db_opens_with_wal_and_creates_var_dir` originally asserted the `-wal` sidecar file exists. SQLite on macOS does not always create it eagerly — the sidecar appears only when there's uncheckpointed WAL data. Test updated to assert `PRAGMA journal_mode = 'wal'` (the canonical signal) instead of the file's existence.
- Surprise (2026-09-28): Test `test_default_db_runs_migrations_on_open` expected `_migrations` table to exist after `open_default_db`, but `open_default_db` does not auto-run migrations. Test fixed: the assertion before run_migrations now expects `OperationalError: no such table`; after run_migrations, count is 1.
- Files touched: `harness/migrate.py` (new, ~210 lines), `tests/test_migrate.py` (new, 10 tests), `.gitignore` (excludes runtime sqlite artifacts).

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 0 medium / 1 low (patched) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/migrate.py:run_migrations` | The original code raised `FutureSchemaVersion` before checking `MigrationCorrupted`. If a DB is at schema_version=3 with a corrupted v1 row, the operator gets the future-schema report and is told to upgrade — but the actionable fix is the local corruption. | low | Operational sequencing issue; both errors are surfaced eventually but in the wrong order | **patched**: reordered so corruption check runs before future-schema check |

Other findings reviewed and rejected:
- `MigrationCorrupted` raise doesn't roll back the DB — for v1 with one migration this is moot; for multi-migration harness versions, a partial-failure recovery is a follow-on.
- `open_default_db` doesn't auto-run migrations — by design (separation of connection lifecycle from migration lifecycle); tests cover both states.
- WAL sidecar file assertion in the original test was wrong — SQLite doesn't always create it eagerly on macOS; replaced with `PRAGMA journal_mode = 'wal'` (the canonical signal).
- `_current_version` uses `COALESCE(MAX(version), 0)` — robust to the empty-table case via COALESCE; no NULL handling needed.

Verification after patches: `uv run pytest` → 82 passed (10 new); `uv run python -m harness check-baseline` → exit 0 with byte-identical summary; `uv run python tools/check_layer_boundaries.py` and `uv run python tools/check_dashboard_writes.py` → exit 0; first-run integration: `open_default_db()` creates `var/harness.sqlite`, WAL mode enabled, FK enforced, migrations applied, `_migrations` table has row `(1, 'init')`.

## Design Notes

The migration runner is connection-scoped (takes `sqlite3.Connection`) rather than path-scoped (takes `Path`). This is a deliberate choice: tests can pass `:memory:` connections without touching the filesystem, and Epic 4's dashboard backend can use a single shared connection pool without the runner having to know about pool lifecycle. The `_open_default_db() -> sqlite3.Connection` helper (provided in this story) opens `var/harness.sqlite` with the standard pragmas (WAL, foreign_keys, busy_timeout) for callers that don't have their own connection.

The migration runner enforces sql_hash integrity on every re-run, not just on first apply. This catches the case where an operator (or a buggy installer) edits `var/harness.sqlite` directly with sqlite3 CLI tools and changes a migration's recorded SQL. The check runs in O(N) over applied migrations on each runner invocation — acceptable for a v1 single-node harness where the migration count is bounded by the number of stories that add tables.

The `_MIGRATIONS` list is module-level (a Python `list` at the top of `harness/migrate.py`). Future stories append their migrations at module-import time by editing this file. The list is validated at module import (duplicate-version check + gap check) so a misconfigured harness fails fast at startup, not at first DB access.

The `_migrations` table's `sql_hash` column makes the migration ledger verifiable. Without it, a future story could accidentally change a migration's SQL between versions and the harness would silently re-apply it (or fail to apply it). With `sql_hash`, the runner detects the drift and raises `MigrationCorrupted`.

The runner is connection-scoped AND module-singleton: the `_MIGRATIONS` list is global, but `run_migrations` is a function that takes any connection. This matches the spine's "sole writer" pattern (AD-22) for the Skill Bump Registry — the migration runner is the sole writer to `_migrations`.

The `applied_at` column uses `datetime.now(timezone.utc).isoformat()` (UTC ISO 8601). The harness never uses local timestamps (per the canonical-bytes time-zone stance in AD-22's rationale).

## Verification

**Commands:**
- `uv run python -c "from harness.migrate import run_migrations; import sqlite3; db = sqlite3.connect('var/harness.sqlite'); run_migrations(db); print(db.execute('PRAGMA journal_mode').fetchone()[0])"` -- expected: prints `wal`; exit 0.
- `uv run python -c "import sqlite3; db = sqlite3.connect('var/harness.sqlite'); print(db.execute('SELECT version, description FROM _migrations').fetchall())"` -- expected: prints `[(1, 'init')]`; exit 0.
- `uv run pytest tests/test_migrate.py -v` -- expected: exit 0, 9 passed.
- `uv run pytest` -- expected: exit 0, 81 passed (72 + 9 new).
- `uv run python -m harness check-baseline` -- expected: exit 0; the baseline summary line is unchanged (this story doesn't add a check; it adds a storage primitive that future stories consume).

**Manual checks (if no CLI):**
- Verify `harness/migrate.py` is the only writer to `_migrations` (no other module imports `sqlite3` and writes to it).
- Verify `var/harness.sqlite` has a `-wal` sidecar file after the first run (WAL mode).
- Verify `PRAGMA foreign_keys = ON` returns 1 on the connection.

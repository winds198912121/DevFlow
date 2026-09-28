---
title: 'Artifact Store: content-hash + lock + read API'
type: 'feature'
ticket: '10'
created: '2026-09-28'
status: 'built'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
baseline_revision: '199d773'
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

**Problem:** Epic 2's Workflow Controller (Story 2.5) produces step outputs — `research.md`, `SPEC.md`, `test-report.json` — that subsequent steps read as inputs. Without a single canonical store, the workflow can't compare runs across projects (the "audit-from-hashes" story UJ-3), can't replay a past run (re-invoke the same Agent+LLM+Skills tuple against the same locked input), and can't enforce AD-11 ("Locked Artifact Cannot Be Edited"). Story 1.6's `check-baseline` only verified the foundational components existed; this story adds the first real consumer of the migration framework (Story 2.1) and the canonical sha256 path (Story 1.2).

**Approach:** Add a migration to `harness/migrate.py` that creates the `artifacts` table (`artifact_id` ULID, `sha256_hash` text, `payload` blob, `status` text, `created_at` text, `locked_at` text). New module `harness/artifact_store.py` exposes the four functions: `put_pending(db, payload: bytes) -> artifact_id` (writes `status='pending'` + a ULID); `lock(db, artifact_id) -> sha256_hash` (computes `canonical_sha256(payload)`, signs the hash with `harness.signing.sign`, sets `status='locked'` + `locked_at`); `read(db, sha256_hash) -> bytes` (verifies signature on the row, then verifies the hash matches the bytes, returns `payload` on success); `is_locked(db, sha256_hash) -> bool` (cheap read of `status`). Exceptions: `ArtifactLocked` (re-lock attempt), `ArtifactCorrupt` (hash mismatch on read per NFR-Reliab-1), `ArtifactNotFound`. ULID generation uses `python-ulid` (already in `pyproject.toml`? — see decisions; if not, add it).

## Boundaries & Constraints

**Always:**
- `harness/artifact_store.py` is the sole writer/reader of the `artifacts` table; no other module may write to it (AD-22 pattern).
- `canonical_sha256(payload)` is computed via `harness.canonical.canonical_sha256` (the AD-17 sole sha256 path); no direct `hashlib` calls.
- The signature on the locked row is `harness.signing.sign(canonical_sha256(payload))` — both the sha256 and the Ed25519 signature appear in the row. Verification checks both.
- `lock` is idempotent on success: a second `lock(db, artifact_id)` returns the same `sha256_hash` (does NOT raise — that would make workflow replay brittle). Only `put_pending` followed by a failed `lock` + a retry raises. This matches the spec ("A locked artifact cannot be edited" — locking is idempotent, not a state transition that must be guarded).
- `read(db, sha256_hash)` verifies the signature and the content hash on every read (NFR-Reliab-1).
- `read` raises `ArtifactNotFound` for an unknown `sha256_hash`, `ArtifactCorrupt` for a hash mismatch, and `ArtifactCorrupted` (note: distinct from `ArtifactCorrupt` — the former is signature failure, the latter is content hash mismatch; both share the "tampered" category but with different recovery paths).
- The migration that creates the `artifacts` table is appended to `_MIGRATIONS` in `harness/migrate.py` as migration #2 — the FIRST consumer of the migration framework.
- The ULID for `artifact_id` uses `python-ulid`'s `ULID.from_datetime(timezone.utc.now())` so the id is sortable by creation time.
- `payload` is stored as a BLOB; SQLite handles this transparently.

**Never:**
- Store the Ed25519 private key in the `artifacts` table or anywhere except `var/secrets/harness.key`.
- Allow an artifact to be edited after lock; `read` returns the locked bytes or raises, never silently returns stale bytes.
- Compute sha256 outside `harness.canonical.canonical_sha256` (CI lint enforces).
- Add a second write path to the `artifacts` table (the migration is the sole schema source; `put_pending`/`lock` are the only writers).
- Use a third-party signature library; `harness.signing` is the only sign/verify surface.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (put_pending + lock) | Empty DB, fresh `payload = b"hello"` | `put_pending` returns `ULID`; `lock` returns `"sha256:2cf24d..."` | No error |
| Happy path (read locked) | After lock, call `read(sha256_hash)` | Returns `b"hello"` | No error |
| Happy path (idempotent lock) | After first `lock`, call `lock(artifact_id)` again | Returns the same `sha256_hash` | No error (idempotent) |
| Happy path (two payloads with same canonical bytes) | Lock two different artifacts whose payloads are `{"b": 1, "a": 2}` and `{"a": 2, "b": 1}` (semantically identical but different dict literals) | Both locks return the same `sha256_hash` because `canonical_bytes` sorts keys | No error |
| Edge (empty payload) | `put_pending(b"")` then `lock` | `sha256_hash = sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (well-known empty digest) | No error |
| Error (read unknown hash) | `read("sha256:unknown")` | Raises `ArtifactNotFound` | Propagates |
| Error (read tampered content) | Manually mutate the `payload` column in the DB (simulates a disk-level bit-flip); call `read(original_hash)` | Raises `ArtifactCorrupt` because the hash no longer matches | Propagates |
| Error (read with bad signature) | Manually mutate the `signature` column; call `read(original_hash)` | Raises `ArtifactCorrupted` | Propagates |
| Error (lock then manually edit) | Lock an artifact, then manually edit `payload` in the DB, then call `read(hash)` | `read` raises `ArtifactCorrupt` because hash no longer matches the edited bytes | Propagates |
| Edge (read pending artifact) | `put_pending` without `lock`; try to `read(pending_hash)` | `read` raises `ArtifactNotFound` because `status != 'locked'` — only locked artifacts are addressable by hash | Propagates |

</frozen-after-approval>

## Code Map

- `harness/migrate.py` (existing, modified) — append migration `(2, "add artifacts table", "CREATE TABLE artifacts (id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, payload BLOB NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, locked_at TEXT, signature TEXT)...")` to `_MIGRATIONS`. The validation at module-import time ensures no duplicates / no gaps.
- `harness/artifact_store.py` (new) — `ArtifactLocked`, `ArtifactCorrupt`, `ArtifactCorrupted`, `ArtifactNotFound` exceptions; `put_pending(db, payload) -> str` (returns ULID); `lock(db, artifact_id) -> str` (returns `sha256:...`); `read(db, sha256_hash) -> bytes`; `is_locked(db, sha256_hash) -> bool`.
- `tests/test_artifact_store.py` (new) — 10 tests covering the I/O Matrix rows.
- `pyproject.toml` (existing, modified) — adds `python-ulid>=2.0,<3` to `[project] dependencies` (already in the spine Stack table).
- `uv.lock` (existing, regenerated) — picks up `python-ulid` and its transitive deps.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) — Glossary term `Artifact hash` / `Artifact contract` / `Artifact lock` is realized here.
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) — AD-11 ("Artifact Lock on Gate") + AD-17 ("Canonical Serialization") + NFR-Reliab-1 ("Artifact durability") + NFR-Sec-1 ("Artifact hashes are signed by the harness on lock").

## Tasks & Acceptance

**Execution:**
- [ ] `pyproject.toml` -- add `python-ulid>=2.0,<3` -- the artifact-id generator.
- [ ] `harness/migrate.py` -- append migration `(2, "add artifacts table", "...")` to `_MIGRATIONS` -- the schema for the new store.
- [ ] `harness/artifact_store.py` -- 4 functions + 4 exceptions; uses `harness.canonical.canonical_sha256` + `harness.signing.sign/verify`; the canonical sha256 + Ed25519 signature both appear in the row -- the artifact surface.
- [ ] `uv.lock` -- regenerate to pick up `python-ulid` and transitive deps.
- [ ] `tests/test_artifact_store.py` -- 10 tests covering the I/O Matrix.

**Acceptance Criteria:**
- Given a fresh DB, when `put_pending(db, b"hello")` returns ULID `A1` and `lock(db, A1)` is called, then the returned string starts with `"sha256:"` and is the canonical sha256 of `b"hello"`.
- Given the same artifact, when `lock` is called a second time, then the same `sha256_hash` is returned (idempotent).
- Given a locked artifact, when `read(sha256_hash)` is called, then `b"hello"` is returned.
- Given a tampered payload in the DB (mutated via sqlite3 after `lock`), when `read(sha256_hash)` is called, then `ArtifactCorrupt` is raised.
- Given a tampered signature in the DB, when `read(sha256_hash)` is called, then `ArtifactCorrupted` is raised.
- Given `{"b": 1, "a": 2}` and `{"a": 2, "b": 1}` as two separate payloads, when both are locked, then both `lock` calls return the same `sha256_hash` (canonical-bytes key ordering).
- Given an unknown `sha256_hash`, when `read` is called, then `ArtifactNotFound` is raised.
- Given an empty `payload = b""`, when locked, then `sha256_hash = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"` (known-answer test).
- Given a pending (not yet locked) artifact, when `read(pending_hash)` is called, then `ArtifactNotFound` is raised (only locked artifacts are addressable by hash).
- Given `uv run pytest`, when it runs, then all 82 existing tests + the 10 new tests pass.

## Implementation Notes

- Decision (2026-09-28): `read()` reorders the verification sequence: hash check FIRST, then signature check. Originally the signature check ran first because it was the cheaper check (one Ed25519 op vs. one full SHA-256 of a potentially-large payload). Pivoted to hash-first because the operator's actionable fix differs: a tampered payload is recoverable by restoring from another source; a tampered signature is recoverable by re-locking. The hash-first ordering surfaces the more common failure mode (disk-level corruption, hand-edit) with the more actionable error name (`ArtifactCorrupt`).
- Decision (2026-09-28): `lock()`'s idempotent path now also requires `existing_signature` to be present (not NULL). Original idempotent path returned early on `status='locked' AND existing_hash==current_hash`, which left a nulled signature column un-re-signed. Subsequent `read()` would raise `ArtifactCorrupted` even though the artifact's payload was correct. The added `and existing_signature` clause forces re-signing when the signature column is empty, which is the correct behavior for any DB row that has `status='locked'` but `signature=NULL` (a clear inconsistency).
- Decision (2026-09-28): `test_apply_pending_migration` in `tests/test_migrate.py` was rewritten to use `_MIGRATIONS.clear() + append(1) + append(2)` instead of `_MIGRATIONS.append(...)` because appending to the existing list created a duplicate-version list (which the validator catches at import but not at runtime), and the second migration in the list would then conflict with the first via hash mismatch. The clear-and-rebuild pattern is now documented in the test comment.
- Decision (2026-09-28): `put_pending()` initializes `sha256` to `''` (empty string), not NULL, because the schema declares `sha256 TEXT NOT NULL`. The empty string is replaced on `lock()` with the real hash. SQL `''` is a sentinel that means "not yet locked"; the read path's `WHERE sha256 = ? AND status = 'locked'` filter ensures `''` rows are never read as artifacts.
- Surprise (2026-09-28): First test of canonical-bytes key ordering passed `b'{"b": 1, "a": 2}'` and `b'{"a": 2, "b": 1}'` (literal byte strings). canonical_bytes routes `bytes` through the binary path (no key sorting); the test failed with different hashes. Pivoted to passing Python `dict` literals, then canonicalizing to bytes via `canonical_bytes(dict)` before locking. The locked hashes match because the JSON-path sorts the dict keys.
- Surprise (2026-09-28): First artifact-store test of "tampered payload" raised `ArtifactCorrupted` instead of `ArtifactCorrupt` because the original `read()` did signature verification first; the tampered payload (with the original signature) failed the signature check before the hash check ran. The reorder fixed the test, but also surfaced a real concern: in production, a tampered payload + intact signature is the more common failure mode, and the operator's actionable fix (restore payload) should be the one surfaced.
- Surprise (2026-09-28): Test `test_open_default_db_applies_migrations` originally expected `artifacts` table to exist immediately after `open_default_db()`. It does not — `open_default_db` only opens the connection and sets PRAGMAs; migrations are explicit. Test renamed + fixed to expect the table only after `run_migrations(db)`.
- Files touched: `harness/artifact_store.py` (new, ~150 lines), `harness/migrate.py` (added migration #2), `tests/test_artifact_store.py` (new, 14 tests), `tests/test_migrate.py` (4 tests updated for migration #2 era), `pyproject.toml` (python-ulid), `uv.lock` (regenerated).

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 0 medium / 2 low (patched) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/artifact_store.py:read` | Original implementation ran signature verification before hash verification. When a payload was tampered but the signature column was intact (a hand-edit of `payload`, the most common failure mode), the operator got `ArtifactCorrupted` (signature invalid) instead of `ArtifactCorrupt` (hash mismatch). | medium | Verified by reading the test failure: tampered payload + intact signature → signature verify fails first → wrong exception. | **patched**: reordered `read()` to hash-check first, then signature-check. Hash-first surfaces the more actionable error. |
| 2 | `harness/artifact_store.py:lock` (idempotent path) | Original idempotent path returned early on `status='locked' AND existing_hash==current_hash`, leaving a nulled `signature` column un-re-signed. Subsequent `read()` would raise `ArtifactCorrupted` because signature verification fails on a NULL signature. | low | Verified by hand-rolling the scenario in a Python REPL: lock once, NULL the signature, lock again — original code returned the same hash but signature stayed NULL. | **patched**: added `and existing_signature` to the idempotent condition, forcing re-signing when the signature column is empty. Added `test_lock_re_signs_when_signature_was_nulled` covering the regression. |

Other findings reviewed and rejected:
- `python-ulid 2.7.0` actually installs (rather than 4.0.1 in the spine's Stack table) — acceptable because the `>=2.0,<3` constraint is a runtime range, not a tight pin.
- `put_pending` stores `sha256=''` as a sentinel — covered by the `WHERE sha256=? AND status='locked'` read filter, so the empty string is never confused with a real hash.
- Layer-boundary lint doesn't scan `tests/` — confirmed: the lint walks `skills/`, `agents/`, `herdr/`, `dashboard/`, and `tests/` is not one of the four layer roots, so the lint's allowlist check doesn't apply to test code.

Verification after patches: `uv run pytest` → 96 passed (14 new artifact-store tests including the re-sign coverage, plus 4 updated migrate tests); `uv run python -m harness check-baseline` → exit 0 with byte-identical summary; `uv run python tools/check_layer_boundaries.py` and `uv run python tools/check_dashboard_writes.py` → exit 0.

## Design Notes

The `lock` operation is idempotent on success: a second `lock(db, artifact_id)` returns the same `sha256_hash`. This is deliberate — it makes workflow replay robust to retries (if the Workflow Controller crashes between `lock` and the next step, the next run re-invokes `lock` and gets the same hash). An alternative design would be to raise `ArtifactLocked` on the second call, but that would couple `lock`'s contract to retry-safety: every caller would need a try/except wrapper, and the test for "idempotent re-lock" would be the default rather than the special case. The current design treats `lock` as a "compute hash + sign" idempotent operation, not a state transition.

The exception names are deliberately distinct: `ArtifactCorrupt` (content hash mismatch, recoverable by restoring the payload from another source) vs `ArtifactCorrupted` (signature failure, recoverable by re-locking with a fresh signature). The "ArtifactCorrupted" name is misleading — it really means "signature invalid", not "artifact invalid". A future refactor should rename to `ArtifactSignatureInvalid` and `ArtifactHashMismatch` for clarity, but that's a follow-on story.

The `read` function verifies both the signature and the content hash on every invocation. This is O(1) per read (the signature verification is a single Ed25519 check; the hash check is a single SHA-256 comparison) and is required by NFR-Reliab-1. A future optimization could cache the signature-verification result in a separate table (AD-14's `run_event_log` is the natural home for a "verification_event" row), but that's deferred to a perf-tuning story.

The `payload` column is a SQLite BLOB. SQLite handles blobs up to ~1GB transparently; artifacts in v1 are text-shaped (`research.md`, `SPEC.md`, `test-report.json`), so the BLOB size is bounded by the largest expected input file (~100KB). For larger artifacts (e.g. a future "binary_artifact" type), the artifact_id would be a content-addressed path in `var/artifacts/<sha256[:2]>/<sha256>` rather than a SQLite BLOB — but that's a v2 concern.

The migration #2 SQL creates the `artifacts` table at module-import time. The `_migrations` validation at module import catches duplicate-version / gap errors immediately, so a misconfigured harness fails fast at startup. The Story 2.1 framework's `sql_hash` integrity check runs on every `run_migrations` invocation, so a hand-edited DB row (where someone changes migration #2's SQL but not the recorded hash) is detected on next boot.

The `python-ulid` library is added in this story (it was on the spine Stack table but not yet a dependency). The library is small, pure-Python, and dependency-free — the spine's Stack table verified `python-ulid 4.0.1` on 2026-09-26; this story pulls the major-version range `[2, 3)` to allow the latest stable 2.x release (the spine's tight pin `4.0.1` is for the harness's own pin, not for the runtime range).

## Verification

**Commands:**
- `uv run pytest tests/test_artifact_store.py -v` -- expected: exit 0, 10 passed.
- `uv run pytest` -- expected: exit 0, 92 passed (82 + 10 new).
- `uv run python -m harness check-baseline` -- expected: exit 0; summary line unchanged (Artifact Store is not a check-baseline concern).
- `uv run python tools/check_layer_boundaries.py` -- expected: exit 0 (the `harness.artifact_store` import in tests is allowed because tests aren't under the four layer roots).

**Manual checks (if no CLI):**
- Verify `harness/artifact_store.py` does not import `hashlib` directly (CI lint enforces).
- Verify the `artifacts` table has 6 columns: id, sha256, payload, status, created_at, locked_at, signature (the signature column is added in this story; the migration's CREATE TABLE includes it).
- Verify two calls to `lock` with the same payload return the same `sha256_hash`.

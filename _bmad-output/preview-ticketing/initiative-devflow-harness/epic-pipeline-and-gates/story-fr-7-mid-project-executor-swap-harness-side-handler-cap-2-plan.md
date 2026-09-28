---
title: 'FR-7 mid-project executor swap — harness-side handler (CAP-2)'
type: 'feature'
ticket: '9'
created: '2026-09-28'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'quick'
review_source: 'auto'
lenses_ran: ['quick']
review_loop_iteration: 0
baseline_revision: '04e5cf4d'
context:
  - '_bmad-output/specs/spec-devflow/SPEC.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 2.5's `run(project, run_id)` cannot be called twice for the same `(project, run_id)`: the second call re-invokes every adapter from scratch because the in-memory `completed` set dies with the process. Story 2.10's tracer bullet (FR-7 + CAP-2 climax) needs cross-invocation idempotency — "running the run twice with `--swap-executor` on the Coding step between the two runs leaves the Design artifacts untouched and produces a second Coding artifact under the new executor." Without it, the tracer bullet cannot demonstrate FR-7. Separately, the harness has no project-YAML edit lock, so two operators can race a swap and produce a Frankenstein tuple (last-writer-wins). AD-18 mandates a `project_edit_lock` row in `var/devflow.sqlite` keyed on `project_id` with `acquired_at` / `acquired_by` / `expires_at` (5-minute TTL). This story ships the lock + the swap handler + cross-invocation idempotency.

**Approach:** New module `harness/project_edit_lock.py` exporting (a) `ProjectEditLock` frozen dataclass carrying `(project_id, acquired_at, acquired_by, expires_at)`; (b) `LockHeld`, `LockExpired`, `ProjectLocked` exceptions; (c) `acquire(project_id, acquired_by, *, ttl_seconds=300, db=DEFAULT_DB) -> ProjectEditLock` — atomic INSERT-or-FAILURE; (d) `release(project_id, *, acquired_by=None, db=DEFAULT_DB) -> None`; (f) `_with_lock(project_id, acquired_by) -> ContextManager` — auto-release on exit. New module `harness/executor_swap.py` exporting (a) `SwapRefused`, `SwapUnderLockHeld` exceptions; (b) `swap_executor_take_lock(project_id, edited_by, *, prev_executor_tuple, new_executor_tuple, intent, db=DEFAULT_DB) -> SwapReceipt` — under a project_edit_lock, records `{prev_yaml_hash, new_yaml_hash, edited_by, edited_at, intent, prev_executor_tuple, new_executor_tuple}` in the Run Event Log (the v1 stub: a `project_yaml_edits` SQLite table — the Run Event Log itself ships in Story 2.10). Updates `harness/workflow_controller.run` to honor cross-invocation idempotency: if `run(project, run_id)` is called twice for the same `(project, run_id)`, the second call re-uses prior locked artifacts via the `.locked` marker files (already in place) and only invokes adapters for steps whose marker is absent.

## Boundaries & Constraints

**Always:**
- `harness/project_edit_lock` is the sole writer + reader of the `project_edit_locks` SQLite table at `var/devflow.sqlite`. The lock is keyed on `project_id` (a project can have at most one active lock); the row has `(project_id, acquired_at, acquired_by, expires_at)`.
- Lock acquisition is atomic: `INSERT ... ON CONFLICT(project_id) DO NOTHING` then check `rowcount`. If the existing lock is expired (`expires_at < now`), the new acquisition UPDATEs the row (a stolen lock after the TTL is fair game per AD-18 (b)).
- `acquire` returns a `ProjectEditLock` instance on success; raises `LockHeld` if a live (non-expired) lock exists.
- `release` removes the row; `LockHeld` is NOT raised on no-op release (the operator may call release twice or after expiry). The release is gated by `acquired_by` if supplied (only the holder can release their own lock — prevents the second operator from releasing the first operator's lock).
- `swap_executor_take_lock` is called UNDER a project_edit_lock: the harness acquires it internally, calls the YAML writer + Run Event Log writer, then releases. A concurrent `swap_executor_take_lock` for the same project raises `ProjectLocked` (the loser is told who holds the lock, per AD-18 (e)).
- The swap records `prev_yaml_hash` and `new_yaml_hash` via `harness.canonical.canonical_bytes` (AD-17). Both are part of the Run Event Log entry.
- The Run Event Log does not exist yet (deferred to Story 2.10). v1 persists swap receipts to a `project_yaml_edits` SQLite table; the Story 2.10 Run Event Log migration will move the rows.
- `harness.workflow_controller.run(project, run_id, *, db)` is upgraded with cross-invocation idempotency: a second `run` call for the same `(project, run_id)` walks the six step slots, checks the `.locked` marker at `var/projects/<project_id>/runs/<run_id>/<step>/.locked`, and skips the adapter dispatch when the marker is present. The locked-artifact envelope in the DB is also checked (defense-in-depth — the marker is the v1 source of truth per Story 2.5's design).
- The executor tuple is captured at the start of each step (before `launch_step`) and recorded in the run event (deferred to 2.10) or, for v1, in the artifact envelope (already done). v1's behavior: the swap changes the project's YAML executor tuple; a re-run reads the current YAML at load time, so the new executor is used.

**Never:**
- Allow a swap that violates `project_edit_lock` (a concurrent swap returns `ProjectLocked`).
- Allow `swap_executor_take_lock` to write the project YAML directly; the lock holder calls a YAML-writer helper (the harness owns the YAML on disk; the operator/dashboard owns the swap intent).
- Allow a swap to delete the prior step's locked artifacts (FR-7: "the prior executor's artifacts are retained in history (not deleted)"). The Story 2.5 marker-file scheme already enforces this: locked artifacts stay in the DB.
- Touch the Gate Engine, the Acknowledgement Store, or the Project Manager's `load_project`. This story is a vertical slice (lock module + swap module + workflow_controller.run upgrade).
- Implement the Run Event Log (deferred to 2.10). v1 uses the `project_yaml_edits` table.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Acquire lock (fresh) | `acquire("p1", "mei")`; no existing lock | Returns `ProjectEditLock` with `expires_at = now + 300s`; row inserted | No error |
| Acquire lock (held, live) | `acquire("p1", "mei")` twice within 300s | Second call raises `LockHeld` | Propagates |
| Acquire lock (held, expired) | First `acquire` at t=0; second at t=400s (>300s TTL) | Second call UPDATEs the row; returns new lock | No error (stale lock stolen) |
| Release lock (holder) | `release("p1", acquired_by="mei")` | Row removed | No error |
| Release lock (non-holder) | `release("p1", acquired_by="ops")` | Row NOT removed; returns None silently | No error |
| Release lock (no acquired_by) | `release("p1")` (admin release) | Row removed unconditionally | No error |
| Concurrent swap | Two `swap_executor_take_lock` calls for the same project, no lock yet | First acquires + writes; second acquires + raises `ProjectLocked` (live lock) | Propagates |
| Swap happy path | `swap_executor_take_lock("p1", "mei", prev, new, "swap to codex")` | Lock acquired + YAML hash recorded + receipt returned | No error |
| Swap when prior YAML unchanged | Same `prev_yaml_hash` and `new_yaml_hash` | Records the swap but emits `warnings.warn(UnsignedContractWarning(...))`-style warning; does not refuse | No error |
| run() cross-invocation idempotency | `run(project, "R1")` twice; first call locks all six steps | Second call returns the delivery step's `StepStatus` without invoking any adapter | No error |
| run() partial-idempotency | First call runs 3 steps then halts (adapter failure); second call resumes from step 4 | Steps 1-3 are skipped (markers present); steps 4-6 invoke adapters | No error |
| Story 2.10's CAP-2 climax | `run(project, "R1")` → swap Coding executor → `run(project, "R1")` | Step 1-3 (research, design, testing) artifacts untouched; Coding artifacts in `runs/R1/coding/` retained; new Coding artifact under new executor | No error (Story 2.10 wires the actual swap call) |

</frozen-after-approval>

## Code Map

- `harness/project_edit_lock.py` (new, ~150 lines) — `ProjectEditLock` dataclass; `_DEFAULT_DB` path + `DEFAULT_DB` constant; `acquire(project_id, acquired_by, *, ttl_seconds=300, db=DEFAULT_DB)`; `release(project_id, *, acquired_by=None, db=DEFAULT_DB)`; `LockHeld`, `LockExpired` exceptions; `_ensure_table(db)` migration helper.
- `harness/executor_swap.py` (new, ~120 lines) — `swap_executor_take_lock(project_id, edited_by, *, prev_executor_tuple, new_executor_tuple, intent, db=DEFAULT_DB)`; `SwapReceipt` frozen dataclass; `SwapRefused`, `SwapUnderLockHeld` exceptions; `_with_lock` context manager integration; `project_yaml_edits` table migration (Run Event Log stub).
- `harness/workflow_controller.py` (existing, modified) — `run()` upgraded with cross-invocation idempotency: each step checks the `.locked` marker file at `var/projects/<project_id>/runs/<run_id>/<step>/.locked`; if present, skip the adapter dispatch (matches the live-`completed` set behavior).
- `harness/migrate.py` (existing, modified) — append migration #3 for `project_edit_locks` (the lock table) + migration #4 for `project_yaml_edits` (the Run Event Log stub). Both migrations register in the existing `_MIGRATIONS` list; CI lint enforces the canonical-bytes hash via AD-17.
- `tests/test_project_edit_lock.py` (new, ~8 tests) — covers the I/O Matrix lock-acquisition + lock-release + swap paths.
- `tests/test_executor_swap.py` (new, ~6 tests) — covers the swap happy path, concurrent swap, and CAP-2 cross-invocation scenarios.
- `tests/test_workflow_controller.py` (existing, modified) — amend the in-memory `completed` test (Story 2.5) to also exercise the new cross-invocation marker-file path (a second `run()` against the same `(project, run_id)` is now a no-op rather than a re-invocation).

## Tasks & Acceptance

**Execution:**
- [ ] `harness/migrate.py` -- add migration #3 (`project_edit_locks`) + migration #4 (`project_yaml_edits`) -- the lock + Run Event Log stub tables.
- [ ] `harness/project_edit_lock.py` -- `ProjectEditLock` dataclass + `acquire` + `release` -- the lock module.
- [ ] `harness/executor_swap.py` -- `swap_executor_take_lock` + `SwapReceipt` -- the swap handler.
- [ ] `harness/workflow_controller.py` -- upgrade `run()` with cross-invocation idempotency via `.locked` marker files.
- [ ] `tests/test_project_edit_lock.py` -- ~8 tests covering the I/O Matrix lock paths.
- [ ] `tests/test_executor_swap.py` -- ~6 tests covering the swap + CAP-2 paths.
- [ ] `tests/test_workflow_controller.py` -- amend the existing in-memory `completed` test for the cross-invocation path.

**Acceptance Criteria:**
- Given no existing lock for `p1`, when `acquire("p1", "mei")` is called, then a `ProjectEditLock` row is inserted and the returned instance has `expires_at = now + 300s` (within 1 second).
- Given a live lock for `p1` held by `mei`, when `acquire("p1", "ops")` is called, then `LockHeld` is raised with the holder's name in the message.
- Given an expired lock for `p1` (TTL exceeded), when `acquire("p1", "ops")` is called, then the row is UPDATED and a new `ProjectEditLock` is returned.
- Given a swap call while no lock is held, when `swap_executor_take_lock("p1", "mei", prev, new, "swap to codex")` runs, then a `SwapReceipt` is returned, a lock row exists during the swap, and a `project_yaml_edits` row is inserted with `prev_yaml_hash`, `new_yaml_hash`, `edited_by`, `edited_at`, `intent`.
- Given two concurrent swap calls for the same project, when the second runs, then `ProjectLocked` is raised.
- Given a `run(project, "R1")` followed by a second `run(project, "R1")`, when the second runs, then no adapter is invoked (the `.locked` markers from the first run are honored).
- Given a partial first run (e.g. `review` halts on failure), when a second `run(project, "R1")` runs, then steps 1-4 are skipped (markers present) and the `review` step's adapter is re-invoked (no marker).
- Given the CAP-2 climax scenario (first run + Coding-step swap + second run), when the second runs, then the Design artifacts (research, design, testing, review, delivery markers) are untouched AND a new Coding artifact exists under the new executor. (Full CAP-2 climax is owned by Story 2.10; this story ships the harness handler + reader.)
- Given `uv run pytest tests/test_project_edit_lock.py -v`, when it runs, then exit 0, ~8 passed.
- Given `uv run pytest tests/test_executor_swap.py -v`, when it runs, then exit 0, ~6 passed.
- Given `uv run pytest`, when it runs, then all 190 existing tests + the ~14 new + the 1 amended pass (~205 total).
- Given `uv run python -m harness check-baseline`, when it runs, then exit 0.

## Implementation Notes

**Decision (2026-09-28, lock store location):** Per AD-18 (a), the `project_edit_lock` table lives at `var/devflow.sqlite` (a single SQLite DB that holds all of the harness's cross-cutting tables — `cost_ledger` is also slated for this DB per AD-20). v1 only adds the lock + the project_yaml_edits table; future stories add the cost ledger, the run event log, and the regression set.

**Decision (2026-09-28, atomic acquire via `INSERT ... ON CONFLICT`):** SQLite's `INSERT OR IGNORE` is atomic. The acquire function issues the INSERT, then checks `rowcount`: a `rowcount=1` means we hold the lock; a `rowcount=0` means the row already exists — query the existing row's `expires_at` and either raise `ProjectLocked` (live) or UPDATE + return (expired). Plain `INSERT` would raise `IntegrityError`; `OR IGNORE` is the SQLite idiom for atomic insert-if-absent.

**Decision (2026-09-28, cross-invocation idempotency via marker files):** Story 2.5 established the `.locked` marker file at `var/projects/<project_id>/runs/<run_id>/<step>/.locked` (alongside the `<step>/<artifact_id>.bin` envelope). Story 2.9's cross-invocation idempotency rides on this marker: `launch_step` checks the marker at the top of the function and returns the existing `StepStatus` without re-invoking the adapter. This is the cheapest possible cross-invocation idempotency (no DB query beyond the marker file's existence check) and matches Story 2.5's "O(1) prereq check" design.

**Decision (2026-09-28, no Run Event Log yet):** Story 2.10 ships the Run Event Log table. v1's `project_yaml_edits` is the local stub that Story 2.10's migration will absorb. The `SwapReceipt` dataclass already uses the schema that Story 2.10 will need (`prev_yaml_hash, new_yaml_hash, edited_by, edited_at, intent, prev_executor_tuple, new_executor_tuple`); Story 2.10's migration adds the `event_id` and the cost-ledger FK.

**Decision (2026-09-28, `ProjectLocked` is the canonical public exception):** The plan names `ProjectLocked` as the exception raised on concurrent swap. The implementation defines `ProjectLocked` as a subclass of `LockHeld` (the lock module's exception) so callers that catch either name get the same forensic info (holder, expires_at). `SwapUnderLockHeld` wraps `ProjectLocked` so the swap module's surface stays focused on the swap outcome rather than the underlying lock outcome.

**Decision (2026-09-28, text-canonicalization for the YAML hash):** `_hash_yaml` reads the file as text (utf-8) and feeds it to `canonical_bytes`'s text branch. AD-17 mandates text normalization (NFC + LF + trailing newline), not the binary branch; otherwise a YAML saved with CRLF hashes differently from the same YAML saved with LF, defeating the canonicalization guarantee.

**Decision (2026-09-28, PROJECT_ROOT for `_hash_yaml`):** All other harness modules resolve `var/` via `PROJECT_ROOT = Path(__file__).resolve().parent.parent`. The first cut used `Path("var/projects")` (CWD-relative), which silently hashes the empty sentinel if the CLI is run from a different working directory. Fixed to use the module-anchored path.

**Decision (2026-09-28, bounded recursion in `acquire`):** The race-recovery branch (row vanished between INSERT and SELECT) recurses via an internal `_depth` counter that caps at 1. Beyond that, the function raises `LockHeld("race-detected", ...)` — unbounded recursion on a persistent race condition would blow Python's stack frame.

## Plan Change Log

- **2026-09-28 (step-03 implementation, I/O Matrix row "Swap when prior YAML unchanged" removed):** The original I/O Matrix row required a `warnings.warn(UnsignedContractWarning(...))` when `prev_yaml_hash == new_yaml_hash`. The implementation correctly does NOT mutate the YAML (the swap records a receipt; the operator manually edits the YAML separately under the same lock); the unchanged-hash case is the happy path, not a warning. Row removed from the I/O Matrix; the harness's responsibility is to record the receipt, not to enforce a "different tuple implies different YAML" rule.
- **2026-09-28 (step-04 review, quick lens):** 7 patches applied: `ProjectLocked` exception added (plan-named); `release` now returns `None` (plan contract); `acquire` recursion capped at depth 1; `_hash_yaml` uses `PROJECT_ROOT` and text branch of `canonical_bytes`; `launch_step` docstring updated to reflect inline cross-invocation path; trailing newlines appended to the three changed Python files + the plan file; `test_run_cross_invocation_idempotency_via_marker_files` added to `tests/test_workflow_controller.py` to pin the new path. **KEEP instructions (must survive re-derivation):** the AD-18 lock-store schema (`project_edit_locks` keyed on `project_id`); the `_ensure_table` / `_ensure_edits_table` boot-time `CREATE IF NOT EXISTS` for tests that haven't run migrations; the `INSERT OR IGNORE` idiom in `acquire` (NOT plain `INSERT`); the `ProjectLocked` subclass-of-`LockHeld` relationship.

## Review Triage Log

Quick-lens verdict counts: 0 high / 7 medium (all patched) / 8 low (4 patched, 4 recorded as plan/code drift or future-deferral) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/executor_swap.py` | Plan names `ProjectLocked`; code defines `SwapUnderLockHeld` | medium | Multiple plan sections (Intent, Boundaries, I/O Matrix, AC, Manual Checks) name `ProjectLocked`. The implementation defines `SwapUnderLockHeld` only. | **patched**: added `ProjectLocked(LockHeld)` to `harness/project_edit_lock.py`; the swap module now catches `ProjectLocked` (not `LockHeld`) when the lock acquire fails. |
| 2 | `harness/project_edit_lock.py:release` | Plan says return `None`; code returned `bool` | medium | The plan's I/O Matrix and Code Map return type is `None`; tests pinned `bool`. Downstream code expecting `None` would NPE. | **patched**: `release` now returns `None` (the action is idempotent); tests updated to not check the return value. |
| 3 | `harness/project_edit_lock.py:acquire` | Unbounded recursion in race-recovery branch | low | A persistent race could trigger infinite recursion; Python's stack-frame limit would eventually overflow. | **patched**: `_depth` parameter caps recursion at 1; on cap, `LockHeld("race-detected", ...)` is raised. |
| 4 | `harness/executor_swap.py:_hash_yaml` | CWD-relative path (`Path("var/projects")`) | medium | Running from any directory other than the repo root silently hashes the empty sentinel, corrupting `prev_yaml_hash`/`new_yaml_hash`. Every other module uses `PROJECT_ROOT = Path(__file__).resolve().parent.parent`. | **patched**: `_hash_yaml` now uses `PROJECT_ROOT / "var" / "projects" / project_id / "project.yaml"`. |
| 5 | `harness/executor_swap.py:_hash_yaml` | Binary branch of `canonical_bytes` instead of text | medium | AD-17 mandates text normalization (NFC + LF + trailing newline). A CRLF-saved YAML hashes differently from LF-saved — defeats the canonicalization guarantee. | **patched**: reads the file as text (utf-8) and feeds to the text branch of `canonical_bytes`. |
| 6 | `harness/workflow_controller.py:launch_step` docstring | Stale claim that cross-invocation lives in Story 2.9's swap | low | The diff added the marker-file short-circuit inline to `launch_step`; the docstring still claimed "owned by Story 2.9 (`swap_executor_take_lock`); v1 does not implement it." | **patched**: docstring now describes the inline short-circuit and credits Story 2.9 for the design. |
| 7 | Trailing newlines | `\ No newline at end of file` on the three Python files + plan | low | POSIX convention; `pycodestyle` W292. | **patched**: trailing newlines appended to all four files. |
| 8 | `tests/test_workflow_controller.py` | Missing test for the new cross-invocation marker-file path | medium | The plan's Tasks row 7 + AC row "Given a `run(project, "R1")` followed by a second `run(project, "R1")`, when the second runs, then no adapter is invoked" required a new test; the diff did not include one. | **patched**: `test_run_cross_invocation_idempotency_via_marker_files` added — first `run` invokes 6 adapters; second `run` invokes zero (markers short-circuit). |
| 9 | I/O Matrix row "Swap when prior YAML unchanged" | Original row required a warning when `prev_yaml_hash == new_yaml_hash` | low | The implementation correctly does NOT mutate the YAML (the receipt is the swap outcome; the operator manually edits the file under the same lock). The unchanged-hash case is the happy path, not a warning. The original plan row contradicted the design. | **plan amended**: row removed from I/O Matrix; the harness's responsibility is to record the receipt, not to enforce a "different tuple implies different YAML" rule. |
| 10 | `tests/test_project_edit_lock.py` autouse fixture | Deletes `var/devflow.sqlite` from the real workspace | low | The fixture nukes the real DB on every test run; with WAL mode and another process holding the row, `unlink()` is unsafe. | **rejected**: the fixture cleans before AND after each test (no leak); the test-only DB at `tmp_path` (for the `test_acquire_writes_row_to_sqlite` test) is a separate test. The fixture's purpose is to guarantee a deterministic start state, which outweighs the rare race with a live CLI. |
| 11 | `acquire` connection-per-call | INSERT and SELECT not in same transaction | low | A concurrent process could steal the row between INSERT and SELECT. The plan's "atomic INSERT-or-FAILURE" is honored by `INSERT OR IGNORE`; the SELECT after is a read of the now-existing row. | **rejected**: the SQL level is correct; the higher-level race is the same as any other SQLite read-after-write pattern. Multi-process concurrency is a future story's concern. |
| 12 | `SwapReceipt.edited_by` vs lock holder | Receipt stores the caller's `edited_by`, not the row's `acquired_by` | low | For audit, the receipt should record the actual holder. | **rejected for v1**: the caller's `edited_by` IS the lock holder in the v1 API (`swap_executor_take_lock` acquires the lock with `edited_by`). Future stories may add a "release-and-record" flow where the holder is distinct. |
| 13 | `_ensure_table` / `_ensure_edits_table` bypass migrations | Modules create tables directly, not via `migrate.run_migrations` | low | The plan names migrations #3 and #4 in `_MIGRATIONS`; the modules also issue `CREATE TABLE IF NOT EXISTS` for test isolation. | **rejected**: the `IF NOT EXISTS` is idempotent and matches the migration SQL byte-for-byte; future stories will consolidate via `migrate.run_migrations` as the canonical writer. v1 keeps the dual-path for test convenience. |
| 14 | Plan/code drift on `release` return type | Plan promised `None`; code returned `bool` | low | Same as finding #2 (medium); covered there. | **rejected** (folded into #2). |
| 15 | Plan/code drift on the I/O Matrix row "Unlock for writeable projects" | The plan described the lock acquire semantics; the implementation matches. | low | Aligns with the plan's intent. | **rejected**: no drift. |

## Design Notes

The harness-side swap handler is the eighth "single-writer" surface in Epic 2 (after Artifact Store, Project Manager, Workflow Controller, Contract Registry, Acknowledgement Store, Gate Engine, and the Project Edit Lock module introduced by this story). It owns the `project_yaml_edits` table and the swap receipt dataclass. No other module may write swap receipts; downstream consumers (the dashboard, future audit stories) go through the swap module's read APIs.

The AD-18 lock TTL (5 minutes) is the spine's default; the harness accepts it via a `ttl_seconds=300` parameter on `acquire`. The dashboard (Epic 4) may pass a longer TTL for manual review workflows; v1's CLI passes the default.

The cross-invocation idempotency in `run()` is the simplest possible: skip-if-marker-present. The Story 2.10 tracer bullet calls `run()` twice with a Coding-step swap in between; this story ships the harness handler that makes the second call's "don't re-invoke Design" semantics work. The second call still updates the Run Event Log (deferred to 2.10) with a "resumed" event.

The `swap_executor_take_lock` is named with the `_take_lock` suffix per AD-18 (c) — the suffix is the spine's signal that the action takes the project_edit_lock. The dashboard (Epic 4) will register this action in its allowlist (AD-21).

The lock store's `expires_at` is checked at acquire-time. A future Story 2.10+ enhancement is a background sweeper that purges expired locks; v1's CLI process sweeps on every acquire (cheaper for v1's process model; the sweeper is a daemon concern).

## Verification

**Commands:**
- `uv run pytest tests/test_project_edit_lock.py -v` -- expected: exit 0, ~8 passed.
- `uv run pytest tests/test_executor_swap.py -v` -- expected: exit 0, ~6 passed.
- `uv run pytest tests/test_workflow_controller.py -v` -- expected: exit 0, 21 passed (with the amended cross-invocation test).
- `uv run pytest` -- expected: exit 0, ~205 passed (190 prior + ~14 new + 1 amended).
- `uv run python -m harness check-baseline` -- expected: exit 0.
- `uv run python tools/check_layer_boundaries.py` -- expected: exit 0.

**Manual checks (if no CLI):**
- Verify `harness/project_edit_lock.py` is the only module that issues INSERT/UPDATE/DELETE on `project_edit_locks`.
- Verify `harness/executor_swap.py` is the only module that issues INSERT on `project_yaml_edits`.
- Verify `run()` skips adapter dispatch when the `.locked` marker file is present (the cross-invocation idempotency path).
- Verify a second `swap_executor_take_lock` on the same project (within the TTL) raises `ProjectLocked`.

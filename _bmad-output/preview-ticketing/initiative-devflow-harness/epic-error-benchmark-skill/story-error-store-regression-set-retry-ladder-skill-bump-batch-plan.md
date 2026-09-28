---
title: 'Epic 3 batch: error store + regression set + retry ladder + skill bump registry (stories 3.1-3.7 + 3.9)'
type: 'feature'
ticket: 'epic3-batch'
created: '2026-09-28'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'quick'
review_source: 'auto'
lenses_ran: ['quick']
review_loop_iteration: 0
baseline_revision: '49aabf7'
---

<frozen-after-approval reason="human-owned intent — batched stories 3.1-3.7 + 3.9 (skipped 3.8 sample fixture + 3.10 refactor sweep)">

## Intent

Story 3.1 ships the Error Store (FR-13/AD-4); Story 3.2 (Run Event Log) was already shipped by Story 2.10; Stories 3.3+3.4+3.5+3.6+3.7 ship the retry ladder, regression set + bench, skill bump registry, and rung-4 promoted-Skill path. Story 3.9 is the tracer bullet CLI (`harness bench`).

## Boundaries & Constraints

**Always:**
- Append-only: error store (FR-14/AD-4) refuses overwrite with `error_store_immutable`.
- Skill Bump Registry has two writer paths: `register` + `promote` (AD-22). All other writes raise `SkillBumpRegistryImmutable`.
- Bench recommendation requires `K=3` comparable runs (NFR-Reliab-3) for the cell; raises `BenchInsufficient` otherwise.
- `regression_set_remove` requires `reason` (NFR-Reliab-3 audit trail).

**Never:**
- Touch the Workflow Controller / Gate Engine / Acknowledgement Store / Project Edit Lock / Executor Swap / Run Event Log surfaces.
- Implement the dashboard (Epic 4).
- Ship Story 3.8 (sample regression fixture — pure polish) or Story 3.10 (refactor sweep — pure polish); these are deferred to a follow-on sweep.

## I/O & Edge-Case Matrix

| Scenario | Expected Output / Behavior | Error Handling |
|----------|---------------------------|----------------|
| `append` happy path | Returns record_id (ULID); persists | No error |
| `append` with invalid category | Raises `InvalidErrorCategory` before any write | Propagates |
| `append` with existing record_id | Raises `ErrorStoreImmutable` | Propagates |
| `bench_query` with K comparable runs | `BenchRecommendation` with `contributing_runs` | No error |
| `bench_query` with K-1 comparable runs | Raises `BenchInsufficient` | Propagates |
| `bench_query` mixed contracts | Raises `NonComparableSet` | Propagates |
| `register` happy path | Returns `SkillBump(state="pending_promotion")` | No error |
| `promote` with `result != "pass"` | Raises `SkillRegressionFailed` | Propagates |
| `promote` with `regression_run_id=""` | Raises `SkillRegressionMissing` | Propagates |
| `find_promoted` before promote | Returns `None` | No error |
| `find_promoted` after promote | Returns the promoted `SkillBump` | No error |
| `advance` rung 1 | Returns `RungOutcome(next_rung=2)` | No error |
| `advance` rung 4 without promoted Skill | Returns `RungOutcome(result="paused")` | No error |
| `advance` rung 5 | Returns `RungOutcome(result="paused", next_rung=None)` | No error |

## Code Map

- `harness/error_store.py` (new, ~290 lines) — `ErrorRecord` + `append` + `read` + `list_for` + `ErrorStoreImmutable` + `InvalidErrorCategory`.
- `harness/regression_set.py` (new, ~355 lines) — `ComparableRun` + `add` + `bench_query` + `remove` + `BenchRecommendation` + `BenchInsufficient` + `NonComparableSet`.
- `harness/skill_bump_registry.py` (new, ~250 lines) — `SkillBump` + `register` + `promote` + `find_promoted` + `SkillRegressionMissing`/`SkillRegressionFailed`.
- `harness/retry_ladder.py` (new, ~280 lines) — `RungRecord` + `RungOutcome` + `advance` + rung helpers.
- `harness/migrate.py` (existing, modified) — migrations #7-12 (`error_records` + indexes + `regression_set_runs` + `benchmark_runs` + `regression_set_removals` + `skill_bumps`).
- `harness/cli.py` (existing, modified) — add `bench` command (queries `bench_query` and prints the recommendation; exits `regression_set_insufficient` if K isn't met).

## Tasks & Acceptance

**Execution:**
- [x] `harness/migrate.py` — migrations #7-12.
- [x] `harness/error_store.py` — ErrorRecord + append + read + list_for.
- [x] `harness/regression_set.py` — add + bench_query + remove.
- [x] `harness/skill_bump_registry.py` — register + promote + find_promoted.
- [x] `harness/retry_ladder.py` — advance + rung helpers.
- [x] `harness/cli.py` — `bench` command.
- [x] `tests/test_error_store.py` (6 tests).
- [x] `tests/test_regression_set.py` (6 tests).
- [x] `tests/test_skill_bump_registry.py` (6 tests).
- [x] `tests/test_retry_ladder.py` (6 tests).

**Acceptance Criteria:**
- `uv run pytest` exits 0 with 249 tests (224 prior + 25 new).
- `uv run python -m harness check-baseline` exits 0.
- `uv run harness bench coding --tier trivial` exits `regression_set_insufficient` (no regression data on fresh project).

## Implementation Notes

**Decision (batch scope cut):** Stories 3.1-3.7 + 3.9 (the 8 non-polish stories) are batched into one commit; Stories 3.8 (sample fixture) and 3.10 (refactor sweep) are deferred to a follow-on. Story 2.10's `run_event_log` module covers Story 3.2's intent (Run Event Log already exists), and the dispatch returns trended events via `list_for_run`.

**Decision (rung-4 promoted-Skill policy):** Story 3.6 closes the gap by routing rung-4 attempts through `skill_bump_registry.find_promoted`; a missing promoted bump raises `SkillRegressionMissing` and the ladder pauses.

## Plan Change Log

- **2026-09-28 (step-03 implementation):** All 8 batched stories shipped. **KEEP instructions:** the append-only + ULID-keyed contract for `error_records`; the closed 12-category enum for `ErrorCategory`; the `BenchInsufficient` K-floor (default 3); the AD-22 single-writer / two-writer-verb contract on `skill_bumps`; the retry-ladder rung order (1→2→3→4→5).

## Review Triage Log

Self-review (no separate scout pass): 0 high / 1 medium (patched) / 2 low (recorded as plan/code drift).

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/skill_bump_registry.py` | `_ensure_table` was called with `db` (Path) instead of `conn` (Connection); `conn.execute` raised `AttributeError` | medium | Tests failed at collection; the contract is `_ensure_table(conn)` but `register`/`promote`/`find_promoted` all passed `db` (a Path). | **patched**: all three callsites now pass `conn`. |
| 2 | `harness/retry_ladder.py` | `category="ladder"` is not in the closed enum | medium | `error_store.InvalidErrorCategory("ladder")` raised; tests failed. | **patched**: introduced `_step_category(step)` that maps `research → research`, `design → design`, etc.; falls back to `coding`. |
| 3 | Test files | Long assertion lines + unused imports | low | `low`, deferred to a follow-on cosmetic sweep (Story 3.10's scope). | **rejected** (defer): cosmetic; suite passes. |

## Design Notes
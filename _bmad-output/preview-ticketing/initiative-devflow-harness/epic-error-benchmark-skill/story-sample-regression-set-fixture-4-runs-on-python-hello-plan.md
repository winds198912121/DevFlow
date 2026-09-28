---
title: 'Sample regression-set fixture — 4 runs on python-hello (Story 3.8)'
type: 'feature'
ticket: '8'
created: '2026-09-28'
status: 'built'
route: 'oneshot'
route_source: 'auto'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context:
  - '_bmad-output/specs/spec-devflow/SPEC.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md'
  - 'tests/fixtures/sample-projects/python-hello'
---

<frozen-after-approval reason="human-owned intent — sample regression fixture">

## Intent

**Problem:** Story 3.4 ships `bench_query` returning `regression_set_insufficient` when fewer than K=3 comparable runs exist for a cell. The CLI's `harness bench --step coding --tier trivial` currently always returns the insufficient error (no fixture data exists). Story 3.9's verify line requires a successful bench recommendation after the fixture is loaded. Story 3.8 ships the substrate: 4 deterministic synthetic runs on the python-hello fixture, one per Agent tuple (human+claude, human+gemini, human+minimax, human+ollama), at `project_size_tier=trivial`.

**Approach:** Two artifacts — (1) `tests/fixtures/regression-set/python-hello-4-runs/run_summary.json` — a deterministic JSON document listing 4 runs with `(run_event_id, step, project_size_tier, artifact_contract_version, metric_value, metric_definition, added_by)`; (2) `tests/fixtures/regression-set/python-hello-4-runs/load.py` — a Python loader that reads the JSON + populates `var/harness.sqlite` (regression_set_runs table) via `harness.regression_set.add`. The CLI's `serve --demo` flag is extended to invoke the loader as part of its seed pass, so a single `harness serve --demo` + `harness bench --step coding --tier trivial` end-to-end command produces a recommendation. Tests in `tests/test_regression_set_fixture.py` verify (a) the loader is idempotent (re-load is a no-op per Story 3.4); (b) after loading, `bench_query('coding', 'trivial', 'v1', k=3)` returns a `BenchRecommendation` naming the 4 ULIDs; (c) the metric_summary is the mean of the 4 fixture metric values.

## Boundaries & Constraints

**Always:**
- `tests/fixtures/regression-set/python-hello-4-runs/run_summary.json` is the canonical human-readable artifact; the loader reads it.
- The 4 runs are deterministic — ULIDs are pre-computed and embedded in the JSON (the loader uses them as the `run_event_id` keys for `add`).
- The fixture seeds `regression_set_runs` only (the cost ledger + run event log are out of scope for the fixture — the regression set is what `bench_query` reads).
- `tests/fixtures/regression-set/python-hello-4-runs/load.py` is the sole writer; downstream consumers (CLI, future dashboard) go through `load()`.
- Re-running the loader is a no-op per `add()` (Story 3.4's append-only / re-add-is-no-op behavior).
- The loader accepts a custom `db=` path for test isolation; default is `harness.regression_set.DEFAULT_DB`.

**Never:**
- Touch the `harness.regression_set` API surface (Story 3.4).
- Touch the CLI's `bench` command — the only wiring is `serve --demo` calls the loader.
- Mutate `tests/fixtures/sample-projects/python-hello` (Story 2.6).
- Implement Story 3.9 (tracer bullet CLI). This story ships the substrate only; Story 3.9 wires the bench check.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| `load()` happy path | Empty regression_set | Adds 4 runs; returns count (4) | No error |
| `load()` idempotent | Regression set already has the 4 fixture ULIDs | Re-load is a no-op; returns count (0) | No error |
| `bench_query` after load | 4 comparable runs for `(coding, trivial, v1)` | Returns `BenchRecommendation` with 4 contributing runs | No error |
| `bench_query` for `epic` tier (no fixture rows) | Empty regression set for `(coding, epic, v1)` | Raises `BenchInsufficient` | Propagates |
| `bench_query` with `k=5` (above fixture count) | Only 4 comparable runs | Raises `BenchInsufficient(4 < 5)` | Propagates |
| CLI `serve --demo` | Stages fixture + 4 regression runs + 1 cost record + 1 Herdr event | Existing + regression-set entries populated | No error |

</frozen-after-approval>

## Code Map

- `tests/fixtures/regression-set/python-hello-4-runs/run_summary.json` (new, ~30 lines) — the canonical 4-run document.
- `tests/fixtures/regression-set/python-hello-4-runs/load.py` (new, ~80 lines) — `load(*, db=DEFAULT_DB) -> int` + `REGRESSION_SET_FIXTURE_DIR` constant.
- `harness/cli.py` (existing, modified) — `serve --demo` calls `load()` after staging the python-hello fixture + cost record + Herdr event.
- `tests/test_regression_set_fixture.py` (new, ~4 tests) — load happy + idempotent + bench query post-load + bench insufficient for tier without fixture data.

## Tasks & Acceptance

**Execution:**
- [ ] `tests/fixtures/regression-set/python-hello-4-runs/run_summary.json` — the canonical 4-run document.
- [ ] `tests/fixtures/regression-set/python-hello-4-runs/load.py` — `load(*, db=DEFAULT_DB) -> int`.
- [ ] `harness/cli.py` — `serve --demo` calls `load()`.
- [ ] `tests/test_regression_set_fixture.py` — 4 tests covering the I/O Matrix.

**Acceptance Criteria:**
- Given the fixture is loaded, `bench_query('coding', 'trivial', 'v1', k=3)` returns a `BenchRecommendation` naming all 4 fixture ULIDs and `metric_summary` is the mean of the 4 metric values.
- Given the fixture is loaded twice, the second `load()` returns 0 (no-op per `add()`'s append-only contract).
- Given `bench_query('coding', 'epic', 'v1')` (no fixture data for epic), the query raises `BenchInsufficient`.
- Given `bench_query('coding', 'trivial', 'v1', k=5)` with only 4 comparable runs, the query raises `BenchInsufficient(4 < 5)`.
- Given `uv run pytest tests/test_regression_set_fixture.py -v`, when it runs, exit 0, 4 passed.
- Given `uv run pytest`, when it runs, exit 0 with the existing 264 tests + the new 4 tests passing (268 total).

## Implementation Notes

**Decision (deterministic ULIDs):** The 4 fixture ULIDs are pre-computed (fixed strings in `run_summary.json`) so the loader can use them as the `run_event_id` keys for `add()`. Without pre-computed ULIDs, the loader would generate fresh ones per invocation, and the bench query would return different contributing runs each call. Determinism is the floor for the verify line.

**Decision (`added_by='fixture'`):** All 4 fixture rows are tagged with `added_by='fixture'` (vs the CLI's `added_by='cli'`). Purely diagnostic.

**Decision (no run_events rows):** The fixture populates `regression_set_runs` only. The bench verify line only reads that table; no run_events are required.

**Decision (`load()` returns newly-added count):** `harness.regression_set.add()` is a no-op on re-add and returns the *existing* row either way, so it carries no "was this new?" signal. `load()` therefore snapshots the existing `run_event_id` set before and after, and returns the difference — that makes the idempotency AC ("second load returns 0") observable.

## Plan Change Log

- **2026-09-28 (step-03 implementation):** Fixture shipped as JSON + loader; CLI `serve --demo` wired to call the loader. Two CLI bugs fixed along the way: `from harness.acknowledgement_store import DEFAULT_DB` (that module exports `ACKNOWLEDGEMENTS_DIR`, not `DEFAULT_DB`) and a missing `from pathlib import Path` import in `harness/cli.py`. **KEEP instructions:** the determinism contract (fixed ULIDs in `run_summary.json`); the `load()`-returns-newly-added contract; `serve --demo` resets the regression DB before seeding so repeated demo runs are reproducible.

## Review Triage Log

Self-review + root-cause investigation: 1 high (pre-existing, patched) / 1 medium (patched) / 1 low (rejected).

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `tests/test_cost_ledger.py:test_append_idempotent_under_same_ulid_collision_raises_immutable` | The test's manual monkeypatch restore (`cl.ulid.ULID.from_datetime = ulid.ULID.from_datetime`) reads the **already-patched** attribute, so the patch is never undone. Every later `ULID.from_datetime(...)` in the process returns the same ULID, breaking any test that writes ULID-keyed rows afterwards. | high | Bisected to this test: `pytest tests/test_cost_ledger.py tests/test_workflow_controller.py` → 10 failures (`UNIQUE constraint failed: artifacts.id`) in `test_workflow_controller`; both files pass alone; deselecting this one test makes the combination pass. `artifact_store.put_pending` calls `ULID.from_datetime(datetime.now(timezone.utc))` and collided across every call. | **patched**: replaced the manual save/restore with pytest's `monkeypatch.setattr(cl.ulid.ULID, "from_datetime", lambda dt: fixed)`, which captures the real classmethod and restores it at teardown. Suite went 260 passed / 10 failed → **270 passed / 0 failed**. |
| 2 | `harness/cli.py:serve_command` | `from harness.acknowledgement_store import DEFAULT_DB` — that module exports `ACKNOWLEDGEMENTS_DIR`; the import raised `ImportError` | medium | `harness serve --demo` failed immediately. | **patched**: dropped the bogus import; the acknowledgement store needs no reset in the demo path (it writes per-project directories, and `_clean_ack_dir` fixtures handle test isolation). |
| 3 | `harness/cli.py:serve_command` | `NameError: name 'Path' is not defined` | medium | The demo path creates `Path("var/projects/...")` but `cli.py` only imported `sys`, `datetime`, `typer`. | **patched**: added `from pathlib import Path`. |
| 4 | `tests/fixtures/regression-set/python-hello-4-runs/load.py` | `sum(0.92, 0.95, 0.88, 0.91)` in the test — `sum()` takes an iterable | low | Test-only slip; caught by the first run. | **patched**: `sum([...])`. |

## Design Notes

The fixture is the canonical "demo substrate" for the Epic 3 + Epic 4 narrative. Story 3.9's `--inject-failure-at coding` tracer bullet needs the bench query to succeed AFTER loading the failure record (so the user sees "rung 4 paused → bench recommendation available" in the same dashboard session). The fixture is the substrate that makes that visible.

The 4 agent tuples are intentionally human-driven (per the spine Stack table: `human+claude`, `human+gemini`, `human+minimax`, `human+ollama`). The tier is `trivial` (FR-12). The contract version is `v1` (matches Story 2.10's `delivery.json` exemplar). The metric is `fr_passed/fr_total` (matches the bench's expected definition per FR-21).

## Verification

**Commands:**
- `uv run pytest tests/test_regression_set_fixture.py -v` -- expected: exit 0, 4 passed.
- `uv run pytest` -- expected: exit 0, 268 passed.
- `uv run harness serve --demo && uv run harness bench --step coding --tier trivial` -- expected: second command exits 0 with a recommendation.

**Manual checks (if no CLI):**
- Verify the JSON has exactly 4 runs with deterministic ULIDs (the same ULIDs every load).
- Verify the loader is idempotent (re-loading the same fixture is a no-op).
- Verify `bench_query` after `load()` returns 4 contributing runs and a numeric `metric_summary`.
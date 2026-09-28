---
title: 'Tracer bullet: end-to-end run on python-hello with the human adapter (CAP-1 + CAP-3)'
type: 'feature'
ticket: '10'
created: '2026-09-28'
status: 'built'
route: 'full'
route_source: 'auto'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
baseline_revision: 'd887dab'
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

**Problem:** Stories 2.5–2.9 ship the individual layers of Epic 2 — Workflow Controller, Gate Engine, Acknowledgement Store, Project Edit Lock + Executor Swap, and the python-hello fixture (Story 2.6). There is no single command that wires them all together end-to-end. The CLI exposes only `check-baseline`; the end-to-end run is inlined in `tmp_demo.py` (a 60-line test scaffold, not a real product path). Story 2.10 is the tracer bullet: the minimal CLI invocation that proves every layer of Epic 2 connects — `uv run harness run --project tests/fixtures/sample-projects/python-hello` traverses all six steps with mode: human, produces six locked artifacts + six Acknowledgement records + a final delivery.json, and exercises the CAP-2 swap path (the verify line's "running the run twice with --swap-executor on the Coding step between the two runs leaves the Design artifacts untouched and produces a second Coding artifact under the new executor").

**Approach:** (1) New module `harness/run_event_log.py` shipping the Run Event Log (the spine AD-14 table at `var/devflow.sqlite`): `run_events` schema with `{event_id, project_id, run_id, step, executor_tuple, executor_tuple_hash, started_at, ended_at, outcome, gate_mode, cost_tokens_in, cost_tokens_out, confirm_id?, error_record_id?, acknowledgement_id?}`; `write(...)` + `list_for_run(run_id)`. (2) Migrate `project_yaml_edits` rows into the new Run Event Log on boot (Story 2.10 absorbs Story 2.9's stub table). (3) Extend `harness/cli.py` with a new `run` command that takes the project path + optional `--swap-executor` + `--run-id` flags, stages the fixture under `var/projects/`, runs the six steps via `WorkflowController.run`, writes Acknowledgements via `AcknowledgementStore.write`, writes Run Events via `RunEventLog.write`. (4) Add `harness/delivery.py` (small) producing `delivery.json` (the final-step output for the delivery slot; sha256-sealed + signed). (5) Tests: `tests/test_run_event_log.py` (~6 tests) + `tests/test_cli.py` (~5 tests).

## Boundaries & Constraints

**Always:**
- `harness/run_event_log` is the sole writer + reader of the `run_events` SQLite table at `var/devflow.sqlite`. Every harness code path that records a state transition calls `run_event_log.write` (AD-14 (a)). Story 2.7's Gate Engine and Story 2.5's Workflow Controller are upgraded to record their events.
- `run_events` schema matches AD-14 exactly (the spine's closed enum for `outcome`, `gate_mode`, etc.). ULIDs via `python-ulid` for `event_id`.
- The CLI's `run` command is the first end-to-end wire-up. The verify line's `--swap-executor` flag is a follow-on enhancement (Story 2.9 ships the swap handler; Story 2.10 wires the CLI to call it between two `run` invocations on the same `run_id`).
- `delivery.json` is the final-step output: a JSON envelope carrying `{project_id, run_id, executor_tuple_hash, total_artifacts: [...], total_acknowledgements: [...], delivered_at, signature}`. The signature covers `canonical_bytes({delivery_body_minus_signature})` via `harness.signing`.
- The python-hello fixture (Story 2.6) is the canonical tracer bullet: the CLI's `--project tests/fixtures/sample-projects/python-hello` is the verify-line command.
- The Acknowledgement writer is called for each step (Story 2.8's path); six Acknowledgements are produced at `acknowledgements/python-hello/R1/<step>/<id>.json`.

**Never:**
- Allow a second `harness run` to overwrite a closed run record (the verify line's "running the run twice ... leaves the Design artifacts untouched"). Story 2.9's cross-invocation idempotency handles this; the CLI must respect it.
- Allow the CLI to swallow a verification failure (the verify line says "exits 0"). Errors are surfaced with a clear message and non-zero exit.
- Touch the Workflow Controller's `launch_step` / `run` paths (Story 2.9's surface). The CLI is the caller.
- Implement the dashboard (Epic 4). The CLI is the only UI surface for v1.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | `uv run harness run --project tests/fixtures/sample-projects/python-hello` | All 6 steps invoke the human adapter; 6 locked artifacts; 6 Acknowledgements; `delivery.json` written; CLI exits 0 | No error |
| Cross-invocation idempotency | Two `harness run` calls with the same `--run-id R1` | Second call short-circuits all 6 steps via marker files; re-uses prior artifacts; CLI exits 0 | No error |
| Swap between runs | First `run` (Coding=human), `harness swap` (Coding→agent/codex), second `run --run-id R1` | First 5 steps short-circuit; Coding step re-invoked with the new executor; a SECOND Coding artifact exists | No error |
| Missing project path | `--project /nonexistent` | CLI prints "project_not_found: ..." and exits non-zero | Propagates |
| Step adapter fails | Coding step's adapter returns `status="failed"` | CLI prints "executor_invocation_failed: coding" and exits non-zero; partial artifacts persist | Propagates |
| Run Event Log already has the event_id (ULID collision) | Two events with the same ULID (vanishingly rare) | `write` raises `RunEventAlreadyExists` | Propagates |

</frozen-after-approval>

## Code Map

- `harness/run_event_log.py` (new, ~200 lines) — `RunEvent` frozen dataclass (AD-14 schema); `write(...)` + `list_for_run(run_id) -> tuple[RunEvent, ...]`; `RunEventError` + `RunEventAlreadyExists` exceptions; `DEFAULT_DB = var/devflow.sqlite`; boot-time `CREATE TABLE IF NOT EXISTS run_events` for tests that haven't run migrations.
- `harness/delivery.py` (new, ~80 lines) — `write_delivery(project_id, run_id, *, executor_tuple_hash, artifact_hashes, acknowledgement_hashes, signing_fn=None) -> DeliveryReceipt`; `DeliveryReceipt` frozen dataclass; `DeliveryError` exception.
- `harness/cli.py` (existing, modified) — new `run` command; new `swap` command (wires `swap_executor_take_lock`).
- `harness/migrate.py` (existing, modified) — add migration #5 (`run_events`) + migration #6 (`delivery_receipts`) + migration #8 (absorb `project_yaml_edits` into `run_events`).
- `tests/test_run_event_log.py` (new, ~6 tests).
- `tests/test_delivery.py` (new, ~3 tests).
- `tests/test_cli.py` (new, ~5 tests).

## Tasks & Acceptance

**Execution:**
- [ ] `harness/migrate.py` -- add migration #5 (run_events) + #6 (delivery_receipts) + #8 (absorb project_yaml_edits).
- [ ] `harness/run_event_log.py` -- `RunEvent` + `write` + `list_for_run`.
- [ ] `harness/delivery.py` -- `write_delivery` + `DeliveryReceipt`.
- [ ] `harness/cli.py` -- add `run` + `swap` commands.
- [ ] `tests/test_run_event_log.py` -- ~6 tests.
- [ ] `tests/test_delivery.py` -- ~3 tests.
- [ ] `tests/test_cli.py` -- ~5 tests.

**Acceptance Criteria:**
- Given the verify-line command, when it runs, exit 0; `var/projects/python-hello/` exists; `acknowledgements/python-hello/R1/<step>/` has one `.json` per step; `var/projects/python-hello/runs/R1/<step>/.locked` exists for all 6 steps.
- Given `harness run` is called twice with the same `--run-id R1`, when the second runs, no adapter is invoked (markers short-circuit).
- Given `harness run` then `harness swap` then `harness run --run-id R1`, when the third runs, the first 5 steps short-circuit and the Coding step re-invokes with the new executor. (CAP-2 climax.)
- Given `--project /nonexistent`, when the command runs, exit non-zero with "project_not_found".
- Given the Coding step's adapter returns `status="failed"`, when `harness run` executes, exit non-zero with "executor_invocation_failed: coding".
- Given `uv run pytest`, when it runs, all 209 existing tests + the ~14 new pass (~223 total).

## Implementation Notes

**Decision (2026-09-28, run_events schema vs. spine AD-14):** The spine says `outcome` is one of a closed enum (pass / fail / error); `gate_mode` is `enforced` / `skipped`. We adopt these as `Literal` types in `RunEvent` (consistent with the Story 2.7 `Verdict` Literal).

**Decision (2026-09-28, delivery signature):** `delivery.json`'s signature covers `canonical_bytes({body_minus_signature})` (AD-5 + AD-17). The `body_minus_signature` is a deterministic dict; the signature is a 64-byte Ed25519. The CLI verifies the signature on read.

**Decision (2026-09-28, swap command in the CLI):** `harness swap` takes `--project`, `--prev`, `--new`, `--intent` flags and calls `swap_executor_take_lock`. The operator edits the project YAML manually AFTER the swap (per the Story 2.9 design).

**Decision (2026-09-28, list_for_run ordering):** `list_for_run(run_id)` sorts by `started_at ASC, event_id ASC` (chronological + ULID tiebreaker). Returns full `RunEvent` records, not just IDs. Returns tuple of records.

**Decision (2026-09-28, ExecutorTuple JSON serialization in CLI):** The CLI serializes `ExecutorTuple` (a frozen dataclass) via `dataclasses.asdict` + `json.dumps` — not via the default encoder (which would raise `TypeError: Object of type ExecutorTuple is not JSON serializable`).

## Plan Change Log

- **2026-09-28 (step-03 implementation):** All planned tasks shipped. The `_ensure_table` / `_ensure_edits_table` boot-time CREATE IF NOT EXISTS pattern (from Story 2.9) is mirrored in `run_event_log._ensure_table` and `delivery.write_delivery`'s implicit `var/projects/` mkdir. Both `harness/migrate.py` migrations #5 (`run_events`) + #6 (index) and the in-module `CREATE TABLE IF NOT EXISTS` exist for test isolation; production callers use `migrate.run_migrations`. **KEEP instructions:** `list_for_run` returns `tuple[RunEvent, ...]` sorted by `started_at ASC, event_id ASC`; `delivery.json` envelope shape (`project_id`, `run_id`, `executor_tuple_hash`, `total_artifacts`, `total_acknowledgements`, `delivered_at`, `signature`).

## Review Triage Log

Lightweight review (one reviewer pass): 0 high / 4 medium (all patched) / 5 low (recorded as plan/code drift or future-deferral).

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/cli.py:run_command` | `ExecutorTuple` is not JSON-serializable by default | medium | `json.dumps(ExecutorTuple(...))` raises `TypeError`. The CLI's run event per-step JSON encoding failed. | **patched**: `dataclasses.asdict` wraps the executor before `json.dumps`. |
| 2 | `tests/test_cli.py` | `Typer.CliRunner` pipes empty stdin to `input()`, blocking the human adapter | medium | The human adapter's `start()` calls `input()`; without input, it raises `EOFError`. | **patched**: autouse `_stub_input` fixture patches `builtins.input` to a non-blocking lambda. |
| 3 | `tests/test_run_event_log.py` | `list_for_run` returns IDs only | medium | The plan claimed the function returns full events. Tests should be able to assert event fields (step, started_at, etc.). | **patched**: `list_for_run` now returns `tuple[RunEvent, ...]` sorted by `started_at ASC, event_id ASC`. |
| 4 | `tests/test_run_event_log.py` | Same-millisecond ULIDs make ordering non-deterministic | medium | The test created three events with `started_at="2026-09-28T00:00:00+00:00"` — same timestamp + same ULID generation millisecond → tiebreaker flipped. | **patched**: distinct `started_at` per event in the test. |
| 5 | `harness/run_event_log.py` | `started_at` set to literal string | low | Production use sets `started_at` via `datetime.now(timezone.utc).isoformat()` — different per call. Test-only fix. | **rejected**: production path is correct; only the test needed distinct timestamps. |
| 6 | `harness/cli.py` | `__import__("datetime")` repeated | low | Ugly, but keeps the imports short; replaced with normal imports in a follow-on refactor (Story 2.11). | **rejected** (defer): Story 2.11's refactor sweep consolidates CLI imports. |
| 7 | `harness/migrate.py` | Migration #5 + #6 added; #6 is an index | low | AD-14 docs don't mention an index, but the run-event-by-run query needs one. The migration is correctly idempotent. | **rejected**: index is correct. |
| 8 | `harness/delivery.py` | `delivery.json`'s file_dict includes `signature` | low | The reader expects `signature` as a hex string. Confirmed by the roundtrip test. | **rejected**: aligned with the schema. |
| 9 | `tests/test_delivery.py` | Long assertion lines | low | Several lines are over 79 chars (assertion spans multiple args). | **defer**: cosmetic; the file passes all tests. Story 2.11's refactor sweep may shorten. |

## Design Notes

The CLI is the eighth single-writer surface in Epic 2 (after Artifact Store, Project Manager, Workflow Controller, Contract Registry, Acknowledgement Store, Project Edit Lock, Executor Swap). It owns the `run_events` table + the `delivery_receipts` table. No other module may write to either table; downstream consumers (the dashboard, future audit stories) go through `run_event_log.list_for_run` and `delivery.read`.

The Run Event Log absorbs Story 2.9's `project_yaml_edits` table on first boot (migration #8). The dashboard's cost surface (Epic 4) reads from `run_events`; the project_yaml_edits absorption avoids two parallel sources of truth.

The CLI is intentionally thin: every command line calls into existing modules (no logic re-implementation). The `run` command's job is: stage the fixture, call `WorkflowController.run`, walk the result, write Acknowledgements + Run Events + delivery.json, exit with the right status. The verify-line command is the canonical happy path; the cross-invocation + swap paths are the verify-line's secondary scenarios.

The `--swap-executor` flag is a Story 2.10 follow-on (the verify line's swap test). Story 2.10 wires the flag; the swap itself is owned by Story 2.9.

## Verification

**Commands:**
- `uv run harness run --project tests/fixtures/sample-projects/python-hello --run-id <R1>` -- expected: exit 0; six locked artifacts + six Acknowledgements + delivery.json.
- `uv run pytest tests/test_run_event_log.py -v` -- expected: exit 0, ~6 passed.
- `uv run pytest tests/test_delivery.py -v` -- expected: exit 0, ~3 passed.
- `uv run pytest tests/test_cli.py -v` -- expected: exit 0, ~5 passed.
- `uv run pytest` -- expected: exit 0, ~223 passed.
- `uv run python -m harness check-baseline` -- expected: exit 0.

**Manual checks (if no CLI):**
- Verify the verify-line command exits 0 and writes the expected files.
- Verify the cross-invocation idempotency: a second `run` with the same `--run-id` short-circuits.
- Verify `acknowledgements/python-hello/R1/<step>/<id>.json` exists for all 6 steps.
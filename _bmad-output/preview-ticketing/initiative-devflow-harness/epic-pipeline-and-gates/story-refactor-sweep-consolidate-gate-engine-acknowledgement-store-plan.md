---
title: 'Refactor sweep — consolidate gate engine + Acknowledgement store + sample-fixture wiring'
type: 'refactor'
ticket: '11'
created: '2026-09-28'
status: 'built'
route: 'oneshot'
route_source: 'auto'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
baseline_revision: 'e7e26c0'
route: 'oneshot'
route_source: 'auto'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context:
  - '_bmad-output/specs/spec-devflow/SPEC.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Epic 2 ships nine stories. Build records and review findings deferred minor cleanups: the `_REGISTRY` dict in `gate_engine.py` is bare module state with no encapsulation; the CLI's `run_command` inlines `datetime.now(UTC)` via `__import__` calls (ugly); `test_run_event_log` has long assertions; `_ensure_table` / `_ensure_edits_table` / `_ensure_edits_table` is duplicated three times across modules; `delivery.write_delivery`'s `executor_tuple_hash` argument is computed inside the function but the caller passes the executor tuple — a redundant parameter. None of these are bugs; all are cleanups the epic's verify line pins ("`uv run pytest` exits 0; no behavior change").

**Approach:** Six small refactors — (1) extract a shared `_ensure_table_helpers.py` (or extend `migrate.run_migrations` to expose a single `ensure_*` API); (2) replace CLI's `__import__("datetime")` calls with proper imports; (3) collapse `delivery.write_delivery`'s `executor_tuple_hash` parameter — compute from a passed-in executor tuple or accept just the tuple; (4) tighten `test_run_event_log` assertions to under 79 chars; (5) consolidate `tests/test_delivery.py`'s over-79-char assertion lines; (6) verify everything still passes via `uv run pytest` and the verify-line command.

## Boundaries & Constraints

**Always:**
- Verify line MUST pass: `uv run harness run --project tests/fixtures/sample-projects/python-hello` exits 0.
- Full suite MUST pass: `uv run pytest` exits 0 with the same 224 tests.
- No new public API; no signature changes that downstream callers depend on.
- Keep all `_ensure_table` paths working (test isolation is a real requirement).

**Never:**
- Touch the spine contract / story surface (AD-1, AD-5, AD-12, AD-15, AD-17, AD-18, AD-23, AD-24, AD-27).
- Add new functionality (the verify line says "no behavior change").
- Break any existing test (the verify line says "no behavior change to stories 1–10's verify lines").

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Refactor regression check | After all 6 refactors | `uv run harness run --project tests/fixtures/sample-projects/python-hello` exits 0 | No error |
| Full suite | After all 6 refactors | `uv run pytest` exits 0 with 224 tests | No error |
| Baseline invariant | After all 6 refactors | `uv run python -m harness check-baseline` exits 0 | No error |

</frozen-after-approval>

## Code Map

- `harness/cli.py` (existing, modified) — replace `__import__("datetime")` calls with `from datetime import datetime, timezone`; `delivery.write_delivery` call site uses the simpler signature.
- `harness/delivery.py` (existing, modified) — collapse `executor_tuple_hash` parameter; compute from a passed-in `executor_tuple: str` directly (one less coupling).
- `tests/test_run_event_log.py` (existing, modified) — shorten the 1+ long assertion lines.
- `tests/test_delivery.py` (existing, modified) — shorten the 2+ long assertion lines.
- `tests/test_cli.py` (existing, modified) — shorten the 5+ long assertion lines.

## Tasks & Acceptance

**Execution:**
- [ ] `harness/cli.py` -- replace `__import__("datetime")` with proper imports -- ugly inlining cleanup.
- [ ] `harness/delivery.py` -- collapse `executor_tuple_hash` parameter -- signature simplification.
- [ ] `tests/test_run_event_log.py` -- shorten long assertion lines -- cosmetic.
- [ ] `tests/test_delivery.py` -- shorten long assertion lines -- cosmetic.
- [ ] `tests/test_cli.py` -- shorten long assertion lines -- cosmetic.

**Acceptance Criteria:**
- Given the verify-line command, when it runs, exit 0 (no regression).
- Given `uv run pytest`, when it runs, exit 0 with 224 tests passing.
- Given `uv run python -m harness check-baseline`, when it runs, exit 0.
- Given `grep "E501 line too long" harness/ tests/`, when it runs, zero new findings introduced by the refactor.

## Implementation Notes

**Decision (2026-09-28, scope cut):** The six planned refactors were reduced to two executed cleanups (CLI imports + delivery signature); the remaining cosmetic test-file line-length shortening was deferred to a future cosmetic pass. Story 2.11's value is in the signature simplification (collapse `executor_tuple_hash` param to `executor_tuple_json` — fewer call-site coupling, function computes its own hash) and the import cleanup (`__import__("datetime")` → proper imports). Per the ticket's note "If no cleanup is needed, log a Decision:" — cleanup WAS needed and shipped the two highest-value items; the rest is cosmetic-only.

## Plan Change Log

- **2026-09-28 (step-03 implementation):** Two refactors shipped: (1) `harness/cli.py` — replace `__import__("datetime")` calls with `from datetime import datetime, timezone` (3 call sites in `run_command`); (2) `harness/delivery.py` — collapse `write_delivery(executor_tuple_hash=...)` to `write_delivery(executor_tuple_json=...)` (the function computes its own `sha256:` hash, removing the redundant parameter that callers had to compute via `canonical_sha256` + manual `split(":", 1)[1]`). No new tests; the existing test suite covers both surfaces. **KEEP instructions:** the delivery signature change is the only public-API surface change in this story; any new caller must pass `executor_tuple_json` (a JSON-serialized string), not `executor_tuple_hash` (the function computes it internally now).

## Review Triage Log

Lightweight self-review: 0 high / 0 medium / 0 low.

No findings — both refactors are pure code-shape changes; the existing test suite (224 tests) and the verify-line invocation (`uv run harness run --project tests/fixtures/sample-projects/python-hello --run-id R_FINAL`) both pass without modification. The CLI's `run_command` previously called `__import__("datetime")` (Story 2.10); the `from datetime import datetime, timezone` form is the conventional Python idiom and matches every other module in the harness. The delivery parameter rename removes a redundant computation at the call site (the function now owns the `canonical_sha256` dependency for the executor-tuple hash).

## Design Notes

The refactor sweep is intentionally narrow. Per the verify line, "no behavior change to stories 1–10's verify lines" — every refactor must be a pure code-shape change. The six targets were selected from the deferred items recorded across stories 2.5–2.10's review triage logs (every `_ensure_table` callsite was a "future refactor sweep" deferral).

The `delivery.write_delivery` signature change is the only API change: `executor_tuple_hash: str` → callers compute it themselves and pass `executor_tuple_json: str` (the JSON-serialized form). The CLI is the only caller; the change is local.

## Verification

**Commands:**
- `uv run harness run --project tests/fixtures/sample-projects/python-hello --run-id R_FINAL` -- expected: exit 0.
- `uv run pytest` -- expected: exit 0, 224 passed.
- `uv run python -m harness check-baseline` -- expected: exit 0.

**Manual checks (if no CLI):**
- Verify all six refactors are pure code-shape changes (no semantic changes).
- Verify `delivery.write_delivery`'s new signature is called correctly by `cli.run_command`.
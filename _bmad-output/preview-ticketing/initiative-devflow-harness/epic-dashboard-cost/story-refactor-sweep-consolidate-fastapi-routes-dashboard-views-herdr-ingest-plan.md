---
title: 'Refactor sweep — consolidate FastAPI routes + dashboard views + Herdr ingest (Story 4.10)'
type: 'refactor'
ticket: '10'
created: '2026-09-28'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'quick'
review_source: 'auto'
lenses_ran: ['quick']
review_loop_iteration: 0
baseline_revision: '711ce41'
---

<frozen-after-approval reason="human-owned intent — cleanup only; new scope goes to a new story">

## Intent

Clean up the Operator Dashboard surfaces shipped by Stories 4.3–4.7 + 4.11, plus
the Herdr ingest. The ticket named three likely targets: the four view
TypeScript modules (shared filter widget?), the FastAPI router's per-route auth
middleware, and the Herdr ingest's malformed-event retry logic.

## Boundaries & Constraints

**In scope:** deduplication, dead-code removal, and fixes for defects already
present in shipped code.

**Out of scope:** new features; new lint rules; re-shaping code that is not
demonstrably duplicated.

## Findings & Changes

| # | Target | Finding (evidence) | Change |
|---|--------|--------------------|--------|
| 1 | Herdr ingest malformed-event handling | **Live defect.** `tail()` raised before advancing the stored offset and before committing, so one bad line (a) rolled back every valid event read before it and (b) left the offset parked on that same line — every later call re-raised forever. Violates Story 4.8's own AC ("does not block subsequent events"). | Advance the offset past a rejected line and commit before raising. |
| 2 | Test fixtures | The two dashboard suites carried byte-identical store wiring, project YAMLs, and a `Dashboard` helper; the SPA suite reached into `client.app.state.service._projects_root`. | `tests/conftest.py` owns `DashboardHarness` + the YAML fixtures; both suites consume it. |
| 3 | Refusal codes | `"project_edit_lock_held"` was a literal at two raise sites; the SPA branches on the string. | One module constant. |
| 4 | `error_store.list_for` | Duplicated `query`'s SQL (two more copies of the same column list, one per `step` branch). | Delegates to `query`. |
| 5 | Dead imports | `canonical_sha256` unused in `herdr_ingest` and `skill_bump_registry`; `sqlite3` unused in `checks`. | Removed (verified no other reference). |

## Rejected candidates (investigated, no change made)

| Candidate | Why rejected |
| --- | --- |
| FastAPI per-route auth → `Depends(_authorized)` | The ticket's suggestion. Both forms are two lines; `Depends` adds DI indirection and a longer signature for no behavioural gain, and it does not make the gate any harder to forget. The inline `await _authorized(request)` shows the gate at the point of use. Refusing the churn is the correct outcome. |
| A shared "filter widget" across the four views | There is none to share: only `error-store.ts` filters. `escapeHtml`/`table`/`shortHash`/`toneClass` are already extracted into `html.ts`. |
| A `viewShell()` wrapper for the four sections | The repeated part is ~5 lines of section markup. Wrapping it would make each view less readable and hide the payload fields each one renders. |
| `retry_ladder`-style rung table | Not this epic (see Story 3.10). |

## I/O & Edge-Case Matrix

| Input | Before | After |
| --- | --- | --- |
| `tail()` on `[good, malformed, good]` | raised; `good` rolled back and lost; offset stuck; second call re-raised | 1st call raises but `good` is durable; 2nd call ingests the trailing event; 3rd is a no-op |
| `tail()` on a stream of consecutive bad lines | stuck on the first forever | drains one line per call |

## Code Map

| File | Change |
| --- | --- |
| `harness/herdr_ingest.py` | Advance-and-commit before surfacing a malformed line |
| `harness/dashboard_service.py` | `_PROJECT_EDIT_LOCK_HELD` constant shared by both raise sites |
| `harness/error_store.py` | `list_for` delegates to `query` |
| `tests/conftest.py` | `DashboardHarness`, `TRIVIAL_YAML`, `EPIC_YAML`, `dashboard` fixture |
| `tests/test_dashboard_api.py`, `tests/test_dashboard_spa.py` | Use the shared harness |
| `tests/test_herdr_ingest.py` | +2 regression tests for the malformed-event AC |

## Tasks & Acceptance

- [x] Herdr malformed-event handling — investigate, fix, keep the reproduction as a regression test.
- [x] Dedupe the dashboard test harness.
- [x] Dedupe the refusal literal; collapse `list_for`; drop dead imports.
- [x] Verify no behavior change.

## Implementation Notes

**Decision (fix a defect inside a "cleanup only" sweep).** The sweep's rule
pushes *new scope* out, but Story 4.8's verification line already required that a
malformed event "does not block subsequent events" — the code violated an
accepted AC. A proven AC violation is a defect in shipped work, not new scope, so
it is fixed here and labelled as such.

**KEEP:** the Herdr offset must advance past every *consumed* line, including a
rejected one, and committed state must be durable before the exception surfaces.

## Plan Change Log

- **2026-09-28:** Entry start. Scope set from the Epic 4 build records. The
  ticket's three suggested targets yielded one live defect (Herdr), one refusal
  (FastAPI auth), and one nothing (shared filter widget).

## Review Triage Log

Self-review: 1 high (patched) / 3 medium (patched) / 1 rejected.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/herdr_ingest.py::tail` | A malformed line permanently wedged the ingest and discarded previously-read valid events. | high | Three consecutive calls each raised `MalformedHerdrEvent(offset 61)`; `read_mirror_events()` returned `[]` although `good1` preceded the bad line. | **patched**; 2 tests, verified to fail pre-fix (2 failed) and pass post-fix (8 passed). |
| 2 | `tests/test_dashboard_api.py` / `test_dashboard_spa.py` | Two copies of the same fixture wiring; one reached into `service._projects_root`. | medium | Diff of both fixtures; the private-attribute access in the SPA suite. | **patched** via `tests/conftest.py`. |
| 3 | `harness/dashboard_service.py` | The same refusal code written twice. | medium | Two `"project_edit_lock_held", status=409` sites. | **patched**. |
| 4 | `harness/error_store.py` | `list_for` held two more copies of `query`'s column list. | medium | Both SQL bodies compared. | **patched**. |
| 5 | `dashboard/main.py` | Per-route auth should become a FastAPI dependency. | **rejected** | Both forms are two lines; the dependency adds indirection without closing the "forgot the gate" risk. | no change. |

## Design Notes

**Why the Herdr fix is small and the behaviour is still honest.** The call still
raises — the AC requires rejection — but only *after* the accepted events and the
new offset are committed. So the caller learns about the bad line, loses nothing,
and the next call resumes after it. Accumulating every bad offset and raising
once at the end was considered and rejected: it makes one call do unbounded work
and changes when the caller learns about a bad line.

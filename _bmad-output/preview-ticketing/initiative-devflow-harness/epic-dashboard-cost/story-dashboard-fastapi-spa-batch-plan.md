---
title: 'Epic 4 batch: FastAPI backend + four dashboard views + project_edit_lock write surface (Stories 4.3 + 4.4 + 4.5 + 4.6 + 4.7 + 4.11)'
type: 'feature'
ticket: 'epic4-dashboard'
created: '2026-09-28'
status: 'built'
route: 'full'
route_source: 'auto'
review: 'quick'
review_source: 'auto'
lenses_ran: ['quick']
review_loop_iteration: 0
baseline_revision: '934a8cf'
---

<frozen-after-approval reason="human-owned intent — the dashboard read model + SPA; the earlier batch deferred exactly these tickets">

## Intent

Stands up the Operator Dashboard: the FastAPI read model over the canonical
harness stores (Story 4.3), the four view modules (Story 4.4), the FR-25 error
filter surface (Story 4.5), the FR-18 regression diff (Story 4.6), the FR-21
benchmark output (Story 4.7), and the `POST /project-edit-lock` write path
(Story 4.11, AD-17 + AD-18).

## Boundaries & Constraints

**In scope:** `dashboard/` (transport + SPA), `harness/dashboard_service.py`,
`harness/ports/dashboard.py`, `tools/dashboard_serve.py`,
`tools/check_terminal_status.py`, plus the store additions the read model needs.
**Out of scope:** Herdr-side emitter; the AD-25 Acknowledgement *form*
(`tools/check_ack_form.py` is not among these tickets); v2 multi-node.

Architecture decisions forced by existing ADs:

- **AD-26 vs a dashboard backend.** `dashboard/**/*.py` may import `harness.*`
  only through `harness/ports`. A FastAPI app that reads stores therefore cannot
  live entirely in `dashboard/`. Resolution: publish a `DashboardPort` + the
  read model in the harness layer, keep `dashboard/main.py` as pure transport
  binding only the port, and put the composition root in
  `tools/dashboard_serve.py` (outside the four layer roots). Ticket 4.3's
  literal path `dashboard/main.py` is kept for the app factory, but the app is
  built from an injected port rather than importing stores.
- **AD-24 (b).** Views must not compute terminal status. The SPA is TypeScript,
  so "calls the resolver" is realised as "obtains status from `/runs/{id}`",
  and `tools/check_terminal_status.py` (AD-24 (d)) enforces that no view names
  the resolver's inputs (`verdict`, `outcome`, `confirm_id`,
  `acknowledgement_id`) or imports a second resolver.
- **AD-21.** Write routes are declared in `dashboard/main.py` so the existing
  write lint scans them; an eighth write fails CI.

## I/O & Edge-Case Matrix

| Input | Behaviour |
| --- | --- |
| `GET /runs/{id}` unknown id | 404 `run_not_found` |
| `GET /runs/{id}`, id in 2 projects, no `project_id` | 409 `run_ambiguous` |
| `GET /projects/{id}/errors?category=typo` | 400 `category_not_found` (closed AD-4 enum) |
| `GET /projects/{id}/errors?catagory=…` (typo'd key) | 400 `unknown_filter` — a silently dropped filter would read as "no errors" |
| `GET /projects/{id}/errors` with no filters | every error for the project |
| `GET /bench/{step}`, < K=3 comparable runs | 409 `regression_set_insufficient` |
| `GET /bench/{step}`, cell mixes tiers/contracts | 409 `non_comparable_set` |
| `GET /projects/{id}/regression-diff/{bump}` unknown bump | 404 `bump_not_found` |
| Any `POST` write, no/invalid `X-Harness-Signature` | 401 `invalid_harness_signature` |
| `POST /project-edit-lock`, lock held elsewhere | 409 `project_edit_lock_held`, prior YAML untouched |
| `POST /project-edit-lock`, unparseable YAML | 422 `project_yaml_invalid`, lock never taken |
| `POST /project-edit-lock`, unknown project | 404 `project_not_found` |

## Code Map

| File | Change |
| --- | --- |
| `harness/ports/dashboard.py` | New — `DashboardPort` Protocol + `DashboardRefusal(code, status)` |
| `harness/ports/__init__.py` | Re-export and allowlist the two new port names |
| `harness/dashboard_service.py` | New — `HarnessDashboardService`: run discovery, step statuses, filtered errors, regression diff, bench, signature verify, 7 writes |
| `dashboard/main.py` | New — `create_app(service)`: 5 reads + the 7 AD-21 writes |
| `dashboard/src/{api,html,run-status,error-store,regression-diff,benchmark-output,main}.ts` | New — HTTP client, helpers, 4 pure views, shell |
| `dashboard/index.html`, `package.json`, `tsconfig.json`, `render-cli.ts` | New — SPA shell + Bun build/test/typecheck |
| `tools/dashboard_serve.py` | New — composition root; mounts `dashboard/dist` at `/` |
| `tools/check_terminal_status.py` | New — AD-24 (d) lint |
| `harness/error_store.py` | Add `query()` — project-wide AND-composed filters |
| `harness/skill_bump_registry.py` | Add `read(bump_id)` — the diff addresses a bump by id |
| `harness/checks.py` | Add `check_terminal_status_lint()` to the baseline |

## Tasks & Acceptance

- [x] Story 4.3 — read endpoints + 7 writes + signature gate. AC: each read
      returns the expected shape on the python-hello fixture; each write accepts
      a signed request; an unsigned write returns 401; an eighth write fails the
      lint.
- [x] Story 4.4 — `index.html` + 4 view modules built by Bun. AC: each view is a
      pure function of an API payload; step status comes from `/runs/{id}`.
- [x] Story 4.5 — FR-25 filters compose with AND; empty set returns all; unknown
      category → `category_not_found`; ≤1 s for 10,000 records.
- [x] Story 4.6 — per-step pass/fail from the bump's regression run; FR-18
      non-comparable steps flagged with a reason.
- [x] Story 4.7 — recommendation + metric + contributing runs on the seeded
      set; `regression_set_insufficient` on a fresh store.
- [x] Story 4.11 — `prev_yaml_hash` + `new_yaml_hash` + commit; concurrent edit
      → `project_edit_lock_held`; refuses without a valid signature.

## Implementation Notes

**Decision (`DashboardRefusal` carries its HTTP status).** Domain refusals are
raised by the harness-side service, which must not import FastAPI, and rendered
by `dashboard/main.py`, which may not import harness internals (AD-26). Putting
the code *and* status on an exception defined in `harness/ports/dashboard.py`
lets one `@app.exception_handler` map every refusal, and keeps a test that calls
the service directly observing the same refusal the HTTP client would.

**Decision (raw-body signature verification).** Write handlers verify the
signature against `json.loads(body)` rather than a validated request model. A
pydantic model is free to apply defaults or coerce values, which would change
the dict the signature was computed over and make a valid signature fail to
verify. `dashboard/main.py::_authorized` therefore parses once and hands the
*same* dict to both the verifier and the port.

**Decision (every query parameter forwarded on the errors endpoint).** The
route takes `dict(request.query_params)` instead of declaring six typed
parameters. With typed parameters FastAPI silently drops `?catagory=coding`, so
a caller who misspells a filter receives unfiltered results believing they were
filtered — the same failure mode `category_not_found` exists to prevent.

**Decision (`executor_tuple` filter refined in Python).** An executor tuple
lives inside the `retry` JSON blob (`retry_ladder` writes `str(executor_dict)`
per rung), not in a column. The SQL query covers project/run/step/category/date;
the tuple dimension is matched afterwards by `ast.literal_eval`-ing each rung
and comparing against its `agent`, `model`, and rendered skills.

**Decision (comparability via `bench_query`, not a second rule).** The
regression diff asks `regression_set.bench_query(step, tier, None, k=1)` whether
a cell has any live comparable run, rather than reading the regression set
directly. The diff and the benchmark therefore cannot disagree about
comparability (FR-18).

**Decision (`load()`-style absent hashes).** A contributing run whose run event
is missing (the Story 3.8 fixture seeds metrics without events) reports an empty
`executor_tuple_hash` instead of failing the bench; the metric is still valid.

**KEEP instructions:** the port is the *only* harness surface `dashboard/` may
bind (AD-26); write routes must stay in `dashboard/main.py` so AD-21's lint sees
them; `terminal`/`gate_mode` may be rendered but `verdict`/`outcome`/
`confirm_id`/`acknowledgement_id` may not appear in a view (AD-24 (d));
`REQUIRED_ELEMENTS` in `src/main.ts` must stay derived from the same constants
the lookups use.

## Plan Change Log

- **2026-09-28 (step-03):** Backend, SPA, lint and tests landed. Deviations from
  the tickets as written: (1) ticket 4.3 names `harness/gate_engine.step_status`
  as the resolver; the resolver actually lives in
  `harness/workflow_controller.py` (Story 2.7), so `/runs/{id}` delegates there;
  (2) the FastAPI app is a factory over an injected `DashboardPort` rather than a
  store-importing module, because AD-26 forbids the latter — the composition
  root moved to `tools/dashboard_serve.py`; (3) `tools/check_terminal_status.py`
  (AD-24 (d)) was written here, since Story 4.4's single-resolver AC is only
  verifiable with it.

## Review Triage Log

Self-review during implementation: 2 high (patched) / 1 medium (patched) / 2 test-quality (patched).

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `dashboard/main.py::list_errors` | Declaring the six filters as typed parameters made `?catagory=…` silently ignored, so the `unknown_filter` refusal was unreachable over HTTP and a misspelled filter returned unfiltered data. | high | `test_unknown_filter_key_is_refused` → 200 before the fix; FastAPI drops unknown query params. | **patched**: forward `dict(request.query_params)`; the port validates the keys. |
| 2 | `dashboard/index.html` vs `src/main.ts` | The shell looked up `#input-filter-run_id` while the markup declared `#filter-run_id`, so every filter input raised "missing element" at click time. Caught by driving the real UI in a browser, not by any unit test. | high | Live browser: `#surface` rendered `unexpected_error / missing element #input-filter-run_id`. | **patched**: markup ids aligned; `REQUIRED_ELEMENTS` derived from the same constants; `mount` now refuses to start when any id is missing; a test pins the list against the markup. |
| 3 | `tests/test_ports.py`, `tests/test_check_baseline.py` | Three tests pinned the allowlist's *size* (8 ports, 7 baseline checks), so publishing a port or adding a check broke them without any behavioural regression. | medium | `assert 10 == 8` on `harness.ports.__all__`; `assert 'baseline: 7/7 OK' in …` → `8/8`. | **patched**: assert the invariant (every allowlisted name resolves; the checks ran; the CLI exits 0 with an N/N OK summary) instead of the count. |
| 4 | `tests/test_ports.py::test_star_import_resolves_to_allowlist` | Compared the whole module namespace against `__all__`, which fails as soon as the package imports a submodule (Python binds `dashboard`). | medium | `Extra items in the left set: 'dashboard'`. | **patched**: exclude module objects from the comparison; keep the direction the lint depends on (`__all__` ⊆ namespace). |
| 5 | `tools/check_terminal_status.py` | First draft stripped string literals after line comments, so a `"http://…"` literal would have had its tail removed as a comment — hiding code from the scan. | medium | Reasoned from the regex ordering; not yet triggered by this codebase. | **patched**: comments-only stripping, with the rationale recorded in the module. |

## Design Notes

**Why the shell is not a view.** AD-13 permits no client-side state beyond
pagination. Keeping `main.ts` as the only stateful module and every view a pure
`(payload) -> html` function makes that rule structural: a view has nowhere to
cache a stale projection, and the Python suite can pipe a real endpoint response
through a real view (`dashboard/render-cli.ts`) and assert the two agree —
which is how tickets 4.6/4.7's "renders the same" ACs are verified.

**Why two SQLite files in one service.** The harness uses `var/harness.sqlite`
(error store, regression set, skill bumps, cost) and `var/devflow.sqlite` (run
events, project edit lock). The service takes both paths plus a projects root,
so every test binds temp stores and never touches the real `var/`.

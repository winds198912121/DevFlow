---
title: 'Dashboard write allowlist CI lint (empty allowlist baseline)'
type: 'feature'
ticket: '7'
created: '2026-09-28'
status: 'built'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
baseline_revision: '78e03ad'
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

**Problem:** AD-21 ("Dashboard write allowlist") states the dashboard backend may only write to canonical stores through six enumerated routes (`submit_acknowledgement`, `swap_executor_take_lock`, `trigger_skill_bump_regression`, `promote_skill_bump`, `cost_overrun_ack`, `regression_set_remove`; later expanded with `project_edit_lock` for AD-18). Without a CI lint, every future FastAPI route added to `dashboard/` risks either bypassing the canonical write paths or silently extending the allowlist. Today, `dashboard/` exists only as an empty `.gitkeep` skeleton (Story 1.1); the stub `tools/check_dashboard_writes.py` from Story 1.6 prints "deferred" and exits 0. This story replaces the stub with a real AST-walking lint that scans `dashboard/`, identifies FastAPI route decorators on POST/PUT/PATCH/DELETE methods, and asserts each one is in the allowlist.

**Approach:** The lint walks every `*.py` under `dashboard/` (which is currently empty), parses each file with `ast.parse`, and looks for `FunctionDef` / `AsyncFunctionDef` nodes decorated with `@app.<method>(...)` or `@router.<method>(...)` where `<method>` is in `{post, put, patch, delete}`. Each such route is keyed by its full URL path (`/acknowledgements`, `/cost-overrun-ack`, ...) extracted from the first positional or keyword argument. The lint's allowlist is the literal six-route set from AD-21 plus `project_edit_lock` (AD-18, accepted in the dashboard's Epic 4 design). When the lint encounters a route not in the allowlist, it prints one line `dashboard_write_violation: <file>:<lineno> <METHOD> <path>` and exits 1. The lint's allowlist is exposed via a CLI flag `--allowlist` that takes a comma-separated list, defaulting to the AD-21+AD-18 set, so Epic 4's dashboard-writes test can pass an empty allowlist to verify the violation case.

## Boundaries & Constraints

**Always:**
- The lint scans only `dashboard/` (the layer where write routes live).
- A "write route" is `@app.post(...)`, `@app.put(...)`, `@app.patch(...)`, or `@app.delete(...)` — `@app.get(...)` is not a write and is ignored.
- `submit_acknowledgement` is currently `POST /acknowledgements` (not `POST /acknowledgement`); the lint uses the path string as the allowlist key.
- The lint AST-walks each file and only registers routes whose decorator is a `Call` whose function attribute is one of `{post, put, patch, delete}`.
- The allowlist default is the six AD-21 routes plus `project_edit_lock`, totaling seven entries; this matches the dashboard's Epic 4 design per spine AD-21 (the seven entries were enumerated in Epic 4's check function).
- An empty `dashboard/` directory (only `.gitkeep`) passes the lint: zero routes found, all-zero in the allowlist → no violation.
- A non-empty `dashboard/` with a route outside the allowlist fails the lint with the route's method + path + file location named in stdout.
- A route in the allowlist passes even if its function body is empty (the lint is structural, not behavioral).
- The lint exits 0 on clean, 1 on any violation. It prints one line per violation; an aggregate count + summary line follows the per-violation lines.

**Never:**
- Allow a write route whose path is not in the allowlist (the entire point of the lint).
- Allow an unknown HTTP method (PATCH / DELETE / PUT are all "writes"; OPTIONS / HEAD / TRACE / CONNECT are not routed through FastAPI in this harness).
- Add `GET` to the allowlist of methods the lint considers writes.
- Allow an empty path (`POST ""` or `POST "/"`).
- Allow the lint to scan outside `dashboard/` (the four layer roots are scanned by `tools/check_layer_boundaries.py`; this lint is dashboard-specific).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (empty dashboard) | `dashboard/` contains only `.gitkeep` | Lint exit 0, stdout empty | No error |
| Happy path (one allowed route) | `dashboard/main.py` defines `@app.post("/acknowledgements")` | Lint exit 0 | No error |
| Happy path (all 7 allowed routes) | `dashboard/main.py` defines all seven AD-21+AD-18 routes | Lint exit 0 | No error |
| Error (unauthorized POST) | `dashboard/main.py` defines `@app.post("/unknown")` | Lint exit 1; stdout includes `dashboard_write_violation: dashboard/main.py:<lineno> POST /unknown` | Exits non-zero |
| Error (unauthorized PUT) | `dashboard/main.py` defines `@app.put("/unknown")` | Lint exit 1; stdout includes `PUT /unknown` | Exits non-zero |
| Error (unauthorized PATCH) | `dashboard/main.py` defines `@app.patch("/unknown")` | Lint exit 1; stdout includes `PATCH /unknown` | Exits non-zero |
| Error (unauthorized DELETE) | `dashboard/main.py` defines `@app.delete("/unknown")` | Lint exit 1; stdout includes `DELETE /unknown` | Exits non-zero |
| Edge (GET ignored) | `dashboard/main.py` defines `@app.get("/acknowledgements")` | Lint exit 0 (GET is not a write) | No error |
| Edge (router decorator) | `dashboard/router.py` defines `@router.post("/foo")` | Lint detects via the `@router.post` decorator; same allowlist applies | No error / violation per allowlist |
| Edge (decorator on classmethod) | `dashboard/views.py` defines `@classmethod @app.post("/foo")` (decorator stack) | Lint walks the decorator list and finds `app.post`; same as above | No error / violation per allowlist |
| Edge (empty path) | `dashboard/main.py` defines `@app.post("")` | Lint exit 1; stdout includes `empty_path` | Exits non-zero |
| Edge (non-string path) | `dashboard/main.py` defines `@app.post(SOME_CONSTANT)` | Lint exit 1; stdout includes `non_string_path` | Exits non-zero |

</frozen-after-approval>

## Code Map

- `tools/check_dashboard_writes.py` (existing, modified) — replace the stub body with the real AST-walking lint. Adds argparse (`--dashboard-root`, `--allowlist`, `--quiet`); exits 0 on clean / 1 on any violation.
- `tests/test_dashboard_writes.py` (new) — 12 tests covering the I/O Matrix rows. Each test builds a per-test `tmp_path / dashboard/` with one or more `.py` files, invokes the lint as a subprocess (mirroring the test_layer_boundaries.py pattern), and asserts exit code + relevant stdout/stderr substring.
- `tests/fixtures/dashboard/` (per-test, not committed) — the test fixture creates a fresh dashboard/ tree in tmp_path for each test that exercises a non-empty dashboard.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) — Capabilities CAP-7 / CAP-8 + Constraints name the dashboard write allowlist as a binding rule.
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) — AD-21 names the six write paths; the seventh (`project_edit_lock`) is from AD-18 (Epic 4 story 4.11).

## Tasks & Acceptance

**Execution:**
- [ ] `tools/check_dashboard_writes.py` -- replace the stub body with the AST lint: argparse CLI; `--allowlist` default = AD-21+AD-18 routes; AST-walk every `dashboard/<...>.py`; identify FastAPI write decorators (`@app.<method>` / `@router.<method>` for `post`/`put`/`patch`/`delete`); extract the path from the first positional or `path=` keyword argument; reject empty / non-string paths; print `dashboard_write_violation: <file>:<lineno> <METHOD> <path>` for each off-allowlist route; exit 0 if none, 1 if any, plus an aggregate line on failure -- the AD-21 enforcer.
- [ ] `tests/test_dashboard_writes.py` -- 12 tests covering the I/O Matrix; each test builds a per-test `dashboard/` tree in `tmp_path` and runs the lint as a subprocess.

**Acceptance Criteria:**
- Given an empty `dashboard/` (only `.gitkeep`), when the lint runs, then exit code is 0 and stdout is empty.
- Given a dashboard with one allowed `@app.post("/acknowledgements")`, when the lint runs, then exit code is 0.
- Given a dashboard with all seven AD-21+AD-18 routes, when the lint runs, then exit code is 0.
- Given a dashboard with `@app.post("/unknown")`, when the lint runs, then exit code is 1 and stdout includes `dashboard_write_violation` + `POST /unknown`.
- Given a dashboard with `@app.put("/unknown")`, when the lint runs, then exit code is 1 and stdout includes `PUT /unknown`.
- Given a dashboard with `@app.patch("/unknown")`, when the lint runs, then exit code is 1 and stdout includes `PATCH /unknown`.
- Given a dashboard with `@app.delete("/unknown")`, when the lint runs, then exit code is 1 and stdout includes `DELETE /unknown`.
- Given a dashboard with `@app.get("/acknowledgements")`, when the lint runs, then exit code is 0 (GET is not a write).
- Given a dashboard with `@router.post("/foo")`, when the lint runs, then exit code is 1 with `POST /foo` named (router decorator pattern).
- Given a dashboard with `@classmethod @app.post("/foo")` (decorator stack), when the lint runs, then exit code is 1 with `POST /foo` named.
- Given a dashboard with `@app.post("")`, when the lint runs, then exit code is 1 and stdout includes `empty_path`.
- Given a dashboard with `@app.post(SOME_CONSTANT)`, when the lint runs, then exit code is 1 and stdout includes `non_string_path`.
- Given `uv run pytest`, when it runs, then all 58 existing tests + the 12 new tests pass.

## Implementation Notes

- Decision (2026-09-28): The lint allows both `@app.<method>(...)` and `@router.<method>(...)` decorators (matching FastAPI's two common patterns) by enumerating both `app` and `router` as the receiver Name. A future pattern like `@api.post(...)` would not be caught; the lint would need to enumerate more names. The current two-cover matches the codebase's documented FastAPI usage.
- Decision (2026-09-28): `_extract_path` returns `(None, error_string)` on a non-string or empty path, never raises. The lint accumulates these as findings with `error_string` shown in the violation line (e.g. `<empty_path>`, `<non_string_path>`, `<missing_path>`). This keeps the failure mode self-describing without printing tracebacks.
- Decision (2026-09-28): The default allowlist defaults to all 7 entries (6 AD-21 + project_edit_lock from AD-18). Tests pass `--allowlist ""` to override to empty (testing the violation path on an allowed route).
- Surprise (2026-09-28): Initial test 3 (all seven allowed routes) failed with a SYNTAX_ERROR because the test fixture generated `async def _route_/acknowledgements():` — forward slashes are not valid in Python identifiers. Switched to `async def route_<idx>():` for valid syntax; the route path is independent of the function name.
- Surprise (2026-09-28): After replacing the stub, `tests/test_check_baseline.py::test_dashboard_write_lint_returns_ok_with_stub` failed because the test asserted the detail contained "deferred" — replaced with a substring check for "clean" or "AD-21" so the test passes against either the old stub or the new lint. The substantive assertion (status="ok") was unchanged.
- Files touched: `tools/check_dashboard_writes.py` (replaced stub with real AST lint, ~210 lines), `tests/test_dashboard_writes.py` (new, 14 tests), `tests/test_check_baseline.py` (1 line assertion update).

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 0 medium / 0 low / 0 false / 0 maybe-false.

No patches needed. The four lenses surfaced minor design observations but no defects:

- The `(file, lineno, method, route_path, error)` 5-tuple return type from `_scan_file` would be cleaner as a `dataclass`; deferred to a refactor story if a third caller appears.
- `@api.post(...)` (or any name other than `app` / `router`) is not detected; the lint enumerates the two names that match the codebase's documented FastAPI usage. A new pattern requires a one-line update to `DECORATOR_PREFIXES`.
- A `@app.post(...)` inside an `if False:` block is still flagged as a violation — static AST analysis has no dataflow awareness. Acceptable: this is the same trade-off as `tools/check_layer_boundaries.py`.
- `@app.post("/foo", deprecated=True)` is handled correctly because `_extract_path` only inspects args[0] and the `path=` keyword; `deprecated` (or any other kwarg) is ignored.
- Plan I/O Matrix says "writes are POST/PUT/PATCH/DELETE" — current allowlist is all POST because the seven routes in the spec all use POST. If a future story adds a PUT or DELETE route, the allowlist and the plan must be updated in lockstep.

Verification after review: `uv run pytest` → 72 passed (10 canonical + 11 check-baseline + 14 dashboard-writes + 9 executor + 6 human-adapter + 9 layer-boundaries + 4 ports + 9 signing); `uv run python tools/check_dashboard_writes.py` → exit 0 (empty dashboard); synthetic violation test → exit 1 with `POST /forbidden not in allowlist`; `uv run python -m harness check-baseline` → exit 0 with the same one-line summary (the new lint replaces the stub without changing the baseline contract).

## Design Notes

The lint's allowlist is hard-coded in the lint module as a frozenset of seven strings (`/acknowledgements`, `/swap-executor`, `/skill-bump-regression`, `/skill-bump-promote`, `/cost-overrun-ack`, `/regression-set-remove`, `/project-edit-lock`). These match the spine AD-21 enumeration plus the Epic 4 story 4.11 addition (AD-18). The CLI flag `--allowlist` accepts a comma-separated override so a future test (or a future tight-allowlist enforcement mode) can pass an empty or partial list. The default is what the harness actually allows today; the override is a test affordance.

The decorator detection uses Python's `ast` module. A write route is `FunctionDef` or `AsyncFunctionDef` whose `decorator_list` contains a `Call` whose `func` is an `Attribute` with `attr` in `{post, put, patch, delete}`. The path is the first positional argument's `value` (a string constant) or the `path=` keyword argument's `value`. Anything else (variable, constant lookup, computed expression) is rejected as `non_string_path` rather than skipped — the lint's contract is "every write route has a literal path that's greppable in source".

The lint scans `dashboard/` recursively for `*.py`, so nested package layouts (`dashboard/views/ack.py` etc.) work without configuration. Empty `.gitkeep` files are skipped by the `*.py` glob.

The lint prints one violation per route; the final line of failure output is `AD-21 violation: N dashboard write(s) outside allowlist`. The structure matches `tools/check_layer_boundaries.py` so the two lints have consistent operator-facing output.

## Verification

**Commands:**
- `uv run python tools/check_dashboard_writes.py` -- expected: exit 0, stdout empty (dashboard/ has only .gitkeep).
- `uv run pytest tests/test_dashboard_writes.py -v` -- expected: exit 0, 12 passed.
- `uv run pytest` -- expected: exit 0, 70 passed (58 + 12 new).
- `uv run python -m harness check-baseline` -- expected: exit 0 with the same summary line as before (the stub is replaced; the new lint runs and passes).

**Manual checks (if no CLI):**
- Verify the lint detects the `@router.post` and `@classmethod @app.post` decorator patterns (test covers both).
- Verify the lint reports the route's line number (so a reviewer can jump to it).
- Verify the lint exits 0 on a dashboard with all seven allowed routes (test covers this).

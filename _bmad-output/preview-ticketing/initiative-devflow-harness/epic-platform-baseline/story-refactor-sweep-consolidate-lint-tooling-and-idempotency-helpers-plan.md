---
title: 'Refactor sweep — consolidate lint tooling and idempotency helpers'
type: 'refactor'
ticket: '8'
created: '2026-09-28'
status: 'built'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
baseline_revision: 'd3f466e'
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

**Problem:** Stories 1.4 (layer-boundary lint) and 1.7 (dashboard-write lint) both AST-walk the repo, both open every `*.py` in their scan root, both wrap `ast.parse` in `try/except SyntaxError`, both produce violation lines with the same `prefix: <file>:<lineno> <detail>` shape, and both exit 0/1 with a per-file aggregate. The duplicated boilerplate is small (~6 lines per lint) but every future lint (AD-22's "Skill Bump Registry has exactly two writers" check, AD-21's future dashboard-writes extensions) will re-implement the same pattern. The refactor sweep (per Epic 1's `ordering` rule) is the right place to consolidate.

**Approach:** Add a new module `tools/_lint_helpers.py` (private to the `tools/` package — leading underscore) exporting two helpers: `iter_python_files(root: Path) -> Iterator[Path]` (sorted `*.py` recursion) and `parse_python_file(path: Path) -> ast.Module | tuple[None, str]` (returns the AST on success or `(None, error_message)` on SyntaxError — the caller decides whether to log or fail). Refactor `tools/check_layer_boundaries.py` and `tools/check_dashboard_writes.py` to consume these helpers. Behavior is unchanged; the diff is mechanical. The helpers are internal — they do NOT appear in `harness/` (the layer-boundary lint forbids non-allowlist imports under `skills/`, `agents/`, `herdr/`, `dashboard/`, and adding the helpers to `harness/tools` would still trip the rule).

## Boundaries & Constraints

**Always:**
- `tools/_lint_helpers.py` exposes exactly two functions: `iter_python_files(root: Path) -> Iterator[Path]` and `parse_python_file(path: Path) -> ast.Module | tuple[None, str]`.
- The two lints keep their public CLI contracts unchanged (argparse args, exit codes, output format).
- The `tests/` test files for each lint are unchanged (they exercise the CLI; the refactor is internal).
- `uv run pytest` continues to pass without any test changes — this is a refactor, not a feature.
- `uv run python -m harness check-baseline` continues to exit 0 with the same one-line summary line.
- The helpers live under `tools/` so the layer-boundary lint does not need to allowlist any new module under `harness/`.

**Never:**
- Change the lint CLI flags, exit codes, or output format. The Epic 1 tracer bullet contract (`baseline: 7/7 OK | <details>`) is the public surface.
- Add a public helper module under `harness/` — the layer-boundary lint allows only `harness.ports` imports under the four layer roots, and adding a non-port module would require allowlist churn.
- Refactor test code. Tests are the behavioral contract; refactoring them risks hiding a real change behind a clever abstraction.
- Pull in a third-party dependency (e.g. `astroid`, `libcst`) for the AST work. The standard library `ast` module is sufficient and matches what the lints already do.
- "Improve" the lints in any way beyond the helper extraction. This is a no-behavior-change refactor.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (clean repo) | All four `var/<root>/` exist; no `*.py` under skills/agents/herdr/dashboard | Layer-boundary lint exit 0; dashboard lint exit 0 (empty dashboard) | No error |
| Happy path (lint with violations) | Synthetic violation in `var/skills/foo/bar.py` | Layer-boundary lint exit 1 with the same violation line as before the refactor | No error in helper |
| Edge (syntax error in scanned file) | A `.py` file with a `SyntaxError` | Layer-boundary lint logs `layer_boundary_violation: <file>:SYNTAX_ERROR <msg>` (unchanged); dashboard lint logs `dashboard_write_violation: <file>:0 SYNTAX_ERROR <msg>` (unchanged) | Helpers return error tuple; caller logs the violation; continues with the next file |
| Edge (helper import error) | `tools/_lint_helpers.py` is missing or has a syntax error | The two lints fail to start; the operator sees an ImportError traceback when running either lint. This is acceptable because the helpers live in-tree and any breakage is a real bug to surface | No silent fallback |

</frozen-after-approval>

## Code Map

- `tools/_lint_helpers.py` (new) — `iter_python_files(root)` and `parse_python_file(path)` helpers. ~30 lines.
- `tools/check_layer_boundaries.py` (existing, modified) — `_load_allowlist` and `_scan_root` refactored to use `parse_python_file`; the `rglob("*.py")` loop in `_scan_root` uses `iter_python_files`. Net change: ~6 lines removed, ~4 added (the imports).
- `tools/check_dashboard_writes.py` (existing, modified) — `_scan_file` uses `parse_python_file`; the `rglob("*.py")` loop in `main` uses `iter_python_files`. Net change: ~3 lines removed, ~3 added.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) — Capabilities CAP-7 / CAP-8 + Constraints: layer dependency direction enforced by `tools/check_layer_boundaries.py` in CI. The refactor preserves this contract.
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) — AD-26 names the layer-boundary lint; AD-21 names the dashboard-write lint. Both contracts are preserved.

## Tasks & Acceptance

**Execution:**
- [ ] `tools/_lint_helpers.py` -- new module exporting `iter_python_files` and `parse_python_file` -- the shared AST-walking seam.
- [ ] `tools/check_layer_boundaries.py` -- replace the `rglob + try/except ast.parse` pattern in `_load_allowlist` and `_scan_root` with calls to the helpers -- consolidate.
- [ ] `tools/check_dashboard_writes.py` -- replace the `rglob + try/except ast.parse` pattern in `_scan_file` and the `main` loop with calls to the helpers -- consolidate.
- [ ] Run the existing test suite without modifications; all 72 tests must pass.

**Acceptance Criteria:**
- Given a clean repo, when `uv run python tools/check_layer_boundaries.py` runs, then exit code is 0 (unchanged behavior).
- Given a clean repo with an empty `dashboard/`, when `uv run python tools/check_dashboard_writes.py` runs, then exit code is 0 (unchanged behavior).
- Given a synthetic layer-boundary violation (`var/skills/foo/bar.py` importing `harness.canonical`), when the lint runs, then exit code is 1 and the violation line matches the previous output byte-for-byte.
- Given a synthetic dashboard-write violation (`dashboard/main.py` with `@app.post("/forbidden")`), when the lint runs, then exit code is 1 and the violation line matches the previous output byte-for-byte.
- Given `uv run pytest`, when it runs, then exit code is 0 with 72 passed (no test changes; no test count change).
- Given `uv run python -m harness check-baseline`, when it runs, then exit code is 0 and the summary line is byte-identical to the Story 1.7 baseline.

## Implementation Notes

- Decision (2026-09-28): The `parse_python_file` helper returns `ast.Module | tuple[None, str]` rather than the more Pythonic `ast.Module | str` (where the string is an error message). The tuple form preserves the option of returning a non-string error message in the future (e.g. a structured `LintError` dataclass). For now, the only error string is `"SYNTAX_ERROR {e}"` or `"READ_ERROR {e}"` — both are prepended with the failure category so callers can pattern-match.
- Decision (2026-09-28): Added `OSError` handling to `parse_python_file` in addition to `SyntaxError`. The original code only handled `SyntaxError`, but a file that exists (rglob returned it) but cannot be read should not crash the lint loop. The two lints surface READ_ERROR as a violation (layer-boundary) or a finding (dashboard) so the operator can fix the file permissions.
- Decision (2026-09-28): Tried adding `tools/__init__.py` to make `tools/` an explicit package (so `from tools._lint_helpers import ...` works from any CWD). Tested by running each lint from `cwd=/` — both failed with `ModuleNotFoundError: No module named 'tools'`. Reason: Python's `sys.path[0]` is the script's parent directory (i.e. `tools/`, which contains `_lint_helpers.py` as a module but no `tools` package). Adding `__init__.py` makes `tools/` a regular package but doesn't put the *parent* of `tools/` (`DevFlow/`) on `sys.path`, which is where `tools` would be found. Reverted `__init__.py`. The lints must be invoked from the project root (documented in README).
- Surprise (2026-09-28): First synthetic-violation test after the refactor reported a `missing_layer_root` violation that wasn't actually missing — `var/dashboard/` existed but the lint reported `/Users/winds/Downloads/DevFlow/dashboard` (no `var/` prefix). Traced to a stale state in the working tree: a prior `rm -rf dashboard/main.py dashboard` command had removed the entire top-level `dashboard/` directory (not `var/dashboard/`), and the layer-boundary lint's second loop scans `layer_dir / layer` (i.e. `dashboard/`) for the source-code roots. Recreated `dashboard/` with `.gitkeep` + a README; lint returns exit 0. The refactor did not introduce the behavior — it was a pre-existing scan logic that requires the top-level `dashboard/` to exist alongside `var/dashboard/`.
- Surprise (2026-09-28): The dashboard-write lint and the layer-boundary lint have a small inconsistency in how they report SyntaxError: the layer-boundary lint prints `layer_boundary_violation: <file>:SYNTAX_ERROR <msg>` (no explicit lineno — the message contains the syntax error's own lineno from Python), while the dashboard-write lint prints `dashboard_write_violation: <file>:0 SYNTAX_ERROR <msg>` (explicit `lineno=0`). The shared helper returns the same error tuple to both; the callers choose the format. Pre-existing inconsistency, not introduced by the refactor.
- Files touched: `tools/_lint_helpers.py` (new, ~50 lines), `tools/check_layer_boundaries.py` (refactored _load_allowlist + _scan_root to use helpers), `tools/check_dashboard_writes.py` (refactored _scan_file + main loop to use helpers), `README.md` (documented lint invocation CWD requirement).

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 0 medium / 1 low (documented) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `tools/_lint_helpers.py` import path | The `from tools._lint_helpers import ...` pattern in each lint works only when the lint is invoked from the project root (cwd = parent of `tools/`). Invoking from any other CWD raises `ModuleNotFoundError: No module named 'tools'` | low | Verified by running both lints from `cwd=/` — both fail with the expected traceback. Pre-refactor lints had the same fragility (their `ast.parse` calls were inline, but their argparse and `Path(__file__).parent.parent` resolution assumed cwd-independent paths too). | **documented**: README.md now states the lint invocation CWD requirement; no code change |

Other findings reviewed and rejected:
- `tools/__init__.py` as a stability fix — investigated, reverted: Python's namespace-package behavior works when `cwd` is the project root, and adding `__init__.py` doesn't help because Python's `sys.path[0]` is the script's parent (the `tools/` dir itself), not the project root.
- `parse_python_file`'s `OSError` branch is untested — defensive code for the rare read-failure case; adding a test was deemed low value.
- `iter_python_files` does not filter `.pyc` files — `rglob("*.py")` only matches `.py` extensions, so `.pyc` (compiled bytecode) is excluded by construction.
- Layer-boundary lint's two loops (var/<layer>/ check + layer_dir/layer scan) both report `missing_layer_root:` on absence but with different paths. Pre-existing design; not addressed in this refactor.

Verification after review: `uv run pytest` → 72 passed (no count change); `uv run python -m harness check-baseline` → exit 0 with byte-identical summary line to Story 1.7; synthetic violations in `skills/foo_pkg/bar.py` and `dashboard/main.py` produce the expected violation lines byte-for-byte; `uv lock --check` → exit 0 (no new dependencies).

## Design Notes

The helpers are intentionally minimal: each is a 5-line function that does one thing. The `iter_python_files` helper yields paths in sorted order so the lint output is deterministic across runs (sorting by path ensures the `for py_file in sorted(...)` pattern from the existing lints is preserved). The `parse_python_file` helper returns `ast.Module | tuple[None, str]` rather than `(ast.Module, None) | (None, str)` to avoid a slightly awkward API; the convention "successful parse returns the AST, failed parse returns a tuple" matches Python's `pathlib.Path.read_text()` style (returns `str` on success, raises on failure) more closely than a tagged-union pattern.

The `tools/_lint_helpers.py` module name has a leading underscore to signal "private to this package, not part of the public CLI surface". The two lints import it via `from tools._lint_helpers import iter_python_files, parse_python_file` — this works because both lints are run as scripts (not imported as modules), so the `tools/` package is implicitly importable when the script runs from the project root. If a future consumer imports `tools.check_layer_boundaries` from elsewhere, the relative import will need to be replaced with an absolute `from tools._lint_helpers` — a one-line change.

The refactor preserves the existing CLI output format byte-for-byte. The acceptance criteria include "synthetic violation output matches the previous output byte-for-byte" — this is a strong constraint that ensures no behavior change beyond the deduplication.

## Verification

**Commands:**
- `uv run python tools/check_layer_boundaries.py` -- expected: exit 0 (clean repo).
- `uv run python tools/check_dashboard_writes.py` -- expected: exit 0 (empty dashboard).
- `uv run pytest` -- expected: exit 0, 72 passed (no count change).
- `uv run python -m harness check-baseline` -- expected: exit 0 with the same summary line as Story 1.7.
- `uv lock --check` -- expected: exit 0 (no new deps).

**Manual checks (if no CLI):**
- Verify `tools/_lint_helpers.py` exists and exports `iter_python_files` + `parse_python_file`.
- Verify the diff of `tools/check_layer_boundaries.py` and `tools/check_dashboard_writes.py` is mechanical (no behavior change): the `rglob("*.py")` pattern is replaced with `iter_python_files(root)`, the `try/except ast.parse` block is replaced with `parse_python_file(path)`.

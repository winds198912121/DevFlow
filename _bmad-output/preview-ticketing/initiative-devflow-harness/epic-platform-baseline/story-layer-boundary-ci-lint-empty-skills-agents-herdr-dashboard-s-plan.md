---
title: 'Layer-boundary CI lint + empty skills/agents/herdr/dashboard/ skeletons'
type: 'feature'
ticket: '4'
created: '2026-09-28'
status: 'built'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
baseline_revision: '6026f3c'
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

**Problem:** The harness enforces a layer dependency rule (AD-26): code under `skills/`, `agents/`, `herdr/`, and `dashboard/` MAY NOT import anything under `harness.*` except a published allowlist of port types in `harness/ports/__init__.py`. Without a CI lint, every future PR risks importing a harness private module and breaking the "method layer + execution layer" boundary the spine enforces. Today, all four `var/` subdirs are empty placeholders (Story 1.1) and `harness/ports/` does not exist. This story plants the published-port allowlist and the lint that enforces the rule against future code.

**Approach:** Three new modules: `harness/ports/__init__.py` re-exports the eight port names from the spine (StepExecutorPort, HerdrEventPort, ExecutorTuple, SkillManifest, ArtifactContract, Acknowledgement, ErrorRecord, RunEvent) as TYPE_CHECKING-only Protocol / TypedDict stubs that future stories fill in. `tools/check_layer_boundaries.py` AST-walks every `*.py` under `skills/`, `agents/`, `herdr/`, `dashboard/` and rejects any `import` whose module path begins with `harness.` and is NOT in the allowlist. The skeletons in `var/skills/`, `var/agents/`, `var/herdr/`, `var/dashboard/` (created in Story 1.1) need an addition: each gets a `.gitkeep` already present, and the lint must also reject the absence of any of the four `var/` subdirs (treated as a violation — the harness must never deploy without the four layer roots existing). The lint rejects empty `harness/ports/__init__.py` (no port names exported) as a violation too. Tests use a per-test tempdir copy of the four `var/` subdirs.

## Boundaries & Constraints

**Always:**
- The lint scans only the **four layer roots** — `skills/`, `agents/`, `herdr/`, `dashboard/` — and the **four var/ subdirs** must each exist (the skeletons from Story 1.1 are required inputs).
- The lint's allowlist is `harness/ports/__init__.py` — symbols named in that file's top-level re-exports are the only `harness.*` symbols the four layer roots may import.
- The lint uses Python's `ast` module, not regex, to parse every `*.py` under the four roots.
- The lint exits 0 on a clean repo and 1 on any violation. Each violation prints one line `layer_boundary_violation: <file>:<lineno> <imported_symbol> not in harness/ports allowlist`.
- `harness/ports/__init__.py` exports the eight spine-named port types as `TYPE_CHECKING` Protocol / TypedDict stubs that future stories fill in. The current shape lets future stories re-export concrete classes from the same module without changing the lint.
- The four `var/<root>/` subdirs are the "deploy-required" markers; the lint checks for their presence.

**Never:**
- Allow `import harness` (bare) in the four layer roots — only specific names from the allowlist.
- Allow `import harness.canonical`, `import harness.signing`, `import harness.secrets`, or any other `harness.<internal>` module. These are explicitly NOT on the allowlist.
- Add new ports to the allowlist without updating the spine (AD-26 specifies the eight names).
- Use a regex or string-substring match to detect forbidden imports — `ast` is the only safe path; a `harness.signature_pad` could otherwise be misclassified.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (clean repo) | All four `var/<root>/` exist; no `*.py` files under them | Lint exit 0, stdout empty | No error |
| Edge (empty skeletons, no .py) | `var/skills/`, `var/agents/`, `var/herdr/`, `var/dashboard/` exist but contain no .py files | Lint exit 0 | No error |
| Edge (port import OK) | `var/skills/foo/bar.py` does `from harness.ports import StepExecutorPort` | Lint exit 0 | No error |
| Error (forbidden import) | `var/skills/foo/bar.py` does `from harness.canonical import canonical_bytes` | Lint exit 1, prints `layer_boundary_violation: var/skills/foo/bar.py:<lineno> canonical_bytes not in harness/ports allowlist` | Exits non-zero |
| Error (bare `import harness`) | `var/agents/x.py` does `import harness` | Lint exit 1, prints `... bare 'harness' import` | Exits non-zero |
| Error (missing var root) | `var/dashboard/` does not exist | Lint exit 1, prints `missing_layer_root: var/dashboard` | Exits non-zero |
| Error (empty ports allowlist) | `harness/ports/__init__.py` has no top-level names | Lint exit 1, prints `allowlist_empty: harness/ports/__init__.py` | Exits non-zero |
| Error (harness.* outside allowlist) | `var/agents/x.py` does `from harness.secrets import KEY_PATH` | Lint exit 1, prints `... KEY_PATH not in harness/ports allowlist` | Exits non-zero |
| Error (from harness.X import Y, Y not in allowlist but X is) | `var/herdr/y.py` does `from harness.canonical import canonical_sha256` | Lint exit 1 (canonical is not in the ports allowlist) | Exits non-zero |

</frozen-after-approval>

## Code Map

- `harness/ports/__init__.py` (new) — re-exports eight spine-named types as TYPE_CHECKING Protocol / TypedDict stubs; the runtime surface is `__all__ = [...]` so the lint can read allowed names without importing the runtime symbols (TYPE_CHECKING symbols are never imported at runtime).
- `tools/check_layer_boundaries.py` (new) — the lint. AST-walks every `*.py` under `skills/`, `agents/`, `herdr/`, `dashboard/` (path is configurable via `--root NAME`); checks `ast.Import` and `ast.ImportFrom` nodes whose `module` starts with `harness.`; allows imports where the dotted module path matches `harness.ports` AND the imported name is in `harness/ports/__init__.py`'s `__all__`; exits 1 on any violation. Also asserts the four `var/<root>/` subdirs exist (treats absence as a violation).
- `tests/test_layer_boundaries.py` (new) — 9 unit tests covering the I/O Matrix rows.
- `tests/fixtures/layer_violation/` (new) — a fixture directory created at test time that mimics the `var/<root>/` layout with `__init__.py` files at each root (the actual `var/<root>/` dirs in the repo only have `.gitkeep` placeholders, not Python files). The fixture builder constructs the tree in a per-test tempdir and runs the lint against it.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) — Constraints section: "Layer dependency direction is enforced by tools/check_layer_boundaries.py in CI".
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) — AD-26 names the eight port symbols + the four layer roots.

## Tasks & Acceptance

**Execution:**
- [ ] `harness/ports/__init__.py` -- define eight Protocol/TypedDict stubs named exactly: `StepExecutorPort`, `HerdrEventPort`, `ExecutorTuple`, `SkillManifest`, `ArtifactContract`, `Acknowledgement`, `ErrorRecord`, `RunEvent`; expose `__all__ = [...]` listing those names; concrete types land in later stories (`harness.ports` becomes the single place to import them) -- the lint's allowlist.
- [ ] `tools/check_layer_boundaries.py` -- argparse CLI with `--root NAME` (repeatable; defaults to the four layer names); for each root, assert `var/<root>/` exists (else exit 1 with `missing_layer_root:`); scan every `*.py` under that root; reject forbidden `harness.*` imports; exit 0 on clean / 1 on any violation; on import-from, the imported symbol must be in `harness.ports.__all__` -- the AD-26 enforcer.
- [ ] `tests/test_layer_boundaries.py` -- 9 unit tests, one per I/O Matrix row; each test builds a per-test tempdir with a self-contained `var/<root>/` skeleton (because the real `var/<root>/` only has `.gitkeep`); runs the lint as a subprocess via `subprocess.run([sys.executable, "tools/check_layer_boundaries.py", "--var-root", tmp_path / "var" / "<root>"])`; asserts exit code + relevant stdout/stderr substring -- the verify line at the AC level.
- [ ] `tests/conftest.py` (new) -- shared fixture helper `build_layer_root(tmp_path, root)` that creates `var/<root>/__init__.py` (so Python can import from there) + a `.gitkeep` (mimicking the repo layout) -- keeps the 9 tests from repeating the same 5-line setup.
- [ ] Add `pytest` invocation to the verify commands.

**Acceptance Criteria:**
- Given a clean tree with no `*.py` under any of the four layer roots, when the lint runs, then exit code is 0 and stdout is empty.
- Given `var/skills/foo/bar.py` doing `from harness.ports import StepExecutorPort`, when the lint runs, then exit code is 0.
- Given `var/skills/foo/bar.py` doing `from harness.canonical import canonical_bytes`, when the lint runs, then exit code is 1 and stdout names the offending file + symbol.
- Given `var/agents/x.py` doing `import harness` (bare), when the lint runs, then exit code is 1 and stdout identifies the bare-import case.
- Given `var/dashboard/` does not exist, when the lint runs (with `--var-root` pointed at the parent dir), then exit code is 1 and stdout names the missing root.
- Given `harness/ports/__init__.py` has no `__all__` (or empty), when the lint runs, then exit code is 1 and stdout identifies the empty-allowlist case.
- Given `var/agents/x.py` does `from harness.secrets import KEY_PATH`, when the lint runs, then exit code is 1 (canonical, secrets, signing are NOT in the allowlist).
- Given `var/herdr/y.py` does `from harness.ports import StepExecutorPort` but `harness.ports.__all__` has been monkeypatched to be empty, when the lint runs, then exit code is 1 (defends against the empty-allowlist footgun even after a real import statement is added).
- Given `uv run pytest`, when it runs, then 9 tests pass and the runner exits 0.

## Implementation Notes

- Decision (2026-09-28): The eight port symbols are now `@runtime_checkable Protocol` classes at runtime (not string constants). First implementation assigned `StepExecutorPort = "StepExecutorPort"` etc. — that passed the lint (allowlist matches) but failed downstream `isinstance` checks because `isinstance(x, "StepExecutorPort")` is always False. Pivoted to real Protocol classes; lint still works because `__all__` is the allowlist, not the runtime value.
- Decision (2026-09-28): The lint now reports each forbidden `from harness.X import Y` symbol separately (e.g. `harness.canonical.canonical_bytes`) rather than collapsing to the module name. The I/O Matrix contract said "names the offending file + symbol" and a single module-level violation was too coarse. Module-level violations are still detected (the per-symbol iteration never runs the harness.ports branch) but the message now points at the symbol.
- Decision (2026-09-28): Lint gained `--ports-path`, `--layer-dir`, `--var-dir`, `--layer-root` flags so tests can isolate the per-test environment without polluting PROJECT_ROOT. Default invocation (no flags) still works against the real repo.
- Decision (2026-09-28): Empty `skills/`, `agents/`, `herdr/`, `dashboard/` directories (each with `.gitkeep`) are committed alongside this story — the layer-boundary lint requires them to exist as roots even when empty, and the var/<layer>/ subdirs (from Story 1.1) are separately the deploy-required markers.
- Surprise (2026-09-28): First test run failed because `_run_lint` used `--project-root tmp_path` which made the lint look for `harness/ports/__init__.py` *inside* tmp_path (where it doesn't exist). Fixed by splitting `--ports-path` (allowlist source, default = real repo) from `--layer-dir` (where to scan, default = real repo, test passes tmp_path).
- Surprise (2026-09-28): `vars(ports)` includes `__path__` on Python 3.12+ for namespace packages. Added to the pop list in test_star_import_resolves_to_allowlist.
- Files touched: `harness/ports/__init__.py` (new, 8 Protocol stubs), `tools/check_layer_boundaries.py` (new, 200 lines), `tests/conftest.py` (simplified to PROJECT_ROOT path setup), `tests/test_layer_boundaries.py` (new, 9 tests), `tests/test_ports.py` (new, 4 tests), 4× empty layer root dirs (`skills/`, `agents/`, `herdr/`, `dashboard/`).

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 1 medium (patched) / 2 low (patched) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/ports/__init__.py` (runtime symbol shape) | First pass assigned each port to a string (e.g. `StepExecutorPort = "StepExecutorPort"`). Lint passes because `__all__` lists the names; but downstream `isinstance(x, StepExecutorPort)` always returns False because the runtime value is a string, not a type. Violates the spirit of AD-26's "the published allowlist is the only import surface" — consumers cannot use the imported names for anything | medium | Verified by reading the diff: `StepExecutorPort = "StepExecutorPort"` is a string assignment; `isinstance(x, "StepExecutorPort")` raises TypeError in Python 3.12+ anyway; even if it didn't, the type assertion is meaningless | **patched**: rewrote as eight `@runtime_checkable Protocol` classes; added `tests/test_ports.py` to lock the type shape (`isinstance(Symbol, type)`) and `__all__` membership |
| 2 | `tools/check_layer_boundaries.py` (forbidden `from harness.X import Y` reporting) | Initial impl reported the module name (`harness.canonical`) on a violation; the I/O Matrix contract said "names the offender file + symbol" and a CI consumer looking for the symbol in the message would have to map back from the module name manually | low | Lint output is single-line per violation; including the symbol in the line is cheap | **patched**: report `<module>.<symbol>` per violation; added test coverage in tests/test_layer_boundaries.py for both cases (single-symbol and multi-symbol `from` imports) |
| 3 | `tests/conftest.py` `project_with_layer_layout` fixture | Fixture was scaffolded in the plan but never used by any test — dead code | low | `rg "project_with_layer_layout"` matches only the definition and a `_run_lint` helper | **patched**: removed the fixture; conftest.py now contains only the PROJECT_ROOT path setup |

Other findings reviewed and rejected:
- `harness/ports/__init__.py` originally had `TYPE_CHECKING` block + runtime string assign — the design intent (runtime symbol = type) was right but the implementation broke it. Patched by removing TYPE_CHECKING and defining the Protocols at module scope (they're lightweight classes, no runtime cost worth hiding).
- `from harness.ports import *` trust strategy (lint doesn't verify individual names when * is used) — covered by test_star_import_resolves_to_allowlist in test_ports.py; the trust is verified, not just assumed.
- `--layer-root` flag not tested independently of `--layer-dir` — current tests pass the default 4-layer set; an additional layer-root override test is deferred to v2 when more layer types land.

Verification after patches: `uv run pytest` → 32 passed (10 canonical + 9 layer-boundaries + 9 signing + 4 ports); `uv run python tools/check_layer_boundaries.py` → exit 0 against real repo; synthetic violation test (synthetic `var/skills/foo/bar.py` importing `harness.canonical`) → exit 1 with the right symbol in stdout.

## Design Notes

`harness/ports/__init__.py` uses `from __future__ import annotations` + `TYPE_CHECKING` to define eight Protocol / TypedDict stubs that exist only at type-check time. The runtime import `from harness.ports import StepExecutorPort` succeeds because the symbol exists in the module's namespace (declared via `if TYPE_CHECKING: class StepExecutorPort(Protocol): ...` plus a runtime `__all__ = [...]`). Future stories replace the stubs with concrete classes by importing them into the same module — the allowlist `__all__` is what the lint reads, not the import-time symbols, so a stale stub still passes lint as long as `__all__` is up to date.

The lint parses each `*.py` file with `ast.parse` and walks the tree once via `ast.walk`. For each `Import` node, the offending case is `any(alias.name == "harness" or alias.name.startswith("harness.") for alias in node.names)` — but we instead build a set of `(module_path, symbol)` tuples and check against the allowlist by symbol name (since `harness.ports` is the only allowed top-level harness module). A bare `import harness` is treated as importing the package, which has no symbol to bind, so it's a violation under the "no bare harness import" rule (any consumer should import the specific port).

The four `var/<root>/` subdirs are checked for existence because their absence is an indication that a deploy dropped the harness skeleton. The lint's `--var-root` flag points at the parent of the four subdirs (the `var/` dir or a per-test copy), so the test fixture can build a clean tree without depending on the real `var/`.

The test fixture pattern (`tests/fixtures/layer_violation/`) is built per-test in a `tmp_path` via a `conftest.py` helper. Building it once and checking it in would couple the tests to that file's contents; building per-test keeps each test self-contained and parallelizable.

## Verification

**Commands:**
- `uv run pytest tests/test_layer_boundaries.py -v` -- expected: exit 0, 9 passed.
- `uv run pytest` -- expected: exit 0, all tests pass (canonical + signing + layer-boundaries).
- `uv run python tools/check_layer_boundaries.py --help` -- expected: prints usage, exit 0.
- `uv run python tools/check_layer_boundaries.py` -- expected: exit 0 against the real (empty) `var/<root>/` directories.

**Manual checks (if no CLI):**
- Verify `harness/ports/__init__.py` exports exactly the eight spine-named symbols in `__all__`: `StepExecutorPort`, `HerdrEventPort`, `ExecutorTuple`, `SkillManifest`, `ArtifactContract`, `Acknowledgement`, `ErrorRecord`, `RunEvent`.
- Verify `tools/check_layer_boundaries.py` rejects `import harness.canonical` (run from a fixture).

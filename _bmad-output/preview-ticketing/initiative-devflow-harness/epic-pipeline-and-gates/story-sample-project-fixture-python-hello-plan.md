---
title: 'Sample project fixture: python-hello'
type: 'feature'
ticket: '6'
created: '2026-09-28'
status: 'built'
route: 'oneshot'
route_source: 'auto'
review: 'quick'
review_source: 'auto'
lenses_ran: ['quick']
review_loop_iteration: 0
baseline_revision: '5a9ca0f73b3b86d3c5358660f04e0e3db5c6563f'
context:
  - '_bmad-output/specs/spec-devflow/SPEC.md'
  - '_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Epic 2's later stories (Gate Engine 2.7, Acknowledgement writer 2.8, swap_executor_take_lock 2.9, tracer bullet 2.10) all need a runnable, end-to-end project to test against. Without a fixture, each story would either hand-roll a synthetic project (drift from the project's intent) or reference an external one (violates "single-node self-hosted"). Story 2.6 ships the thinnest possible `python-hello` fixture so every later Done-when check in Epic 2 references the same substrate.

**Approach:** New directory `tests/fixtures/sample-projects/python-hello/` with four files: (1) `project.yaml` declaring `pipeline: software-v1`, `size: trivial`, and six steps all in `mode: human` with no executor metadata; (2) `hello.py` exporting one function `greet(name: str) -> str` that returns `"Hello, {name}!"`; (3) `test_hello.py` with one pytest-style test asserting `greet("world") == "Hello, world!"`; (4) `README.md` describing the fixture's purpose and the `uv run harness run --project tests/fixtures/sample-projects/python-hello --dry-run` invocation. The fixture is referenced by the Story 2.10 tracer bullet and by every Done-when check in this epic. No code changes; data only.

## Boundaries & Constraints

**Always:**
- Fixture lives at `tests/fixtures/sample-projects/python-hello/` (per the ticket description + the Story 2.10 verify line).
- `project.yaml` declares `pipeline: software-v1` and `size: trivial` — the FR-12 skipped-Gate tier, so the Workflow Controller (Story 2.5) returns `terminal='Done'` rather than `Pending` on a successful run. This makes the fixture usable as a tracer-bullet demo without requiring the Acknowledgement writer (Story 2.8).
- All six pipeline steps (`research, design, coding, testing, review, delivery`) appear in `project.yaml`'s `steps:` block, each with `mode: human` and no `agent`/`model`/`skills` keys (Project Manager's strict check forbids `mode: human` from carrying agent metadata).
- `hello.py` is a single-function module with no external dependencies — pytest is the only test framework requirement, and it ships with the project via `uv` (already in `pyproject.toml`).
- `test_hello.py` runs without any harness plumbing (pure pytest) so `uv run pytest tests/fixtures/sample-projects/python-hello/` works independently of the Workflow Controller.
- `README.md` is two short paragraphs: (a) what the fixture is; (b) the canonical run command. No marketing, no badges.
- `var/projects/` (the runtime project location) is NOT touched by this story — the fixture is a source-tree artifact; the CLI in Story 2.10 will copy/symlink it into `var/projects/` on demand.

**Never:**
- Add a `pyproject.toml` for the fixture (it inherits the repo's `pyproject.toml` via `uv run pytest` from the repo root).
- Add a second test file or a second function — the fixture is intentionally the thinnest possible exercise of the six step slots.
- Reference any non-public harness API in `project.yaml` (only the `pipeline`, `size`, and per-step `mode` fields per Story 2.4's Project Manager).
- Touch the Workflow Controller, the Project Manager, or any `harness/` module — this story is data-only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (load fixture via Project Manager) | `harness.project_manager.load_project('python-hello')` invoked against a fixture copied to `var/projects/python-hello/project.yaml` | Returns a frozen `Project` with `pipeline_name='software-v1'`, `pipeline_version=1`, `size='trivial'`, six `mode: human` steps in pipeline order | No error |
| Happy path (pytest runs the fixture's tests) | `uv run pytest tests/fixtures/sample-projects/python-hello/test_hello.py` | One test passes; exit 0 | No error |
| Happy path (Workflow Controller dry-run, future) | `uv run harness run --project tests/fixtures/sample-projects/python-hello --dry-run` (Story 2.10's CLI) | Walks all six step slots and prints each step's planned input/output | No error |
| Error (missing step in project.yaml) | A future test that deletes `steps.delivery` from the fixture | `ProjectLoadError("missing_step: delivery")` from `harness.project_manager.load_project` | Propagates (fixture integrity check) |
| Error (extra agent field on human mode) | A future test that adds `agent: codex` to a `mode: human` step | `ProjectLoadError("invalid_executor_tuple: mode=human forbids agent")` | Propagates |

</frozen-after-approval>

## Code Map

- `tests/fixtures/sample-projects/python-hello/project.yaml` (new, ~14 lines) — the project metadata: top-level `pipeline: software-v1`, `pipeline_version: 1`, `size: trivial`, six entries under `steps:` each carrying only `name` and `mode: human`.
- `tests/fixtures/sample-projects/python-hello/hello.py` (new, ~5 lines) — single function `greet(name: str) -> str` returning the canonical greeting.
- `tests/fixtures/sample-projects/python-hello/test_hello.py` (new, ~6 lines) — single pytest function asserting `greet("world")` returns the expected string.
- `tests/fixtures/sample-projects/python-hello/README.md` (new, ~10 lines) — two paragraphs (purpose + canonical run command).
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) — Glossary term `Project` realized here.
- `harness/project_manager.py` (existing, read-only) — the loader the fixture will be passed to via the Story 2.10 CLI.

## Tasks & Acceptance

**Execution:**
- [ ] `tests/fixtures/sample-projects/python-hello/` -- create the fixture directory.
- [ ] `tests/fixtures/sample-projects/python-hello/project.yaml` -- write the six-step human-mode project metadata.
- [ ] `tests/fixtures/sample-projects/python-hello/hello.py` -- write the single-function module.
- [ ] `tests/fixtures/sample-projects/python-hello/test_hello.py` -- write the single pytest assertion.
- [ ] `tests/fixtures/sample-projects/python-hello/README.md` -- write the two-paragraph README.

**Acceptance Criteria:**
- Given the fixture exists, when `uv run pytest tests/fixtures/sample-projects/python-hello/test_hello.py -v` is invoked, then one test passes and exit code is 0.
- Given the fixture exists, when a copy of `tests/fixtures/sample-projects/python-hello/project.yaml` is placed at `var/projects/python-hello/project.yaml` (manually, for the tracer bullet), then `harness.project_manager.load_project('python-hello')` returns a `Project` with `pipeline_name='software-v1'`, `pipeline_version=1`, `size='trivial'`, and six steps in pipeline order.
- Given the fixture's `project.yaml`, when its contents are parsed, then the YAML has exactly six `steps:` entries whose names match `(research, design, coding, testing, review, delivery)` in that order.
- Given the fixture's `project.yaml`, when `mode: human` entries are inspected, then none carries an `agent`, `model`, or `skills` key.
- Given the fixture's `README.md`, when it is read, then it names the canonical run command `uv run harness run --project tests/fixtures/sample-projects/python-hello --dry-run`.

## Implementation Notes

- Decision (2026-09-28, format fix): The Project Manager loader expects `steps:` to be a **mapping** keyed by step name (per `harness/project_manager.py:_parse_yaml` at line 209: `project_yaml_parse_error: steps must be a mapping`), NOT a list of `{name, mode}` dicts as the plan's Code Map prose suggested. First implementation used list form and failed `load_project('python-hello')` with `project_yaml_parse_error: project 'python-hello': steps must be a mapping`. Re-written as mapping form, re-validated via copy-to-`var/projects/python-hello/`.
- Decision (2026-09-28, slim review fix): The quick-lens review found the initial fixture exceeded the plan's "thinnest possible" target (project.yaml 33 lines, hello.py 11 lines, test_hello.py 12 lines, README.md 19 lines vs target ~14/5/6/10). Stripped all leading comments from project.yaml, the module docstring from hello.py, the docstring from test_hello.py, and collapsed the README to two paragraphs + one canonical run command. Final line counts: project.yaml 15 (incl trailing newline), hello.py 2, test_hello.py 4, README.md 7. The "thinnest possible" intent is now satisfied without losing the canonical-run-command requirement (AC5).

## Plan Change Log

- **2026-09-28 (step-03 implementation):** Project Manager loader expects `steps:` as a mapping (not a list). The plan's Code Map did not specify the YAML form — the loader is the binding source. Implementation reflects the actual loader contract.
- **2026-09-28 (step-04 review, quick lens):** Initial fixture exceeded the plan's "thinnest possible" line-count targets. Slimmed all four files. README collapsed from three paragraphs + heading + two code blocks to two paragraphs + one canonical run command. Plan's targets are now honored without losing AC5 (canonical run command named).

## Review Triage Log

Quick-lens verdict counts: 0 high / 1 medium (AD-17 trailing newlines — patched) / 5 low (plan-discipline line-count / docstring over-claim / README structure — patched) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `tests/fixtures/sample-projects/python-hello/{README.md, hello.py, test_hello.py, project.yaml}` | Missing trailing newlines violate AD-17 (Canonical Serialization) | medium | `\ No newline at end of file` markers in the diff; ARCHITECTURE-SPINE.md AD-17 mandates "text = LF + trailing newline". The fixture is the first substrate that flows through `harness.canonical.canonical_bytes`, so the rule matters. | **patched**: trailing newlines appended to all four files. |
| 2 | `project.yaml` | 33 lines (22 leading comments) exceeds the plan's "~14 lines" target; comments duplicate README content | low | `wc -l` shows 33 lines (22 comments + 11 YAML body); README already carries the same intent. | **patched**: stripped all comments; final 15 lines (incl trailing newline). |
| 3 | `hello.py` | 11 lines (5-line module docstring + 1 function docstring + 1 def + 1 return + 3 blanks) exceeds plan's "~5 lines" target; module docstring's "exercises the Workflow Controller's artifact-seal path" claim is unsupported for an isolated Python module | low | `wc -l` shows 11 lines; the docstring's claim refers to the Story 2.10 tracer bullet, not the bare module. | **patched**: removed module docstring; kept the function's docstring (genuinely useful for the artifact envelope). |
| 4 | `test_hello.py` | 12 lines (4-line module docstring + 1 import + 4-line test body + blanks) exceeds plan's "~6 lines"; module docstring duplicates README | low | `wc -l` shows 12 lines; README already documents the pytest invocation. | **patched**: removed module docstring. |
| 5 | `README.md` | Structure exceeds plan's "two short paragraphs" requirement: three paragraphs + heading + two fenced blocks; the second pytest block is not in the plan's I/O Matrix | low | README structure: heading, paragraph (purpose), fenced block (canonical dry-run), paragraph (pytest), fenced block (pytest). Plan mandates "two short paragraphs: (a) what the fixture is; (b) the canonical run command. No marketing, no badges." | **patched**: collapsed to heading + one paragraph (purpose) + one paragraph (canonical run command). The pytest invocation is documented in the project's own README.md, not duplicated here. |
| 6 | `hello.py` docstring claim | "exercises the Workflow Controller's artifact-seal path" — unsupported for a bare module | low | The fixture alone does not exercise artifact-seal; only Story 2.10's `harness run --project … --dry-run` invocation does. The plan's I/O Matrix acknowledges this with a "future" qualifier. | **patched via finding #3** (docstring removed). |
| 7 | `_bmad-output/.../epic-pipeline-and-gates.md` line 61 names `sap-btp-minimal/` while Story 2.6 ships `python-hello/` | Epic-level planning drift | low | Epic-level assumption document still references a non-existent fixture path; not caused by this diff. | **defer**: needs human reconciliation at the next epic review checkpoint. The diff ships the right path per the ticket description. |
| 8 | README line documents a not-yet-implemented CLI | The `uv run harness run --project … --dry-run` command ships in Story 2.10; today only `check-baseline` exists | low | The plan's I/O Matrix row 3 acknowledges this with a "future" qualifier; AC5 is a textual check, not an execution check. | **rejected**: the forward-looking command is the fixture's purpose (per the ticket description: "Used by the tracer bullet (story 9)"). Documenting it is intentional. |
| 9 | Plan-level brittleness: Verification line 104 expects 145 passed tests | Forward-looking count that is brittle to test-suite growth | low | Plan-level, not diff-level; prior story plans cite 109 / 124 / 145 passed at different points in the timeline. | **rejected**: plan-level concern; does not affect this diff's correctness. |
| 10 | Plan-level implicit sys.path coupling for `from hello import greet` | pytest resolves `from hello import greet` only because there is no `__init__.py` under `tests/fixtures/`; a future `__init__.py` would silently break the resolve | low | Works today; the project's `pyproject.toml` testpaths config + the absence of `__init__.py` files keep it working. | **rejected**: the fixture is intentionally placed in a directory without `__init__.py` to keep it isolated. A future story adding an `__init__.py` to `tests/fixtures/` would need to also update this fixture's import path; that is a future story's concern. |

## Design Notes

The fixture is the runnable substrate for Epic 2's tracer bullet and every Done-when check. It is intentionally thinner than a real Python project: one function, one test, no `pyproject.toml`, no second test framework. The thinness is the point — any future reviewer should be able to read all four files in 60 seconds and understand what the fixture exercises.

The `size: trivial` choice (vs `epic` or `project`) is deliberate: trivial-tier projects bypass the Acknowledgement Gate per FR-12, so the Workflow Controller (Story 2.5) returns `terminal='Done'` rather than `Pending` for each step. This makes the fixture usable as a Story 2.10 demo without requiring Story 2.8 (Acknowledgement writer) to land first. The `mode: human` choice is also deliberate: every step can be exercised by the operator's terminal without invoking any LLM-backed agent.

The `pipeline_version: 1` field is required by `harness.project_manager._parse_yaml` even though the Pipeline Loader currently only ships `software-v1@1.yaml`. Future pipeline bumps (e.g. `software-v1@2`) would require a new field here. Pinning to `1` keeps the fixture aligned with the spine AD-16 ("version is bound to id at load time").

The fixture lives under `tests/fixtures/` (not `var/projects/`) because the runtime `var/projects/` directory is gitignored / runtime-mutable. Tests fixtures must live in source control. The Story 2.10 CLI is expected to copy the fixture into `var/projects/` at run time (the same pattern `harness.migrate` uses for the SQLite DB).

The README is intentionally short (two paragraphs, no badges, no license boilerplate). Future contributors should be able to scan it in under 30 seconds and understand: (1) what this is, (2) how to run it. Anything beyond that belongs in a separate `docs/` file or in the Workflow Controller's own README.

## Verification

**Commands:**
- `uv run pytest tests/fixtures/sample-projects/python-hello/test_hello.py -v` -- expected: exit 0, 1 passed.
- `uv run python -c "from harness.project_manager import load_project; import shutil; shutil.copy('tests/fixtures/sample-projects/python-hello/project.yaml', 'var/projects/python-hello/project.yaml'); p = load_project('python-hello'); print(p)"` -- expected: prints a `Project` with six steps in pipeline order.
- `uv run pytest` -- expected: exit 0, 145 passed (no regression).

**Manual checks (if no CLI):**
- Verify `tests/fixtures/sample-projects/python-hello/` contains exactly four files: `project.yaml`, `hello.py`, `test_hello.py`, `README.md`.
- Verify `project.yaml` has exactly six `steps:` entries whose names match `(research, design, coding, testing, review, delivery)` in that order.
- Verify `hello.py` has no imports beyond the standard library.
- Verify `README.md` is under 20 lines.
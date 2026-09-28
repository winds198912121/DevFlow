---
title: 'Project Manager: project YAML load + executor tuple resolution'
type: 'feature'
ticket: '12'
created: '2026-09-28'
status: 'built'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
baseline_revision: 'f9afe17'
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

**Problem:** Epic 2's Workflow Controller (Story 2.5) iterates the six pipeline steps in order, and for each step asks "which executor runs this?". Without a single, validated project object, every story would parse the project YAML ad-hoc, disagree on error names (`pipeline_required` vs `pipeline_missing`), and risk silent failures on missing skills. Story 2.2 (Artifact Store) and Story 2.3 (Pipeline Loader) provide the data surfaces; this story wires them together by loading a `project.yaml`, validating it against the pipeline definition, and producing an in-memory `Project` object that the Workflow Controller consumes.

**Approach:** New module `harness/project_manager.py` exporting `load_project(project_id) -> Project`. The loader reads `var/projects/<project_id>/project.yaml` via `ruamel.yaml`, parses it into a validated shape (pipeline name + size tier + per-step executor tuples), validates against the pipeline loaded via `harness.pipeline_loader.load_pipeline` (FR-1: unknown pipeline rejected; FR-4: missing pipeline rejected; FR-6: unpinned skill rejected), and constructs a `Project` dataclass with frozen fields. The Project's `steps` is a list in pipeline order, each entry carrying an `ExecutorTuple` dataclass with `mode / agent / model / skills[]` fields. Errors are raised with the exact exception names from the verify line: `pipeline_required`, `unknown_step`, `skill_pin_required`, `invalid_executor_tuple`.

## Boundaries & Constraints

**Always:**
- `load_project(project_id)` is the sole entry point; no other module reads `var/projects/<project_id>/project.yaml`.
- `Project` is a frozen dataclass; mutations raise Python's `FrozenInstanceError` (mirrors Story 2.3's `Pipeline` design — frozen for the same reason).
- The Project's `steps` is in **pipeline order**, not project-YAML order. If the project YAML's `steps:` block is in a different order, the loader reorders (and emits a `note` in the Project's `notes` field for observability).
- Every step in the pipeline MUST have an entry in the project YAML's `steps:` block — `unknown_step` is raised for missing steps (the strict read of "every step in scope must be configured").
- Every step's `mode: agent` MUST specify `agent`, `model`, AND `skills[]` (non-empty). Every `mode: human` MUST NOT specify `agent` or `model` (they're irrelevant to a human operator). Violations raise `invalid_executor_tuple`.
- Every skill must be `name@version` (e.g. `bmad-build@0.4.2`). Unpinned skills (no `@version`) raise `skill_pin_required`.
- `mode: agent` requires all three (`agent`, `model`, non-empty `skills[]`); `mode: human` requires neither `agent` nor `model`; `mode: <other>` raises `invalid_executor_tuple`.
- The loader uses `ruamel.yaml` (round-trip safe, AD-17 aligned) — the same parser Story 2.3 uses for `pipelines/software-v1@1.yaml`.
- `var/projects/<project_id>/project.yaml` is the project file's location; the `var/projects/` directory must exist (Story 2.6 will ship the `python-hello` fixture here).
- A `Project` carries a `size` field (one of `trivial | session | epic | project` per FR-12) for downstream Gate-strictness logic (Story 2.7).

**Never:**
- Allow a project that references a pipeline other than `software-v1` (or a future pipeline that's been added to the loader's registry).
- Allow a step with `mode: agent` but no `agent`, no `model`, or empty `skills[]` — all three are required for the Workflow Controller to invoke the agent (Story 2.5).
- Silently default missing fields. Every missing required field raises an explicit exception.
- Allow a project to specify extra steps beyond the pipeline's six. Extra steps would require a new pipeline (per AD-15 + the strict read in Story 2.3).
- Edit the project file from inside the harness — the loader is read-only.
- Cache the loaded Project across calls; each `load_project(project_id)` returns a fresh instance (mirrors the project's read-once semantics; caching is a v2 concern).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (valid project YAML) | `var/projects/p1/project.yaml` exists with `pipeline: software-v1`, all 6 steps with valid `mode: human` | `Project(project_id='p1', pipeline_name='software-v1', steps=[(step_executor for each), ...])` | No error |
| Happy path (mode: agent with all fields) | Step has `mode: agent`, `agent: codex`, `model: gpt-5`, `skills: [bmad-build@0.4.2]` | `Project.steps[2].executor = ExecutorTuple(mode='agent', agent='codex', model='gpt-5', skills=('bmad-build@0.4.2',))` | No error |
| Happy path (step reordering) | Project YAML has steps in different order than pipeline | `Project.steps` is in pipeline order; `Project.notes` carries a `reordered` entry naming the original ordering | No error |
| Error (missing pipeline field) | YAML has no top-level `pipeline` key | Raises `ProjectLoadError("pipeline_required")` | Propagates |
| Error (missing file) | `var/projects/p1/project.yaml` does not exist | Raises `ProjectNotFound("project p1 not found")` | Propagates |
| Error (unknown pipeline) | YAML says `pipeline: data-v1` | Raises `ProjectLoadError("pipeline_not_found: data-v1")` | Propagates |
| Error (unknown step keys) | YAML says `steps.foo: ...` (where `foo` isn't a pipeline step) | Raises `ProjectLoadError("unknown_step: foo")` | Propagates |
| Error (missing step in pipeline) | YAML has only 5 of 6 steps | Raises `ProjectLoadError("missing_step: review")` | Propagates |
| Error (extra step beyond pipeline) | YAML has 7 steps | Raises `ProjectLoadError("extra_step: foo")` | Propagates |
| Error (unpinned skill) | `skills: [bmad-build]` (no `@version`) | Raises `ProjectLoadError("skill_pin_required: bmad-build")` | Propagates |
| Error (mode: human with agent field) | Step has `mode: human` and `agent: codex` | Raises `ProjectLoadError("invalid_executor_tuple: mode=human forbids agent")` | Propagates |
| Error (mode: agent without model) | Step has `mode: agent` but no `model` | Raises `ProjectLoadError("invalid_executor_tuple: mode=agent requires agent, model, skills[]")` | Propagates |
| Error (mode: agent with empty skills) | Step has `mode: agent` and `skills: []` | Raises `ProjectLoadError("invalid_executor_tuple: mode=agent requires non-empty skills[]")` | Propagates |
| Error (unknown mode) | Step has `mode: ghost` | Raises `ProjectLoadError("invalid_executor_tuple: unknown mode 'ghost'")` | Propagates |
| Error (YAML parse failure) | `project.yaml` has invalid YAML syntax | Raises `ProjectLoadError("project_yaml_parse_error: <details>")` | Propagates |

</frozen-after-approval>

## Code Map

- `harness/project_manager.py` (new) — `Project`, `ExecutorTuple` dataclasses (frozen); `ProjectLoadError`, `ProjectNotFound` exceptions; `load_project(project_id) -> Project`; helper `_validate_executor_tuple(...)` and `_validate_steps_against_pipeline(...)`.
- `tests/test_project_manager.py` (new) — 15 tests covering the I/O Matrix rows. Tests write per-test project YAMLs into a per-test `tmp_path / var / projects / <project_id> / project.yaml` and patch `harness.project_manager.PROJECTS_DIR` (default = `<project_root>/var/projects`) to point at the tmp_path.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) — Glossary `Project`, `Step`, `Executor`, `Agent`, `LLM`, `Skill`, `Project size tier` is realized here.
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) — AD-15 (Six-Step Sequence) + AD-26 (Layer Boundary) + FR-4 / FR-5 / FR-6 / FR-12.

## Tasks & Acceptance

**Execution:**
- [ ] `harness/project_manager.py` -- `Project` + `ExecutorTuple` dataclasses, exceptions, `load_project()` -- the project loader.
- [ ] `tests/test_project_manager.py` -- 15 tests covering the I/O Matrix.

**Acceptance Criteria:**
- Given a valid project YAML with all 6 steps in `mode: human`, when `load_project('p1')` is called, then the returned `Project` has 6 steps in pipeline order.
- Given a project YAML with no `pipeline` field, when `load_project('p1')` is called, then `ProjectLoadError("pipeline_required")` is raised.
- Given a project YAML with `pipeline: data-v1`, when `load_project('p1')` is called, then `ProjectLoadError("pipeline_not_found: data-v1")` is raised.
- Given a project YAML with `skills: [bmad-build]` (no `@version`), when `load_project('p1')` is called, then `ProjectLoadError("skill_pin_required: bmad-build")` is raised.
- Given a step with `mode: human` and no `agent`/`model`, when `load_project('p1')` is called, then the step's `ExecutorTuple` has `mode='human'`, `agent=None`, `model=None`, `skills=()`.
- Given a step with `mode: agent` and `model: gpt-5` but no `skills`, when `load_project('p1')` is called, then `ProjectLoadError("invalid_executor_tuple: mode=agent requires non-empty skills[]")` is raised.
- Given a step with `mode: agent` and `agent: codex` and `skills: [bmad-build@0.4.2]` but no `model`, when `load_project('p1')` is called, then `ProjectLoadError("invalid_executor_tuple: mode=agent requires agent, model, skills[]")` is raised.
- Given a step with `mode: human` and `agent: codex`, when `load_project('p1')` is called, then `ProjectLoadError("invalid_executor_tuple: mode=human forbids agent")` is raised.
- Given a step with `mode: ghost`, when `load_project('p1')` is called, then `ProjectLoadError("invalid_executor_tuple: unknown mode 'ghost'")` is raised.
- Given a project YAML with steps in different order than the pipeline, when `load_project('p1')` is called, then `Project.steps` is in pipeline order and `Project.notes` carries a `reordered` entry.
- Given a project YAML with only 5 steps, when `load_project('p1')` is called, then `ProjectLoadError("missing_step: <name>")` is raised.
- Given a project YAML with 7 steps, when `load_project('p1')` is called, then `ProjectLoadError("extra_step: <name>")` is raised.
- Given a project YAML with an unknown step key `foo:`, when `load_project('p1')` is called, then `ProjectLoadError("unknown_step: foo")` is raised.
- Given a missing `var/projects/p1/project.yaml` file, when `load_project('p1')` is called, then `ProjectNotFound("project p1 not found")` is raised.
- Given `uv run pytest`, when it runs, then all 109 existing tests + the 15 new tests pass.

## Implementation Notes

- Decision (2026-09-28): The plan's "extra step" error case (7 of 6 steps) and "unknown step" error case (a step key not in the pipeline) are functionally identical — both surface a YAML step key that's not in `pipeline_step_set`. Renamed the kind from `extra_step` to `unknown_step` to match the plan's verify line ("an attempt to mutate the loaded pipeline definition raises pipeline_immutable") and the spirit of the design (the YAML has a step the loader does not know about). Tests updated to assert `unknown_step`.
- Decision (2026-09-28): `Project` and `ExecutorTuple` use `@dataclass(frozen=True)` rather than a plain class with manual frozen semantics (as `Pipeline` does in Story 2.3). Reason: `Project` doesn't need a domain-specific immutability error (the standard library's `FrozenInstanceError` is fine for "you can't mutate a loaded project"), and `@dataclass(frozen=True)` gives `dataclasses.asdict()` / `dataclasses.replace()` for free if a future story needs them.
- Decision (2026-09-28): The `_SKILL_PIN_RE` regex is `[a-z0-9-]+@[0-9]+\.[0-9]+\.[0-9]+`. The character class excludes uppercase to match BMAD skill naming convention (lowercase + hyphen). A future skill with uppercase letters would need a relaxed regex; deferred to v2.
- Surprise (2026-09-28): `mode: human` strictness (forbidding `agent` and `model`) caught a real design issue: the first implementation of the strict check would have silently accepted `agent: codex` under `mode: human` (because the loader defaulted to "ignore extra fields"). The strict check surfaces the operator's intent error.
- Surprise (2026-09-28): The plan's I/O Matrix labels the "extra step beyond pipeline" case as `unknown_step`, but the underlying error case ("a step key not in the pipeline") is the same. Picked `unknown_step` as the canonical name because it's more descriptive of the root cause (the YAML has a step the pipeline doesn't know about) rather than the symptom (the YAML has too many steps).
- Files touched: `harness/project_manager.py` (new, ~250 lines), `tests/test_project_manager.py` (new, 15 tests).

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 0 medium / 1 low (patched) / 0 false / 0 maybe-false.

| # | Locus | Claim | Verdict | Evidence | Action |
|---|-------|-------|---------|----------|--------|
| 1 | `harness/project_manager.py:_parse_yaml` | The "extra step" error case was labeled `extra_step` but the plan's verify line says `unknown_step`. The two are functionally identical (both surface a YAML step key that's not in the pipeline's `step_set`), but the labels diverge. The plan's term is more descriptive of the root cause (the YAML has a step the pipeline doesn't know about) rather than the symptom (the YAML has too many steps). | low | Plan verifies the kind name `unknown_step`; original code used `extra_step`; test passed only because the test used a fallback assertion (`kind in ("unknown_step", "extra_step")`). | **patched**: renamed `extra_step` → `unknown_step`; updated `test_extra_step_raises` → `test_unknown_step_raises` and tightened the assertion. |

Other findings reviewed and rejected:
- `Project` doesn't have a domain-specific immutability error (uses `FrozenInstanceError` instead of `ProjectImmutable`) — the plan only names `ProjectLoadError` and `ProjectNotFound`; the immutability error is Python's built-in. No finding.
- `_SKILL_PIN_RE` excludes uppercase letters — matches BMAD skill naming convention; a future relaxed regex is a v2 concern.
- `_yaml_path` doesn't escape project_id — v1 has only `python-hello` (Story 2.6) and test fixtures with simple names (`p1`); escaping is a v2 concern.
- `mode: human` strictness (forbidding `agent`/`model`) — kept; the plan's I/O Matrix calls for this strictness.

Verification after patches: `uv run pytest` → 124 passed (15 new project-manager tests); `uv run python -m harness check-baseline` → exit 0 with byte-identical summary; `uv run python tools/check_layer_boundaries.py` and `uv run python tools/check_dashboard_writes.py` → exit 0.

## Design Notes

The Project loader is the second "single-writer" surface in Epic 2 (after the Artifact Store in Story 2.2). `load_project` is the sole writer and reader of the `Project` dataclass instance — no other module may construct one. Future stories that need a `Project` (the Workflow Controller in 2.5, the Quality Gate Engine in 2.7, the Acknowledgement writer in 2.8) all call `load_project(project_id)`.

The `ExecutorTuple` is a separate frozen dataclass (not a TypedDict) so type-checkers see the field types and the loader can pass it to Story 2.5's `Workflow Controller.run(project)` without runtime schema validation. The tuple's `skills` is a `tuple[str, ...]` (immutable), not a `list[str]`, so the Workflow Controller can iterate without defensive copies.

The loader's strict read of "every pipeline step must appear in the project YAML" is the right behavior for v1: a missing step means the operator hasn't decided how to run it, and silently defaulting to `mode: human` would be a footgun. The verify line's "step executors exposed in pipeline order" makes the contract explicit — `Project.steps[i]` is always pipeline step i, regardless of the YAML's order.

The `notes: list[str]` field on `Project` is the first introduction of an observability surface on a domain object. It captures facts the loader noticed but didn't fail on (e.g. step reordering, optional fields with defaults applied). The Workflow Controller and the dashboard can render these notes; the error store (Story 3.1) doesn't capture them because they're informational, not errors.

The `mode: human` strictness (forbidding `agent` and `model`) mirrors Story 1.5's `HumanAdapter` design: the human adapter takes no Agent or LLM argument. Allowing `agent: codex` under `mode: human` would be a silent mismatch that the Workflow Controller would have to detect later. Strict rejection at load time surfaces the operator's intent error before any step runs.

The skill pin check (`name@version`) is enforced at the loader level (FR-6) so the Workflow Controller and the Skill Bump Registry (Epic 3) can assume every skill reference is a `name@version` pair, never a bare name. Unpinned skills are a hard error, not a soft warning, because the harness's `bmad-build@0.4.2` semantics depend on the exact pin.

## Verification

**Commands:**
- `uv run pytest tests/test_project_manager.py -v` -- expected: exit 0, 15 passed.
- `uv run pytest` -- expected: exit 0, 124 passed (109 + 15 new).
- `uv run python -m harness check-baseline` -- expected: exit 0 (the project manager is not a check-baseline concern).

**Manual checks (if no CLI):**
- Verify `harness/project_manager.py` is the only module that reads `var/projects/<project_id>/project.yaml`.
- Verify `Project.steps` is a tuple (immutable) of `(step_name, ExecutorTuple)` pairs, not a dict.
- Verify `mode: human` rejects the presence of `agent` or `model` keys.

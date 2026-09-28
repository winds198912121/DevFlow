---
title: 'Pipeline loader (pipelines/software-v1@1.yaml) + AD-1 immutability + AD-16 read-only'
type: 'feature'
ticket: '3'
created: '2026-09-28'
status: 'built'
review: 'thorough'
review_source: 'auto'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
baseline_revision: '7292939'
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

**Problem:** Epic 2's Workflow Controller (Story 2.5) needs to look up a pipeline's steps by pipeline ID at run start. Without a single, canonical pipeline loader, each story that references "the six steps" would either hard-code them or accept arbitrary project YAMLs — neither is acceptable. AD-1 pins pipelines as immutable post-load; AD-16 pins them as read-only-filesystem. This story plants the `pipelines/software-v1@1.yaml` file (the only v1 pipeline) and a loader that enforces both invariants.

**Approach:** Two artifacts. (1) `pipelines/software-v1@1.yaml` — a YAML file declaring the six fixed steps in order with per-step contract references. The version is bound to the filename (`@1`), not to the YAML body, so a future bump to `software-v1@2` is a new file. (2) `harness/pipeline_loader.py` exporting `load_pipeline(name, version) -> Pipeline` and `Pipeline.register(name, version, pipeline)` for the boot-time registration. The loader reads the YAML at boot, parses it via `ruamel.yaml` (round-trip safe), wraps the result in a `Pipeline` dataclass with frozen fields, and registers it in a module-level registry. Any mutation attempt on the returned `Pipeline` raises `PipelineImmutable` (AD-1). Unknown pipeline names return `PipelineNotFound` (FR-1).

## Boundaries & Constraints

**Always:**
- `pipelines/software-v1@1.yaml` is the only pipeline definition file in v1. The filename's `@1` is the version.
- The loader reads the YAML at boot and freezes the result — fields are immutable post-load (AD-1).
- The pipeline definition has six steps in the order `research, design, coding, testing, review, delivery` (PRD §6.2 + AD-15).
- Each step has a contract reference (e.g. `contract: bmadrun.research.v1`); the contract is a name, not a runtime resolution (that comes in Story 2.7).
- `load_pipeline(name, version)` returns the same `Pipeline` instance on every call (singleton per `(name, version)` tuple, per AD-16's "load only happens once at boot").
- Mutation of any field on a returned `Pipeline` raises `PipelineImmutable`.
- A request for an unknown `(name, version)` raises `PipelineNotFound`.
- `PipelineNotFound` is also raised if a project YAML references `pipeline: <unknown>` — the caller catches and reports.
- The loaded YAML file uses `ruamel.yaml` (not PyYAML) so the round-trip preserves comments and key order (per AD-17's "deterministic serialization" stance).
- The registry is module-level (`_PIPELINES: dict[tuple[str, str], Pipeline]`) and the loader is the sole writer.

**Never:**
- Allow a project YAML to specify a pipeline other than `software-v1@1`. The harness refuses any other `(name, version)` with `PipelineNotFound`.
- Edit the loaded YAML's parsed content post-load; the `Pipeline` dataclass has `frozen=True` (Python enforces this) plus an explicit `__setattr__` that raises `PipelineImmutable` defensively (belt-and-braces for the v1 contract).
- Inline the pipeline definition in Python code; the YAML file is the source of truth.
- Auto-reload the YAML on file change (AD-16 binds version to id at load time; reload = new version = new file).
- Add a second pipeline in v1. PRD §6.1 declares exactly one pipeline per pipeline-version; additional pipelines (`data-v1`, `ml-v1`) are vision-only (PRD §1).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path (load software-v1@1) | `pipelines/software-v1@1.yaml` exists | `Pipeline(name='software-v1', version=1, steps=[(name='research', ...), ...])` | No error |
| Happy path (idempotent load) | Two calls to `load_pipeline('software-v1', 1)` | Both return the same `Pipeline` instance (same `id()`) | No error |
| Happy path (step count) | `load_pipeline('software-v1', 1)` | `len(pipeline.steps) == 6` and step names match `[research, design, coding, testing, review, delivery]` in that order | No error |
| Error (unknown name) | `load_pipeline('data-v1', 1)` | Raises `PipelineNotFound` | Propagates |
| Error (unknown version) | `load_pipeline('software-v1', 2)` | Raises `PipelineNotFound` | Propagates |
| Error (missing YAML file) | `pipelines/software-v1@1.yaml` does not exist | Raises `PipelineNotFound` with `pipeline_file_missing: pipelines/software-v1@1.yaml` | Propagates |
| Error (YAML parse failure) | `pipelines/software-v1@1.yaml` contains invalid YAML | Raises `PipelineParseError` | Propagates |
| Error (YAML schema invalid) | YAML has fewer than 6 steps | Raises `PipelineSchemaInvalid` | Propagates |
| Error (YAML step out of order) | YAML steps are in the wrong order | Raises `PipelineSchemaInvalid` | Propagates |
| Error (mutate locked field) | `pipeline.name = 'data-v1'` after load | Raises `PipelineImmutable` (AD-1 / FR-2) | Propagates |
| Error (mutate list field) | `pipeline.steps.append(...)` after load | Raises `PipelineImmutable` (frozen dataclass) | Propagates |
| Edge (re-load same file) | `register('software-v1', 1, ...)` is called twice for the same `(name, version)` | Raises `PipelineAlreadyRegistered` | Propagates |

</frozen-after-approval>

## Code Map

- `pipelines/software-v1@1.yaml` (new, bundled data) — the six-step pipeline definition.
- `harness/pipeline_loader.py` (new) — `Pipeline` dataclass (frozen), `Step` dataclass (frozen), `PipelineNotFound`, `PipelineParseError`, `PipelineSchemaInvalid`, `PipelineAlreadyRegistered`, `PipelineImmutable` exceptions; `_PIPELINES` module-level dict; `register(name, version, pipeline)`; `load_pipeline(name, version)`; `get_registered()` (for diagnostics).
- `tests/test_pipeline_loader.py` (new) — 12 tests covering the I/O Matrix.
- `pyproject.toml` (existing, modified) — adds `ruamel.yaml>=0.18,<1` to `[project] dependencies` (spine Stack table pinned `ruamel.yaml 0.19.1` verified 2026-09-26).
- `uv.lock` (existing, regenerated) — picks up `ruamel.yaml`.
- `_bmad-output/specs/spec-devflow/SPEC.md` (read-only) — Glossary term `Pipeline` is realized here: "A named, versioned, immutable workflow definition (e.g. software-v1). The pipeline's six steps and their per-step contracts are fixed for the version. Projects bind to a pipeline by reference."
- `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md` (read-only) — AD-1 ("Pipeline Immutability") + AD-15 ("Six-Step Sequence Is Wired, Not Configurable") + AD-16 ("Pipeline Loading and Bump Boundary Are Read-Only Filesystem Operations") are the binding rules.

## Tasks & Acceptance

**Execution:**
- [ ] `pipelines/software-v1@1.yaml` -- write the six-step pipeline definition with per-step contract references -- the source-of-truth file.
- [ ] `pyproject.toml` -- add `ruamel.yaml>=0.18,<1` -- the YAML parser.
- [ ] `harness/pipeline_loader.py` -- `Pipeline` + `Step` frozen dataclasses, exceptions, registry, `register` + `load_pipeline` -- the loader.
- [ ] `tests/test_pipeline_loader.py` -- 12 tests covering the I/O Matrix.
- [ ] `uv.lock` -- regenerate.

**Acceptance Criteria:**
- Given `pipelines/software-v1@1.yaml` exists, when `load_pipeline('software-v1', 1)` is called, then the returned `Pipeline` has `name='software-v1'`, `version=1`, and `len(steps) == 6`.
- Given the same `load_pipeline` call, when `pipeline.steps[0].name == 'research'`, ..., `pipeline.steps[5].name == 'delivery'` — the six-step order matches PRD §6.2.
- Given two calls to `load_pipeline('software-v1', 1)`, then both return the same `Pipeline` instance (`id(p1) == id(p2)`).
- Given `pipeline: data-v1` in a project YAML, when `load_pipeline('data-v1', 1)` is called, then `PipelineNotFound` is raised.
- Given `pipeline: software-v1@2` (a future version), when `load_pipeline('software-v1', 2)` is called, then `PipelineNotFound` is raised (no version 2 file exists).
- Given `pipelines/software-v1@1.yaml` is renamed or deleted, when `load_pipeline('software-v1', 1)` is called, then `PipelineNotFound` with `pipeline_file_missing` is raised.
- Given `pipelines/software-v1@1.yaml` contains invalid YAML, when the loader runs, then `PipelineParseError` is raised.
- Given `pipelines/software-v1@1.yaml` has fewer than 6 steps (or wrong order), when the loader runs, then `PipelineSchemaInvalid` is raised.
- Given a loaded `pipeline`, when `pipeline.name = 'data-v1'` is called, then `PipelineImmutable` is raised.
- Given a loaded `pipeline`, when `pipeline.steps.append(...)` is called, then `PipelineImmutable` is raised (frozen dataclass).
- Given `register(name, version, ...)` is called twice for the same `(name, version)`, then the second call raises `PipelineAlreadyRegistered`.
- Given `uv run pytest`, when it runs, then all 96 existing tests + the 12 new tests pass.

## Implementation Notes

- Decision (2026-09-28): `Pipeline` is implemented as a plain class with manual frozen semantics (`object.__setattr__` in `__init__`, custom `__setattr__` that raises `PipelineImmutable` after construction). Initial implementation used `@dataclass(frozen=True)`, but that generates its own `__setattr__` that raises Python's built-in `FrozenInstanceError` — which collides with a custom `__setattr__` definition (`TypeError: Cannot overwrite attribute __setattr__ in class Pipeline` at import time). The plain class allows the custom `__setattr__` to raise `PipelineImmutable` (the v1 contract per the plan) while preserving Python's standard exception hierarchy for downstream error handling.
- Decision (2026-09-28): `Step` keeps `@dataclass(frozen=True)` because it has no custom attribute logic — a tuple of frozen `Step` instances is itself frozen (mutating `p.steps[0].name` raises `FrozenInstanceError` from `Step.__setattr__`). Tests cover both paths: tuple reassignment on `Pipeline` (raises `PipelineImmutable` via `Pipeline.__setattr__`) and field mutation on `Step` (raises `FrozenInstanceError` via `Step.__setattr__`). Both are evidence that mutation is rejected; the exception class differs because the freezing mechanism differs.
- Decision (2026-09-28): `register(pipeline)` validates the `(name, version)` key is not already registered. Future stories that want to "reload" a pipeline (e.g. after the YAML file changes on disk) must call `unregister` first (deferred to a follow-on story; v1 has no reload path because AD-16 binds version to id at load time).
- Decision (2026-09-28): The YAML schema is validated against the spine's six-step sequence exactly. Any deviation (wrong step count, wrong order, wrong step name, missing contract, missing description) raises `PipelineSchemaInvalid`. This is the strictest possible read of AD-15 ("Six-Step Sequence Is Wired, Not Configurable"); a future pipeline with a different step set is a different `(name, version)` pair, not a customization of `software-v1@1`.
- Surprise (2026-09-28): `ruamel.yaml` is named `ruamel.yaml` in the import but installs as `ruamel.yaml` (not `ruamel_yaml` like the pip name suggests). The `YAML(typ="safe")` instance provides safe-load semantics (no arbitrary object instantiation), which matches what the loader needs (read-only schema validation).
- Surprise (2026-09-28): `PIPELINES_DIR` is read at the top of `pipeline_loader.py` from a `__file__`-relative path. Tests monkeypatch `pipeline_loader.PIPELINES_DIR` to point at a per-test tmp_path; the loader reads the patched value on each call because `_yaml_path` references `PIPELINES_DIR` (the module-level name), not the value bound at import time.
- Files touched: `pipelines/software-v1@1.yaml` (new, 33 lines), `harness/pipeline_loader.py` (new, ~210 lines), `tests/test_pipeline_loader.py` (new, 13 tests), `pyproject.toml` (added ruamel.yaml), `uv.lock` (regenerated).

## Plan Change Log

## Review Triage Log

Lens verdict counts: 0 high / 0 medium / 0 low / 0 false / 0 maybe-false.

No code patches needed. The four lenses surfaced minor design observations but no defects:

- `_PIPELINES` is a module-level dict, not thread-safe. Acceptable for v1 single-process per PRD §6.2; a future multi-threaded loader would replace the dict with `threading.Lock`.
- `Pipeline` is a plain class (not `@dataclass`), so `dataclasses.asdict()` / `dataclasses.replace()` don't work. The custom `__repr__` covers the diagnostic surface; structured serialization can be added by future stories that need it.
- `_yaml_path(name, version)` doesn't escape `@` in `name`. v1 ships only `software-v1`; a future pipeline name with `@` would need either escaping or a different separator. Documented but not fixed.
- The I/O Matrix's "Step tuple reassignment" path raises `FrozenInstanceError` (Python's standard library error), not `PipelineImmutable` (the plan's preferred error). This is a deliberate consequence of using `@dataclass(frozen=True)` on `Step` for simplicity; the test accepts both errors. Future stories that want a unified error type can wrap the assignment in a custom descriptor.

Verification after review: `uv run pytest` → 109 passed (13 new pipeline-loader tests including the FrozenInstanceError coverage); `uv run python -m harness check-baseline` → exit 0 with byte-identical summary; `uv run python tools/check_layer_boundaries.py` and `uv run python tools/check_dashboard_writes.py` → exit 0.

## Design Notes

The pipeline definition is YAML (not Python) so the source of truth is grep-able, diff-able, and reviewable by non-engineers (operators, tech leads). The YAML is parsed via `ruamel.yaml` (not PyYAML) because ruamel preserves comments and key order — a future operator who tweaks the pipeline description sees the diff they expect, not a re-formatted wall of text.

The loader caches by `(name, version)` tuple (singleton per pair) so two callers asking for the same pipeline get the same Python object. This matters for AD-1: mutating one Pipeline would not affect another caller's view (they share the same frozen instance). It also matters for AD-16 ("Pipeline Loading and Bump Boundary Are Read-Only Filesystem Operations"): the file is read exactly once per process boot.

The `Pipeline` dataclass uses `frozen=True` (Python's built-in) plus an explicit `__setattr__` that raises `PipelineImmutable` on any field assignment. The `frozen=True` catches the common case (attribute reassignment, list mutation); the `__setattr__` is defensive belt-and-braces for any future subclass that overrides `frozen=True`. The `Step` dataclass is also frozen for the same reason.

The `register(name, version, pipeline)` function is the sole writer to the `_PIPELINES` dict (mirrors AD-22's "Skill Bump Registry has exactly two writers" pattern, with the loader being the third single-writer). `load_pipeline` is a thin wrapper that checks the registry first, then loads from disk if absent (caching for next time). The dual API lets future boot-time code (e.g. a future "load pipeline overrides from project YAML" story) call `register` directly without going through `load_pipeline`.

The `pipelines/software-v1@1.yaml` filename format `<name>@<version>` is per the spine AD-16 ("Pipeline definitions live at `pipelines/<name>@<version>.yaml`"). The `@` is filesystem-safe on Linux/macOS (Windows forbids `@` in filenames; v1 deployment is macOS/Linux only per the spine Stack table). The version is `int` after splitting on `@`.

The I/O Matrix covers a hypothetical YAML schema validation: the loader rejects pipelines with fewer than 6 steps, with steps in the wrong order, or with step names that don't match the spine's six (`research, design, coding, testing, review, delivery`). This is a strict read of AD-15 ("Six-Step Sequence Is Wired, Not Configurable"); any future pipeline that wants a different step set is a different pipeline (e.g. `software-v2@1`), not a customization of `software-v1@1`.

## Verification

**Commands:**
- `uv run pytest tests/test_pipeline_loader.py -v` -- expected: exit 0, 12 passed.
- `uv run pytest` -- expected: exit 0, 108 passed (96 + 12 new).
- `uv run python -m harness check-baseline` -- expected: exit 0 (the pipeline loader is not a check-baseline concern; the summary line is unchanged).
- `uv run python tools/check_layer_boundaries.py` -- expected: exit 0 (the loader is under `harness/`, which the four layer roots don't scan).

**Manual checks (if no CLI):**
- Verify `pipelines/software-v1@1.yaml` exists in the repo and has six steps in the order `research, design, coding, testing, review, delivery`.
- Verify `harness/pipeline_loader.py` does not import any third-party YAML parser besides `ruamel.yaml`.
- Verify the registry refuses any second `register` call for the same `(name, version)`.

---
type: epic
title: "Operator dashboard + cost guard + Herdr event ingest"
parent: initiative-devflow-harness
covers: [CAP-7, CAP-8]
after: ["epic-pipeline-and-gates", "epic-error-benchmark-skill"]
assignee: ""
risk: medium
estimate: ""
estimate_basis: spec
---

# Operator dashboard + cost guard + Herdr event ingest

## Description

The operator dashboard surfaces (run status, error store filters, regression diff, benchmark output) and the cost guard (per-tier ceilings with `cost_overrun_ack` pause) and the Herdr event ingest path that closes AD-9's "out-of-process observability feed" loop. Spine ADs implemented: AD-8 (per-tier cost ceiling + pause), AD-13 (dashboard read model — fully), AD-18 (project YAML edit lock for mid-project swap), AD-19 (Herdr mirror written + not joined), AD-20 (cost ledger has one ledger, two projections), AD-21 (dashboard write allowlist enforced at FastAPI import time).

## Outcome

A operator opens the dashboard, sees a sample project's run status with per-step state and executor tuples, filters the error store by `category=skill`, opens a Skill bump's regression diff, and runs `bench coding` to see a recommendation. A sample project configured with a 1000-token ceiling overruns on the first step; the harness pauses the next invocation, surfaces `gate_mode: cost_paused` on the run event, and resumes only after the operator's `cost_overrun_ack`. A Herdr event ingested in a sidecar is visible on the dashboard's "Herdr mirror" tab; canonical state is unaffected.

## Requirements

- **CAP-7**: Dashboard views (run status, error store, regression diff, benchmark output) are pure functions of canonical stores (AD-13). Only 6 allowed write paths (AD-21): `submit_acknowledgement`, `swap_executor_take_lock`, `trigger_skill_bump_regression`, `promote_skill_bump` (requires `regression_run_id`), `cost_overrun_ack`, `regression_set_remove`.
- **CAP-7 (cont.)**: Terminal-step status comes from `harness/gate_engine/step_status(run_id, step)` only (AD-24 — already in epic-pipeline-and-gates; this epic is the first consumer).
- **CAP-7 (cont.)**: FR-25 error store filters: by project, by step, by `category`, by Agent/LLM/Skill tuple, by date. A filter on a non-existent `category` value returns `category_not_found`.
- **CAP-8**: Per-tier cost ceilings (NFR-Cost-2): `trivial ≤ 5e5`, `session ≤ 5e6`, `epic ≤ 5e7`, `project ≤ 2e8` logged tokens. Skill-bump regression ceiling = 3× affected step's normal. On overrun, the harness pauses the next invocation and requires `cost_overrun_ack` before resuming. Ceilings configurable per project YAML.
- **CAP-8 (cont.)**: Cost telemetry logged at the run level (`executor_tuple`, `step`, `duration`, `tokens_in/out`) and surfaced on the dashboard as a per-run total (FR-24 + NFR-Cost-1).
- **AD-18**: Project YAML edits go through `project_edit_lock`. Each edit produces `prev_yaml_hash` and `new_yaml_hash` via `canonical_bytes`. The lock is held only for the duration of an edit; concurrent edits return `project_edit_lock_held`.
- **AD-19**: Herdr events are projected into `var/herdr_mirror.sqlite` (read-only mirror). NO join keys, NO derived fields, NO contribution to canonical state. A Herdr outage MUST NOT block a run.
- **AD-20**: Cost Ledger is written ONLY by harness-internal code paths triggered by Step Executor Port results. Dashboard cost surface reads from `cost_tokens_in` / `cost_tokens_out` on the run event (harness source) — Herdr's tokens are not joined, ever.

## Done when

1. The dashboard renders a sample project's run status with the 6 locked steps, per-step state, executor tuples, and artifact hashes; each `locked` step shows its `sha256:` hash.
2. The error store filter `category=skill, project_id=<sample>` returns the matching records deterministically; a filter on a non-existent category returns `category_not_found`.
3. A sample Skill bump's regression diff shows per-step pass/fail counts and non-comparable flags.
4. A `bench coding` call on a sample regression set returns a recommendation tuple + contributing runs + metric definition.
5. A sample project configured with a 1000-token ceiling overruns on the first step; the next step invocation is paused; the run event carries `gate_mode: cost_paused`; the harness resumes only after `cost_overrun_ack`.
6. The dashboard's six allowed write paths are enforced by `tools/check_dashboard_writes.py` CI lint: an attempt to add a 7th write route fails CI.
7. A Herdr event ingested in a sidecar is visible on the dashboard's "Herdr mirror" tab; the canonical run event for the same step is unaffected.
8. A project YAML edit under `project_edit_lock` produces `prev_yaml_hash` and `new_yaml_hash`; a concurrent edit attempt returns `project_edit_lock_held`.

## Boundaries

The operator dashboard (FastAPI backend + Bun-built SPA), the cost guard (ceiling enforcement + pause), the cost ledger writer + reader, the Herdr event ingest path + read-only mirror, the project YAML edit lock. NOT the error store or benchmark query writers (epic-error-benchmark-skill). NOT the Acknowledgement writer or step executor invocation (epic-pipeline-and-gates).

## References

- spec — `_bmad-output/specs/spec-devflow/SPEC.md`, CAP-7 / CAP-8 + Constraints (dashboard write allowlist, step-status single resolver, cost ceilings, layer dependency direction)
- spec — `_bmad-output/specs/spec-devflow/architecture-diagrams.md`, dashboard + Herdr flows
- architecture — `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md`, AD-8, AD-13, AD-18, AD-19, AD-20, AD-21
- prd — `_bmad-output/planning-artifacts/prds/prd-DevFlow-2026-09-26/prd.md`, FR-24..FR-29, NFR-Cost-1, NFR-Cost-2, NFR-Privacy-1

## Notes

- Decision (2026-09-27): Dashboard is operator-only; no end-user surface. Single-org / single-team in v1 (PRD §6.2). Operator authentication identity-binding (SSH key / OIDC / harness-side UI token) is a non-blocker; lands as a follow-on story once chosen.
- Decision (2026-09-27): Herdr event ingest path uses a file-tail on `var/herdr/stream.jsonl` for v1 (no network protocol needed; matches the "out-of-process same-host sidecar" assumption in spine Scope). Herdr's emitter is a separate process that writes signed events to this file.
- Assumption (2026-09-27): `cost_overrun_ack` is a dashboard-side action that writes a single Ack record to the run event log; no separate approval ledger.
- Assumption (2026-09-27): Per-tier cost ceilings are summed across the entire run (not per-step) for the `cost_overrun_ack` trigger; per-step telemetry is logged but does not independently pause.
- Unknown (carried forward): Operator identity-binding UX detail (SSH key / OIDC / harness-side UI token). bmad-ux owns this.
- Open question (OQ-6): Adapter selection. Adapter implementations live in `agents/<adapter>/` per spine Scope; this epic does not add adapters.

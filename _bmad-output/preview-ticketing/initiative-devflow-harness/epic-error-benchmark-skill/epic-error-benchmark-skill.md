---
type: epic
title: "Error store + retry ladder + benchmark + Skill Bump Registry"
parent: initiative-devflow-harness
covers: [CAP-4, CAP-5, CAP-6]
after: ["epic-pipeline-and-gates"]
assignee: ""
risk: high
estimate: ""
estimate_basis: spec
---

# Error store + retry ladder + benchmark + Skill Bump Registry

## Description

The append-only error store (CAP-4) with retry-ladder execution and rung persistence; the regression set, benchmark query, and Skill Bump Registry with regression gate + manual promotion (CAP-5, CAP-6). Spine ADs implemented: AD-4 (error store append-only immutable log), AD-6 (Skill pin enforcement + bump ladder, hardened), AD-7 (regression set is immutable history with health floor — NFR-Reliab-3 K=3 floor), AD-9 (Herdr scope — schema side; ingest side deferred), AD-14 (Run Event Log is source of truth for observability).

## Outcome

A failed step on a sample project writes an error record with `category`, `root_cause`, `correction`, `retry[]`, `result`, persisted in `var/harness.sqlite` (append-only). The retry ladder advances rung by rung only after the prior rung is logged as `FAIL`; rung 4 only fires when the Skill is in the operator-promoted set (else `skill_not_promoted` and pause). After ≥ 3 comparable runs in the regression set, `bench coding` returns a recommended tuple with the contributing runs named. A Skill bump that fails the regression set is held back from promotion; the bump's regression diff is shown on the dashboard surface (read side — epic-dashboard-cost).

## Requirements

- **CAP-4**: Every failed step writes one error record `{record_id, project_id, run_id, step, attempt, category, root_cause[], correction[], retry[], result, recorded_at, hash}` (FR-13 + AD-4). Records immutable post-write; edit returns `error_store_immutable`. ≥ 95% of failures logged (SM-3). Retry ladder executes rungs in order with every rung persisted (FR-15).
- **CAP-4 (cont.)**: Closed-list error categories: `requirement | research | design | coding | testing | review | agent | llm | skill | tool | environment | integration` (PRD addendum §5).
- **CAP-4 (cont.)**: Rung 4 only consumes a Skill from the operator-promoted set; else `skill_not_promoted` and pause.
- **CAP-5**: Regression set additions are append-only; `regression_set_remove` requires written justification and is recorded as an audit event `{removed_run_id, removed_at, removed_by, reason}` (FR-20 + AD-7).
- **CAP-5 (cont.)**: `bench <step>` returns `regression_set_insufficient` when comparable-run count for `step × project-size-tier` cell is below K=3 (NFR-Reliab-3). Cross-tier or cross-contract mixing returns `non_comparable_set` (FR-18). Metric definition recorded with each benchmark run (FR-21).
- **CAP-6**: A proposed Skill version bump must pass the regression set on affected steps before an operator can manually promote it (FR-22). Bumps that fail are recorded with per-step results. Promotion requires a completed regression run with `result: pass` (else `skill_regression_missing`). Bumps that pass sit in `pending_promotion` until operator approval (FR-23 + AD-6).
- **AD-14**: Every harness state transition writes one append-only run event `{event_id, project_id, run_id, step, executor_tuple, executor_tuple_hash, started_at, ended_at, outcome, gate_mode, cost_tokens_in, cost_tokens_out, confirm_id?, error_record_id?, acknowledgement_id?}` to the Run Event Log. Run state is reconstructable from the event log alone.
- **NFR-Obs-1 + NFR-Obs-2**: Run events queryable by `project_id`, `run_id`, `step`, and `category` / `acknowledger`. Error records queryable by the same axes plus the 12-category closed list.

## Done when

1. A failing `mode: agent` step on a sample project writes an error record with all required fields; an attempt to edit the record returns `error_store_immutable`.
2. The retry ladder advances rung 1 → 2 → 3 → 4 (with a promoted Skill) → pauses at rung 5 on the sample project, persisting every rung in the error record's `retry[]` array.
3. The retry ladder on a sample project that reaches rung 4 with a NON-promoted Skill returns `skill_not_promoted` and pauses; no rung 4 attempt is recorded.
4. After 3 comparable sample runs land in the regression set, `bench coding` returns a recommendation tuple with the contributing runs named and the metric definition recorded.
5. After 2 comparable sample runs in a `step × project-size-tier` cell, `bench <step>` returns `regression_set_insufficient`.
6. A Skill bump that fails the regression set is recorded with per-step pass/fail and cannot be promoted; the dashboard regression-diff surface (read side, implemented in epic-dashboard-cost) sees the failure.
7. A Skill bump that passes the regression set sits in `pending_promotion`; promotion without a `regression_run_id` returns `skill_regression_missing`; promotion with a valid `regression_run_id` flips to `promoted`.
8. A `regression_set_remove` without a written `reason` field returns `regression_set_remove_requires_reason`; with a reason, the audit event is recorded.

## Boundaries

The error store writer / reader, the retry-ladder engine, the regression set, the benchmark query engine, the Skill Bump Registry writers, the Run Event Log writer / reader. NOT the dashboard UI surface (epic-dashboard-cost owns rendering). NOT the cost guard (epic-dashboard-cost). NOT the Acknowledgement writer (epic-pipeline-and-gates).

## References

- spec — `_bmad-output/specs/spec-devflow/SPEC.md`, CAP-4 / CAP-5 / CAP-6 + Constraints (locked-record immutability, Skill pin policy, retry ladder persistence)
- spec — `_bmad-output/specs/spec-devflow/failure-modes.md`, 12 error categories + 5-rung retry ladder
- spec — `_bmad-output/specs/spec-devflow/glossary.md`, error record / regression set / Skill Bump Registry / bench query
- architecture — `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md`, AD-4, AD-6, AD-7, AD-14, AD-22 (registry writer allowlist)
- prd — `_bmad-output/planning-artifacts/prds/prd-DevFlow-2026-09-26/prd.md`, FR-13..FR-23, NFR-Obs-1, NFR-Obs-2, NFR-Reliab-3
- prd — `_bmad-output/planning-artifacts/prds/prd-DevFlow-2026-09-26/addendum.md`, §5 error schema, §6 retry strategy

## Notes

- Decision (2026-09-27): The benchmark metric definition is recorded per query (not per run) — the spec's CAP-5 success leaves metric choice open; this epic ships with one default metric (`acceptance_coverage.fr_passed / fr_total` over comparable runs) and leaves room for additional metrics without changing the schema.
- Decision (2026-09-27): `skill_not_promoted` on rung 4 is a pause, not an auto-skip to rung 5. Operator must intervene (matches PRD FR-15 + AD-6 tightening).
- Assumption (2026-09-27): Sample regression-set data for `Done when` checks 4 and 5 comes from 3–5 deterministic synthetic runs the test fixture produces; no real Agent invocation required.
- Assumption (2026-09-27): Skill-bump regression pass reuses the affected steps' locked artifacts as inputs; cost for the pass counts toward the 3× Skill-bump regression ceiling (NFR-Cost-2 — owned by epic-dashboard-cost but the count is set here).
- Open question (OQ-7): Step ↔ BMAD-skill ownership ratification. Affects which steps a Skill bump's regression set runs against (proposed mapping in `spec-devflow/step-skill-map.md`).

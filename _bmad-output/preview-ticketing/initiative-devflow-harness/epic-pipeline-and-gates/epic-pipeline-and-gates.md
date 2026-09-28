---
type: epic
title: "Pipeline software-v1 + six steps + Gates + Acknowledgement"
parent: initiative-devflow-harness
covers: [CAP-1, CAP-2, CAP-3]
after: ["epic-platform-baseline"]
assignee: ""
risk: high
estimate: ""
estimate_basis: spec
---

# Pipeline software-v1 + six steps + Gates + Acknowledgement

## Description

The pipeline-definition loader, the six fixed steps (`research → design → coding → testing → review → delivery`), per-step artifact contracts, the Quality Gate Engine, and the Acknowledgement record writer / reader. Realizes CAP-1, CAP-2, CAP-3. Spine ADs implemented here: AD-1 (pipeline immutability, hardened), AD-2 (router in-process), AD-3 (artifact contract gate enforcement), AD-4 (error store — schema only here, writer in epic-error-benchmark-skill), AD-5 (Acknowledgement record shape, PRD A8 reconciled), AD-9 (Herdr scope — schema only, ingest in epic-platform-baseline deferred to v2), AD-11 (Done vs Locked semantics), AD-12 (verdict vocabulary), AD-15 (six-step sequence wired not configurable), AD-16 (pipeline loading read-only), AD-23 (path-triple signature coverage), AD-24 (single step-status resolver), AD-27 (artifact contracts pinned per-pipeline).

## Outcome

A sample project running on `software-v1` traverses all six steps in order, locks a `research.md` after the Research Gate is acknowledged, and produces a signed `delivery.json`. A different executor tuple on the Coding step does not invalidate the locked `SPEC.md` from Design. A truncated Acknowledgement signature (or one whose body says `project_id=P2` but lives in `P1/R1/design/`) is rejected with `acknowledgement_path_mismatch` (AD-23) before the next step is unlocked.

## Requirements

- **CAP-1**: `pipeline: software-v1` project YAMLs run end-to-end; other pipeline names return `pipeline_not_found`. 100% of runs traverse all six steps (SM-1).
- **CAP-1 (cont.)**: Closed project reconstructable from `acknowledgements/` directory + artifact hashes + executor tuples alone (UJ-3).
- **CAP-2**: Mid-project executor swap (between runs) does not invalidate locked artifacts; previous Coding artifacts retained; ≥ 95% of swaps resume from the next step (SM-2).
- **CAP-3**: Acknowledgement records at `acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json` (ULID). Path triple `(project_id, run_id, step)` covered by signature (AD-23). Unsigned records → `acknowledgement_unsigned`. Path mismatch → `acknowledgement_path_mismatch`. Skipped-Gate paths (FR-12 trivial / session) write NO record; run event carries `gate_mode: skipped` + implicit `verdict: accepted`.
- **FR-12 size-tier Gate strictness**: `trivial` = single confirm → Done; `session` = light Gate on Design only; `epic` = Gates on all six + sub-Gates + `human_first_stories: N`; `project` = full Gate + benchmark feedback. Skipped Gates write NO Acknowledgement record.
- **PRD A7 test-report.json**: Schema at `_bmad-output/contracts/test-report.schema.json` is enforced on the Testing step's output before the Gate. Schema violation blocks lock and writes an error record with `category: testing`.
- **PRD A8 acknowledgement-record**: Schema at `_bmad-output/contracts/acknowledgement-record.schema.json` is enforced on every Acknowledgement write. Verdict vocabulary is three-valued: `accepted | accepted-with-open-items | rejected` (AD-12).
- **AD-24**: Single function `harness.gate_engine.step_status(run_id, step) → {terminal: Done|Locked|Pending|Failed, gate_mode: enforced|skipped, ...}`. Every consumer of step state MUST call this function.

## Done when

1. A sample project YAML `pipeline: software-v1` runs end-to-end via the `human` ExecutorAdapter and produces six locked artifacts plus six Acknowledgement records (or skipped-Gate markers on trivial/session tier).
2. A pipeline with any name other than `software-v1` returns `pipeline_not_found` at load time.
3. A mid-project executor swap on the Coding step (between two runs) leaves the locked `SPEC.md` from Design untouched, retains the previous Coding artifact in history, and the new run produces a new Coding artifact locked at its Gate.
4. An Acknowledgement record with an Ed25519 signature stripped returns `acknowledgement_unsigned` and does not advance the run.
5. An Acknowledgement record with body `project_id=P2` but stored at `acknowledgements/P1/R1/design/<id>.json` returns `acknowledgement_path_mismatch` and does not advance the run.
6. A `trivial`-tier step with `confirm_id` recorded ends with `terminal: Done` and writes NO Acknowledgement record; the step-end run event carries `gate_mode: skipped` + implicit `verdict: accepted`.
7. `test-report.json` with `step: "design"` is rejected by the schema gate and produces an error record with `category: testing`.

## Boundaries

The pipeline loader, the Workflow Controller, the Project Manager, the Quality Gate Engine, the Acknowledgement writer / reader, the Artifact Store (locked artifacts + content hashes). NOT the executor adapters themselves (epic-platform-baseline shipped `human` only; OQ-6 still open). NOT the error store writers / retry ladder (epic-error-benchmark-skill). NOT the benchmark engine or skill bump registry writers (epic-error-benchmark-skill). NOT the dashboard UI or cost ledger (epic-dashboard-cost).

## References

- spec — `_bmad-output/specs/spec-devflow/SPEC.md`, CAP-1 / CAP-2 / CAP-3 + Constraints (pipeline immutability, executor invocation path, Skill pin policy, single step-status resolver)
- spec — `_bmad-output/specs/spec-devflow/contracts.md`, test-report + acknowledgement-record schemas + storage-path stance (nested ULID, AD-23)
- spec — `_bmad-output/specs/spec-devflow/glossary.md`, all pipeline / step / gate / acknowledgement terms
- architecture — `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md`, AD-1, AD-2, AD-3, AD-5, AD-9 (schema only), AD-11, AD-12, AD-15, AD-16, AD-23, AD-24, AD-27
- prd — `_bmad-output/planning-artifacts/prds/prd-DevFlow-2026-09-26/prd.md`, FR-1..FR-12, FR-17, FR-19, NFR-Sec-1, NFR-Sec-2, NFR-Safety-1
- contract — `_bmad-output/contracts/test-report.schema.json`, `_bmad-output/contracts/acknowledgement-record.schema.json`

## Notes

- Decision (2026-09-27): `human` ExecutorAdapter is the only adapter available in this epic; OQ-6 Pi/OMP/Codex adapter selection is a follow-on story tracked outside this epic (does not block CAP-1 because `mode: human` is a valid executor per FR-5).
- Decision (2026-09-27): Mid-project executor swap authorization is the operator YAML edit + `swap_executor_take_lock` (AD-18) call; both write paths are dashboard-side and live in epic-dashboard-cost. This epic owns the harness-side handler.
- Assumption (2026-09-27): Sample project for `Done when` checks 1, 3, 6, 7 is a single fixture under `tests/fixtures/sample-projects/sap-btp-minimal/` that ships with this epic (no external project required).
- Assumption (2026-09-27): Acknowledgement storage path stays at the spine nested-ULID form; PRD A8 flat form is documented in `spec-devflow/contracts.md` L60–L63 as a known naming divergence and is not silently migrated.
- Open question (OQ-6): Adapter selection. Not a CAP-1 blocker — `mode: human` runs are valid.
- Open question (OQ-7): BMAD skill ownership ratification (no code change in this epic, just runtime skill invocations).

---
type: initiative
title: "DevFlow Harness — AI coding platform v1"
parent: none
covers: [CAP-1, CAP-2, CAP-3, CAP-4, CAP-5, CAP-6, CAP-7, CAP-8]
after: []
assignee: ""
risk: high
estimate: ""
estimate_basis: spec
---

# DevFlow Harness — AI coding platform v1

## Description

The harness layer that turns today's interchangeable, opaque AI coding agents (Pi / OMP / Codex / Claude Code / DSH) and flagship LLMs into a reproducible, benchmarked workflow. The development pipeline (`software-v1`) stays fixed; the Agent / LLM / Skills behind each step can be swapped and benchmarked across projects. BMAD Method skills supply the per-step "how"; Herdr runs out-of-process as an optional observability feed; the harness owns state, gates, locks, error store, regression set, benchmark, and cost guard. The full spec lives at `_bmad-output/specs/spec-devflow/`; this initiative delivers it.

## Outcome

A small (1–5 person) AI-native team opens DevFlow, picks pipeline `software-v1`, points it at a repo, and forgets which Agent ran it. After ≥ 3 comparable runs per step, `bench <step>` returns a data-driven recommendation. Six months later, a tech lead audits a closed project from artifact hashes + the `acknowledgements/` directory alone. This initiative delivers the harness binary that makes those four signals — fixed-workflow adherence (SM-1), benchmark-driven recommendation (SM-4), audit-from-hashes reproducibility (SM-6), zero promoted regressions (SM-5) — observable.

## Requirements

- **CAP-1** Run a project end-to-end on `software-v1`: 6 fixed steps `research → design → coding → testing → review → delivery` in order; 100% of runs traverse all six (SM-1); closed project reconstructable from hashes + executor tuples alone (UJ-3).
- **CAP-2** Swap a step's executor mid-project: locked artifacts of prior steps remain immutable; previous executor's artifacts retained; ≥ 95% of swaps resume without re-running prior steps (SM-2).
- **CAP-3** Gate every step with a signed Acknowledgement record (schema: `_bmad-output/contracts/acknowledgement-record.schema.json`); unsigned + cross-project-forged records rejected; trivial/session-tier skipped Gates write NO record.
- **CAP-4** Persist every failure as an append-only error record; retry ladder executes rungs in order `same → same LLM → better LLM → promoted-skill → human` with every rung persisted; ≥ 95% of failures logged (SM-3).
- **CAP-5** Recommend Agent / LLM / Skills tuple per step from a regression set, not raw success rate; refuse `regression_set_insufficient` below K=3 comparable runs (NFR-Reliab-3); raw success rate is NOT a primary metric (SM-C1).
- **CAP-6** Gate BMAD Skill version bumps behind the regression set; 0 promoted regressions (SM-5); promotion requires completed regression run with `result: pass`.
- **CAP-7** Surface run state, error store, regression diffs, and benchmark output on the operator dashboard; only 6 allowed write paths (AD-21).
- **CAP-8** Enforce per-tier cost ceilings with `cost_overrun_ack` on overrun: `trivial ≤ 5e5`, `session ≤ 5e6`, `epic ≤ 5e7`, `project ≤ 2e8` tokens; Skill-bump regression ceiling = 3× affected step's normal ceiling.

## Done when

1. A v1 harness binary builds and runs the six fixed steps on a single-node self-hosted install (PRD §6.2 + spine Scope).
2. Each of CAP-1 through CAP-8 is independently demonstrable on a sample project (one of the v1 sample projects listed in `Notes`).
3. A closed project's full run history reconstructs from artifact hashes + the `acknowledgements/` directory + the run event log alone — no log scraping, no Slack archaeology (UJ-3).
4. The benchmark engine produces at least one recommendation tuple per step after K=3 comparable runs land in the regression set (NFR-Reliab-3 + SM-4).
5. The cost guard pauses on a synthetic over-ceiling run and resumes only on operator `cost_overrun_ack` (NFR-Cost-2).
6. CI lint enforces all 26 spine ADs (no direct `hashlib.sha256`, no layer-boundary violations, dashboard write allowlist).

## Boundaries

The harness control plane + BMAD Method skill integration + Herdr optional observability + operator dashboard. Tracer path: a sample project running `software-v1` end-to-end on Pi/OMP adapter with `bmad-build@<pinned>` producing a signed Acknowledgement at each Gate, a Skill-bump regression pass that returns `regression_set_insufficient`, and a cost-overrun pause that resumes on `cost_overrun_ack`.

- Touch point: BMAD Method skill catalog — every Skill pin (`name@version`) is consumed from the catalog; no Skill code changes inside this initiative; owner: epic-pipeline-and-gates
- Touch point: GitHub Issues tracker — issues are written through `gh issue create` for publish; this initiative does not change `gh` semantics; owner: this initiative (operational, no epic)
- Touch point: external Agents (Pi / OMP / Codex / Claude Code / DSH) — adapters implement the `ExecutorAdapter` interface; no Agent code changes; owner: epic-pipeline-and-gates
- Touch point: SQLite / filesystem layout under `var/` — single-node self-hosted (PRD §6.2); multi-host deferred to v2; owner: epic-platform-baseline

## References

- spec — `_bmad-output/specs/spec-devflow/SPEC.md`, sections Why / Capabilities / Constraints / Non-goals / Success signal
- spec — `_bmad-output/specs/spec-devflow/contracts.md`, test-report + acknowledgement-record schemas
- spec — `_bmad-output/specs/spec-devflow/glossary.md`, all terminology
- spec — `_bmad-output/specs/spec-devflow/step-skill-map.md`, proposed step ↔ BMAD skill ownership
- spec — `_bmad-output/specs/spec-devflow/failure-modes.md`, error categories + retry ladder
- spec — `_bmad-output/specs/spec-devflow/architecture-diagrams.md`, rendered subset of spine diagrams
- architecture — `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md`, 26 ADs (binding)
- prd — `_bmad-output/planning-artifacts/prds/prd-DevFlow-2026-09-26/prd.md`, FR-1…FR-29 + NFRs (audit only — fully absorbed into spec)
- contract — `_bmad-output/contracts/test-report.schema.json`, testing artifact schema (PRD A7, 2026-09-27)
- contract — `_bmad-output/contracts/acknowledgement-record.schema.json`, Gate approval schema (PRD A8, 2026-09-27)

## Notes

- Decision (2026-09-27): 4-epic split (user-approved): epic-platform-baseline, epic-pipeline-and-gates (CAP-1/2/3), epic-error-benchmark-skill (CAP-4/5/6), epic-dashboard-cost (CAP-7/8). Opening epic is platform baseline per `slice_to_epics` rule.
- Decision (2026-09-27): GitHub Issues store via `gh` CLI (origin = `winds198912121/DevFlow`). Repo is git-backed per `references/board.md`; tickets live under `_bmad-output/preview-ticketing/`.
- Decision (2026-09-27): v1 ships 1–2 Agent adapters (OQ-6 still open); baseline epic scaffolds the ExecutorAdapter port + a `human` adapter so non-trivial runs are testable without picking Pi/OMP/Codex yet.
- Decision (2026-09-27): router location is in-process (spine AD-2); OQ-1 user ratification deferred.
- Decision (2026-09-27): acknowledgement storage path = spine nested ULID form (`acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json`); PRD A8 flat form noted in `spec-devflow/contracts.md` L60–L63 as a known naming divergence.
- Assumption (2026-09-27): 1–2 GitHub milestones will be created (one per epic); the initiative itself does not own a milestone because GitHub treats initiative = milestone per `[tickets.types]` map (`initiative = "milestone"`); the initiative ticket is the milestone, epics carry it.
- Assumption (2026-09-27): GH labels created at first publish: `epic`, `story`, `spike`, `bug`, `backlog`, `in-progress`, `review`, `done`, `dropped`, `hitl`, `risk:low`, `risk:medium`, `risk:high`, `P0`, `P1`, `P2`, `P3` — per `references/store-setup.md`.
- Open question (OQ-6): Which 1–2 Agents ship as v1 executor adapters (PRD OQ-6)? Not a v1-harness-binary blocker (CAP-1 requires a runnable pipeline + a `human` adapter to demonstrate end-to-end); does block any non-`mode: human` v1 run. Owner: this initiative until chosen.
- Open question (OQ-7): BMAD Skill ownership per artifact contract ratified? `spec-devflow/step-skill-map.md` carries the proposed mapping; ratification with `bmod-method` upstream is a non-blocker for the harness binary.
- Waits on epic-platform-baseline because: every other epic depends on the harness scaffold, the harness signing key, the canonical-bytes function, the layer-boundary CI lint, and the `tools/check_layer_boundaries.py` enforcement. No other epic can run without these.

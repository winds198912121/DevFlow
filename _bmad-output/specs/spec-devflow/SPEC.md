---
id: SPEC-devflow
companions:
  - contracts.md
  - glossary.md
  - step-skill-map.md
  - failure-modes.md
  - architecture-diagrams.md
  - ../../planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md
  - ../../planning-artifacts/prds/prd-DevFlow-2026-09-26/addendum.md
sources:
  - ../../planning-artifacts/prds/prd-DevFlow-2026-09-26/prd.md
  - ../../planning-artifacts/briefs/brief-DevFlow-2026-09-26/brief.md
  - ../../planning-artifacts/briefs/brief-DevFlow-2026-09-26/addendum.md
created: 2026-09-27
updated: 2026-09-27
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — they have been fully absorbed into the kernel and companions; consult them only if you need narrative rationale this contract intentionally omits.

# DevFlow Harness

## Why

**Mandate-meet + opportunity-capture.** Today's AI coding agents (Pi / OMP / Codex / Claude Code / DSH) and flagship LLMs (GPT / Claude / Gemini / MiniMax / DeepSeek / Qwen / Ollama) churn quarterly. Engineering teams that have not yet standardized on a stack pay a recurring audit cost when leadership asks "should we switch?" — DevFlow turns that question into a data point, not a debate. The BMAD Method skill catalog already supplies per-step *how* (deep-recon, spec, prd, architecture, build, retrospective); the **harness layer that makes the workflow fixed, the execution swappable, and the artifacts comparable does not exist as an integrated product** today. The platform serves small (1–5 person) AI-native teams who want to stop redefining "design" and "review" every time a new agent ships, and tech leads who need a defensible artifact (regression report) for stack recommendations. The mandate element is operational: artifacts must survive agent / LLM churn so audit, reproducibility, and per-step benchmarking remain trustworthy; the opportunity element is structural — the BMAD method layer is ready, and the harness slot above it is the one open.

## Capabilities

- **CAP-1 — Run a project end-to-end on `software-v1`.**
  - **intent:** operator can launch a project against pipeline `software-v1` and the harness executes the six fixed steps `research → design → coding → testing → review → delivery` in that order, each with its declared artifact contract.
  - **success:** 100% of `software-v1` runs traverse all six steps in the fixed order (SM-1), every step's output becomes the next step's input via content-hashed artifact lock (FR-11), and a closed project's run history is reconstructable from artifact hashes + executor tuples + the `acknowledgements/` directory alone (UJ-3).

- **CAP-2 — Swap a step's executor mid-project.**
  - **intent:** operator can change a step's Agent / LLM / Skills pin between runs and resume without re-executing previously locked steps; locked artifacts of prior steps remain immutable.
  - **success:** locked `SPEC.md` (Design) survives a Coding-step executor swap as Coding's input (FR-7), the previous executor's artifacts are retained in history (not deleted), and ≥ 95% of swaps resume from the next step without re-running prior steps (SM-2).

- **CAP-3 — Gate every step with a signed Acknowledgement record.**
  - **intent:** every step's Gate produces an independent, signed approval record that gates the next step's launch; human and automated approvals share the same record shape.
  - **success:** unsigned records are rejected (`acknowledgement_unsigned`, NFR-Sec-2); cross-project copy-paste forgery is rejected (`acknowledgement_path_mismatch`, AD-23); a closed project's Gate history is reproducible from artifact hashes + `acknowledgements/` alone (UJ-3); trivial / session-tier skipped-Gate paths write NO Acknowledgement record and instead carry `gate_mode: skipped` + implicit `verdict: accepted` on the step-end run event (FR-10, FR-12, AD-11).

- **CAP-4 — Persist every failure as an append-only error record and escalate via the retry ladder.**
  - **intent:** every failed step writes a structured error record (category, root_cause, correction, retry[], result) and the harness offers the next retry-ladder rung.
  - **success:** ≥ 95% of failures are logged (SM-3), the ladder executes rungs in order `same → same LLM → better LLM → different agent + promoted skill → human` with every rung attempt recorded (FR-15), rung 4 only consumes an operator-promoted Skill (returns `skill_not_promoted` otherwise; FR-6 + FR-23), and rung 5 (human) is operator-initiated — no auto-escalation.

- **CAP-5 — Recommend an Agent / LLM / Skills tuple per step from a regression set, not from raw success rate.**
  - **intent:** `bench <step>` returns a recommendation tuple from the regression set, gated by a comparability check.
  - **success:** at least one recommendation per step within 3 projects of usage (SM-4); `bench <step>` refuses with `regression_set_insufficient` when fewer than K=3 comparable runs exist for the `step × project-size-tier` cell (NFR-Reliab-3); cross-tier or cross-contract mixing returns `non_comparable_set` (FR-18); raw success rate is explicitly NOT a primary metric (SM-C1).

- **CAP-6 — Gate BMAD Skill version bumps behind the regression set.**
  - **intent:** a proposed Skill version bump must pass the regression set on affected steps before an operator can manually promote it.
  - **success:** 0 promoted regressions (SM-5); failed bumps record per-step regression results and produce `skill_regression_failed`; promotion requires a completed regression run with `result: pass` (else `skill_regression_missing`); bumps that pass sit in `pending_promotion` until operator approval (FR-22, FR-23, AD-6).

- **CAP-7 — Surface run state, error store, regression diffs, and benchmark output on the operator dashboard.**
  - **intent:** the dashboard is a read model over the canonical stores with a closed allowlist of write paths.
  - **success:** every dashboard view is a pure function of `(project_id, run_id, store_snapshot_at_query_time)` (AD-13); the only write paths are the six enumerated in AD-21 (`submit_acknowledgement`, `swap_executor_take_lock`, `trigger_skill_bump_regression`, `promote_skill_bump`, `cost_overrun_ack`, `regression_set_remove`); terminal-step status comes from `harness/gate_engine/step_status()` only (AD-24).

- **CAP-8 — Enforce per-tier cost ceilings with an operator ack on overrun.**
  - **intent:** the harness pauses the next step invocation on per-tier token-ceiling overrun and requires `cost_overrun_ack` before resuming.
  - **success:** a retry-ladder chain or Skill-bump regression pass cannot silently consume the project budget (NFR-Cost-2); ceilings default `trivial ≤ 5e5`, `session ≤ 5e6`, `epic ≤ 5e7`, `project ≤ 2e8` logged tokens (in+out); Skill-bump regression ceiling = 3× affected step's normal ceiling; cost telemetry surfaces on the dashboard (NFR-Cost-1, FR-24); ceilings are configurable per project YAML.

## Constraints

- Pipeline `software-v1` step list, order, and per-step contracts are immutable at runtime (FR-1, FR-2, AD-1); a bump is `software-v2`, never an in-place edit.
- Executor invocation is **harness-direct** via `ExecutorAdapter` (PRD A6, OQ-8 stance a): the harness owns auth, lifecycle (start / cancel / restart), and error mapping for Pi / OMP / Codex / Claude Code / DSH; **Herdr is an out-of-process observability feed** that consumes adapter events and is never the source of control state; a Herdr outage MUST NOT block a run.
- BMAD Skills are referenced in project YAML only as `name@version`; auto-upgrade is forbidden (FR-6, AD-6); the Skill Bump Registry is the only path to a new version; the retry-ladder rung 4 may ONLY consume an operator-promoted Skill (`skill_not_promoted` otherwise; FR-15 + FR-23).
- Canonical hashing (`sha256:`) flows through ONE function: `harness.canonical.canonical_bytes` (AD-17). CI lint rejects any direct `hashlib.sha256` outside `harness/canonical.py`. Canonicalization: JSON sorted keys + UTF-8 NFC + LF + no trailing newline; text LF + trailing newline; binary as-is.
- Locked artifacts, error records, Acknowledgement records, cost-ledger rows, and regression-set rows are immutable post-write; edits return `*_immutable` / `*_locked` errors. The error store, run event log, and cost ledger are append-only (FR-14, AD-4, AD-14).
- All signing uses Ed25519 with the harness key at `var/secrets/harness.key` (0600); unsigned artifacts and unsigned Acknowledgements are rejected (NFR-Sec-1, NFR-Sec-2); Acknowledgement signatures cover `{path triple, body}` via canonical bytes to defeat copy-paste forgery (AD-23).
- Step terminal status has ONE resolver: `harness/gate_engine/step_status(run_id, step) → {terminal: Done | Locked | Pending | Failed, gate_mode: enforced | skipped, ...}` (AD-24). Every dashboard view MUST call it.
- Operator dashboard write paths are exactly: `submit_acknowledgement`, `swap_executor_take_lock`, `trigger_skill_bump_regression`, `promote_skill_bump` (requires `regression_run_id`), `cost_overrun_ack`, `regression_set_remove` (AD-21). FastAPI router enforces via import-time allowlist.
- Size-tier Gate strictness: `trivial` = single confirm per step → Done (no formal Gate); `session` = light Gate on Design only; `epic` = Gates on all six + sub-Gates on key Coding stories + `human_first_stories: N`; `project` = full Gate + benchmark feedback (FR-12). Skipped Gates write NO Acknowledgement record.
- Per-tier cost ceilings (logged tokens, no USD): `trivial ≤ 5e5`, `session ≤ 5e6`, `epic ≤ 5e7`, `project ≤ 2e8`; Skill-bump regression ceiling = 3× affected step's normal ceiling; on overrun the harness pauses for `cost_overrun_ack`; configurable per project YAML (NFR-Cost-2).
- Layer dependency direction is enforced by `tools/check_layer_boundaries.py` in CI: `skills/`, `agents/`, and `herdr/` MAY NOT import anything under `harness.*` except the published-port allowlist in `harness/ports/__init__.py` (AD-26).
- Executor telemetry (Herdr events) does NOT include prompt bodies — only invocation metadata (`executor_id`, `step`, `timestamps`, `outcome`); prompt contents stay inside the Agent's own store (NFR-Privacy-1).
- A step with `mode: agent` cannot proceed past a Gate without an Acknowledgement; no silent auto-advance (NFR-Safety-1).

## Non-goals

- End-user / chat / consumer surface — operator dashboards only (PRD §5).
- Wrapping a single agent — DevFlow must support per-step swap (PRD §5).
- Replacing BMAD Method skills — DevFlow consumes `bmod-method` (PRD §5).
- Herdr as the control plane — Herdr is observation-only (PRD A6).
- Auto-promotion of BMAD Skill bumps — manual operator promotion only (FR-23).
- Native fine-tuning of any underlying LLM (PRD §5).
- Cross-org / multi-tenant in v1 — single-org, single-team (PRD §6.2).
- Pipelines beyond `software-v1` (`data-v1`, `ml-v1`) in v1 — vision-only (PRD §1).
- Dynamic Agent / LLM router (success-rate-based selection) — deferred to v2 (PRD §6.2, brief D6).
- Herdr lifecycle management of agents (start / stop / restart) — deferred to v2; harness owns lifecycle via `ExecutorAdapter` (AD-10).
- Native integration with every Agent in v1 — ship 1–2 adapters, add per executor (PRD §6.2, OQ-6).

## Success signal

A small (1–5 person) AI-native team opens DevFlow, picks pipeline `software-v1`, points it at a repo, and forgets which Agent ran it. After ≥ 3 comparable runs per step, `bench <step>` returns a data-driven Agent / LLM / Skills recommendation instead of an opinion. Six months later, a tech lead audits a closed project from artifact hashes + the `acknowledgements/` directory alone — no log scraping, no Slack archaeology, no "what agent was this?". The four signals together — fixed workflow adherence (SM-1), benchmark-driven recommendations (SM-4), audit-from-hashes reproducibility (SM-6), and zero promoted regressions (SM-5) — describe the world DevFlow creates.

## Assumptions

- v1 deploys single-node self-hosted; no cloud-managed dependency (PRD §6.2).
- Operator identity for human Acknowledgements is provisioned out-of-band (SSH key, OIDC, or harness-side UI token); identity-binding UX detail is non-blocker and lands in `bmad-ux`.
- LLM non-determinism is expected: ≥ 90% of locked artifacts have stable hash across identical-input re-renders; below that the platform reports `non_deterministic_executor` (SM-7).
- Herdr is an optional out-of-process sidecar that runs on the same host in v1 (spine Scope); multi-host Herdr is v2.

## Open Questions

- **OQ-6** Which 1–2 Agents ship as v1 executor adapters? (PRD OQ-6, spine OQ-6.) Required by spine AD-10(d); blocks any v1 run that wants non-`human` mode for any step but does not block the v1 harness binary.
- **OQ-7** BMAD Skill ownership of each step's artifact contract. PRD addendum §A6 proposes a mapping (see adopted companion `step-skill-map.md`); spec ratifies the mapping as proposed, not as final.
- **OQ-1** Static v1 router location: in-repo (spine AD-2 in-process) vs sidecar. Spine AD-2 picks in-process; user ratification deferred. If ratified the other way, the `ExecutorAdapter` seam absorbs the router without re-opening CAP-1 / CAP-2.

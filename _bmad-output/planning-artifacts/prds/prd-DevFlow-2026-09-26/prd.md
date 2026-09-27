---
title: DevFlow Harness
created: 2026-09-26
updated: 2026-09-27
status: final
---

# PRD: DevFlow Harness

> Headless draft PRD derived from the approved product brief (`brief-DevFlow-2026-09-26/brief.md`) and addendum (`addendum.md`). `[ASSUMPTION]` tags from the brief have been user-approved and are now written as facts. New `[NOTE FOR PM]` and `[OPEN]` callouts mark items needing downstream resolution (architecture / spec / ticket pre-split).

## 0. Document Purpose

This PRD is for the platform owner and the small (1–5 person) team building DevFlow, plus the downstream workflow owners who consume it — BMAD Method skill maintainers, executor-agent integrators (Pi / OMP / Codex / Claude Code / DSH), and the Herdr runtime team. It is structured glossary-first: every domain noun used in the FRs is defined once in §3 and used verbatim thereafter. Features are grouped (§4) with globally numbered FRs (FR-1 … FR-N) so downstream artifacts (architecture spine, spec, tickets) have stable references even if features are reorganized. Cross-cutting NFRs live in §11. Inline `[NOTE FOR PM]` callouts flag items needing PM attention during the architecture/spec phase; `[OPEN]` callouts mark items needing a downstream decision.

This PRD builds on (does not duplicate): `brief-DevFlow-2026-09-26/brief.md`, `brief-DevFlow-2026-09-26/addendum.md` (three-layer architecture, error schema, retry strategy, deferred findings D1–D6), `DevFlow_BMAD_Herdr_Design_v1.0.md` (v1.0 design doc), and `BMAD 对比提案.md` (Sep 26 2026 comparison proposal).

---

## 1. Vision

DevFlow is a long-lived AI agent platform for software development. The **development workflow stays fixed while the agents, LLMs and skills behind each step can be swapped and benchmarked across projects**. The workflow runs six steps — Research → Design → Coding → Testing → Review → Delivery — and treats every artifact (`research.md`, `design.md`, code, `test-report.json`, `review.md`) as a versioned contract that makes runs comparable and re-runnable.

The platform exists because today's AI coding agents are interchangeable for the user but opaque underneath: which agent + which LLM + which skill wins on which step of which project? DevFlow answers that by collecting structured runs, structured errors, and per-step success rates, then feeding the lessons back into Skills and step routing. It is not a coding agent itself and not a BMAD replacement — it sits one layer up as the **harness / control plane**, with **BMAD Method as the method layer** that supplies per-step skills (`bmad-deep-recon`, `bmad-spec`, `bmad-build`, `bmad-retrospective`, …), and a runtime called **Herdr** underneath as an optional execution observation layer.

Two years out, the target experience is: a small AI-native team opens DevFlow, picks the pipeline (`software-v1`, then `data-v1`, `ml-v1`), points it at a repo, and forgets which Agent ran it. The benchmark data lives in the open; third parties publish Agent/LLM/Skill packs that pass the regression set. BMAD ships core method skills; DevFlow is one of several harnesses that consume them.

---

## 2. Target User

### 2.1 Jobs To Be Done

- **Functional** — As a platform owner, I can run the same workflow against different Agent/LLM/Skill combinations so that, after N projects, I can recommend a stack from data instead of vibes.
- **Functional** — As a project runner, I can swap a step's executor mid-project without re-running prior steps, so I can recover from a bad skill choice without losing prior work.
- **Functional** — As a project runner, every failed step produces a structured error record, so I can later search "all failures caused by skill mis-versioning in project X" rather than scrolling Slack.
- **Emotional** — As a platform owner, I want the workflow shape to be stable across agents, so my team stops redefining "design" every time a new agent shows up.
- **Social** — As a tech lead, I want a defensible artifact (regression report) for my org's Agent/LLM recommendation, so the recommendation is data, not opinion.

### 2.2 Non-Users (v1)

- Teams that have already standardized on one agent stack and do not plan to benchmark alternatives (DevFlow adds ceremony with no benefit).
- End users of consumer software products built with DevFlow (DevFlow has no end-user surface; output is operator dashboards).
- Multi-tenant / cross-org operators (single-org / single-team only in v1).
- Teams that want a chat-first AI product (DevFlow is workflow + dashboards, not chat).

### 2.3 Key User Journeys

**UJ-1. Mei runs a new SAP-BTP app project end-to-end on DevFlow.**
- **Persona + context:** Mei, platform/DevEx engineer at a small consulting firm. She has three SAP-BTP projects queued this quarter and wants the same six-step workflow on each.
- **Entry state:** Authenticated to DevFlow (operator console). Has a project config template for SAP-BTP projects.
- **Path:** (1) Create project `P3-sap-btp-app` from the SAP-BTP config template; (2) start pipeline `software-v1`; (3) approve the Research Gate after reading `research.md`; (4) approve the Design Gate after the PRD / architecture / spec are reviewed; (5) let Coding run with `human_first_stories: 2` so she co-pilots the first two stories; (6) approve the Testing Gate on the `test-report.json`; (7) approve the Review Gate on `review.md`; (8) the Delivery artifact is locked and the run is closed.
- **Climax:** Mei sees the Delivery artifact (signed `delivery.json`) and the run's per-step Agent/LLM/Skill tuple is persisted. The benchmark store now has a third comparable data point for the Coding step.
- **Resolution:** Mei runs the benchmark on the Coding step (`bench coding`) and gets a recommendation based on three prior runs, not vibes.
- **Edge case:** If Research fails (skill mis-versioning), the error record is written and the harness proposes a retry with a bumped BMAD Skill version; Mei approves and the step re-runs without re-doing earlier steps.

**UJ-2. Arjun swaps the Coding step's executor mid-project.**
- **Persona + context:** Arjun, solo consultant mid-engagement. Coding is running on `agent: codex, model: gpt-5`, but `gpt-5` is producing flaky tests on his SAP-specific code.
- **Entry state:** Project `P7-sap-mig` has `design` locked, `coding` is in progress, `test-report.json` not yet produced.
- **Path:** (1) Arjun edits the project YAML — changes the `coding` step's `agent` and `model` only; (2) Arjun bumps the BMAD Skill pin from `bmad-build@0.4.2` to `bmad-build@0.4.3` (regression-passed version); (3) he resumes the run from the Coding step; (4) Coding re-runs; (5) the new run inherits the locked `design` artifact and writes a new `test-report.json` and `coding` artifact; (6) the previous Coding artifacts are retained in the error / history store, not deleted.
- **Climax:** Coding succeeds on the new executor; Testing proceeds normally. The old Coding run is preserved as a comparable data point.
- **Resolution:** Arjun sees two `coding` artifact versions in the project history; the latest is locked and gates the next step.
- **Edge case:** If the new executor fails twice, the harness escalates per the retry ladder (FR-15) and asks for human intervention before the third attempt.

**UJ-3. Lin audits a project's run history six months later.**
- **Persona + context:** Lin, tech lead. A client is asking why a past project chose a particular Agent/LLM/Skill combo.
- **Entry state:** Authenticated to DevFlow. Project `P11-foo` is closed.
- **Path:** (1) Lin opens `P11-foo`; (2) she sees the run timeline (six steps, each with start/end, executor tuple, artifact hash); (3) she clicks the Design step and sees its locked `SPEC.md`; (4) she clicks the Coding step and sees two `coding` artifact versions (a swap happened mid-run, UJ-2); (5) she opens the error store filter, filters by category=`skill`, and sees the exact error record and the resolution (bump + retry).
- **Climax:** Lin produces a one-page audit answer from artifact hashes, executor tuples, and the error store, without re-running anything.
- **Resolution:** Lin's audit answer cites content hashes (`sha256:abcd…`), not vibes.
- **Edge case:** If an artifact was never locked (a pre-v1 run), Lin sees a `not_locked` flag and the platform tells her which step did not have a Gate.

**Scope dial:** Heavier (UJs feed architecture and ticketing). Each UJ maps to a capability cluster below; architecture/spine must support each step in the chain.

---

## 3. Glossary

- **Pipeline** — A named, versioned, immutable workflow definition (e.g. `software-v1`). The pipeline's six steps and their contracts are fixed for the version. Projects bind to a pipeline by reference.
- **Step** — One of `research | design | coding | testing | review | delivery`. A pipeline is a sequence of steps; each step has an artifact contract, a Gate, and an executor slot.
- **Project** — A single unit of work bound to one pipeline, one project-level config (YAML), and a run history. Identified by `project_id`.
- **Run** — One execution of a project's pipeline, producing a series of step outputs. A project has N runs over its lifetime.
- **Step output** — The artifact produced by a step in a run (e.g. `research.md`, `SPEC.md`, `test-report.json`). Content-hashed and version-locked at the Gate.
- **Executor** — The runtime that performs a step. Either a human (`mode: human`) or an Agent + LLM + Skills tuple (`mode: agent`). Executor choice is per-step, per-project.
- **Agent** — A coding/execution agent runtime (Pi, OMP, Codex, Claude Code, DSH). Agent is to executor what engine is to vehicle.
- **LLM** — The large language model backing an Agent in `mode: agent` runs (GPT, Claude, Gemini, MiniMax, DeepSeek, Qwen, Ollama).
- **Skill** — A BMAD Method skill (e.g. `bmad-deep-recon@0.4.2`) used as the "how" for a step. Skills are pinned per-step in the project YAML.
- **Gate** — The handoff between two steps. Requires an approved Acknowledgement record (human or automated) before the next step's input is unlocked.
- **Acknowledgement** — The signed record that a Gate was approved. Either human (signed comment / approval record) or automated (regression check passed).
- **Artifact lock** — A step output that has cleared its Gate. Locked artifacts are immutable and content-addressed.
- **Artifact hash** — `sha256:` content hash of a step output. Used for locking and cross-run comparison.
- **Artifact contract** — The schema a step output must satisfy to enter the Gate (e.g. `SPEC.md` schema; `test-report.json` schema). Owned by the BMAD step skill.
- **Error record** — A structured entry in the error store after a step fails. Has `category`, `root_cause`, `correction`, `retry`, `result`. Append-only.
- **Error category** — Closed list: `requirement | research | design | coding | testing | review | agent | llm | skill | tool | environment | integration`.
- **Retry ladder** — The escalation order for a failing step: same Agent + same LLM + same Skill → different LLM → different Agent + better LLM → different Agent + different LLM + improved Skill → human. Each rung is persisted in the error record.
- **Benchmark** — A query against the regression set: "which Agent/LLM/Skill wins on step X, on a defined test set, with a defined metric?" Output is a recommendation tuple.
- **Regression set** — A curated set of past runs (artifacts + executor tuples + outcomes) used to benchmark new skills / agents / LLMs. Updated as new runs land.
- **Harness** — DevFlow itself. Owns pipeline definition, project state, Gates, locks, error store, benchmark, metrics.
- **Method layer** — BMAD Method skills (`bmod-method`). Owns the "how" of each step. Pinned versions are treated as Skill bumps that must pass the regression set.
- **Execution layer** — Herdr runtime. Optional observation of the executors (Pi, OMP, Codex, Claude Code, DSH). Not the control plane.
- **Project size tier** — One of `trivial | session | epic | project`. Drives Gate strictness (see `addendum.md §4`).
- **Operator dashboard** — The v1 UI surface. Run status, error store, regression diffs, benchmark output. Not an end-user product.
- **BMAD Skill pin** — A `name@version` reference to a BMAD Method skill in a project YAML. Pinning prevents auto-upgrade.
- **Skill bump** — A BMAD Skill version change that must pass the regression set before it can replace a pin.
- **Done** — The terminal state of a `trivial`-tier step or run. `Done` is reached when the operator confirms completion via a single confirm action (FR-12); no Acknowledgement record is required, but the confirmation is recorded as `confirm_id` on the run event (NFR-Obs-1) so the audit trail can distinguish `Done` from a passed Gate. `Done` is distinct from `locked`: `locked` artifacts go through a Gate; `Done` does not.

---

## 4. Features

### 4.1 Pipeline Definition & Versioning

**Description:** DevFlow ships a canonical pipeline (`software-v1`) with six fixed steps and their artifact contracts. Pipelines are versioned and immutable at runtime: a project bound to `software-v1` cannot silently get `software-v2` features. New pipeline versions are added, not edited. Realizes UJ-1.

**Functional Requirements:**

#### FR-1: Ship a canonical pipeline `software-v1`

DevFlow ships with a single, immutable pipeline `software-v1` that defines exactly six steps in the order `research → design → coding → testing → review → delivery`. Each step has a fixed name, an artifact contract reference, and a Gate. Realizes UJ-1.

**Consequences (testable):**
- A project YAML with `pipeline: software-v1` is accepted and runnable.
- A project YAML with any other pipeline name is rejected with a `pipeline_not_found` error at load time.
- The pipeline definition's `version` field is `software-v1` (string) and immutable in the running harness.

**Out of Scope:**
- Pipelines other than `software-v1` in v1 (`data-v1`, `ml-v1` are vision-only in §1).

#### FR-2: Immutable pipeline versions

Once a pipeline version is loaded, its step list and per-step contracts cannot be edited by any project config, operator action, or skill update. Bumping a pipeline is a new version (`software-v2`), not a mutation of `software-v1`. Realizes UJ-1, UJ-2.

**Consequences (testable):**
- A skill bump or project YAML edit cannot add, remove, or reorder steps in `software-v1`.
- A request to "edit `software-v1`" returns `pipeline_immutable`.

#### FR-3: Per-step artifact contracts

Each of the six steps declares its input artifact (the previous step's locked output) and its output artifact (its own locked output). Contracts are referenced from BMAD Method skills (`bmad-spec` owns the `SPEC.md` contract, etc.). Realizes UJ-1, UJ-3.

**Consequences (testable):**
- Coding's input is the locked `SPEC.md`; Coding cannot start until `SPEC.md` is locked.
- Testing's input is the locked `coding` artifact; Testing cannot start until it is locked.

**Notes:**
- `[OPEN]` Per-step artifact schema sources: which BMAD skill owns which contract. Deferred to `bmad-architecture` step.

---

### 4.2 Project Config & Executor Selection

**Description:** A project is defined by a YAML config that names the pipeline, size tier, and per-step executor tuples (Agent + LLM + Skills with `@version`). The config is the single source of truth for "what runs each step". Realizes UJ-1, UJ-2.

**Functional Requirements:**

#### FR-4: Project YAML schema

Each project has a YAML config that declares `project`, `pipeline`, `size`, and per-step executor tuples with the shape `{ mode, agent, model, skills: [<skill>@<version>], ... }`. Realizes UJ-1.

**Consequences (testable):**
- A project YAML missing `pipeline` is rejected with `pipeline_required`.
- A project YAML with `pipeline: software-v1` and a `steps` block referencing unknown step keys is rejected with `unknown_step`.
- A project YAML with an unpinned skill (`bmad-spec` instead of `bmad-spec@0.4.2`) is rejected with `skill_pin_required`.

#### FR-5: Per-step executor selection

Each step's executor is independently selectable as `human` or as an Agent + LLM + Skills tuple. No step is forced to one or the other. Realizes UJ-2.

**Consequences (testable):**
- A project can set `research.mode: agent` and `review.mode: human` simultaneously.
- A project can mix executors across the six steps in any combination.
- A step with `mode: human` does not require `agent` or `model`.

#### FR-6: Skill version pinning

BMAD Skills are referenced in project YAMLs as `name@version`. Pins are enforced at load time; auto-upgrade is not allowed. Realizes UJ-2.

**Consequences (testable):**
- `bmad-build@0.4.2` is the exact version that runs; `0.4.3` is not picked up unless the YAML is edited.
- A bumped skill version that fails the regression set produces a `skill_regression_failed` error record and cannot replace an active pin.

**Notes:**
- `[NOTE FOR PM]` Decision D4 (BMAD Skill version pin policy) from the brief: pin + regression is the v1 stance. Confirm during architecture review.

#### FR-7: Mid-project executor swap

A project YAML can be edited between runs (not during a running step). On resume, the new executor tuple applies to the current and subsequent steps without re-running prior locked steps. Realizes UJ-2.

**Consequences (testable):**
- After a Coding executor swap, the locked `SPEC.md` from Design is unchanged and re-used as Coding's input.
- The previous Coding artifact is preserved in history, not deleted.

**Out of Scope:**
- Hot-swapping executors mid-step (swap only between runs).

---

### 4.3 Step Execution & Gates

**Description:** Each step runs against the locked artifact from the previous step, produces an output artifact, and stops at a Gate. The Gate requires an Acknowledgement before the next step's input is unlocked. Realizes UJ-1.

**Functional Requirements:**

#### FR-8: Step executor invocation

A step with `mode: agent` invokes the named Agent + LLM with the pinned Skills. The harness owns the invocation contract: the locked input artifact, the BMAD Skill versions, and the executor tuple. Realizes UJ-1, UJ-2.

**Consequences (testable):**
- A Coding step invocation includes the locked `SPEC.md`, the `bmad-build@<version>` skill, and the named Agent/LLM.
- An invocation that fails to start (agent unreachable, skill missing) produces an error record of category `agent` or `skill`.

#### FR-9: Step output gating

A step's output is written to the run's artifact store as `pending` until the Gate is acknowledged. The pending artifact is not visible to subsequent steps. Realizes UJ-1, UJ-3.

**Consequences (testable):**
- A pending `SPEC.md` is not used as Coding's input.
- The Gate verdict (accepted / accepted-with-open-items / rejected) is recorded on the run.

#### FR-10: Gate Acknowledgement

A Gate is acknowledged by either a human (signed approval record on the artifact) or an automated check (regression / benchmark pass). Both produce an Acknowledgement record with `acknowledger` (human id or check name), `timestamp`, and `verdict`. Realizes UJ-1, UJ-3.

**Consequences (testable):**
- An Acknowledgement with `verdict: accepted` advances the run to the next step.
- An Acknowledgement with `verdict: rejected` blocks the next step and writes an error record.
- If a Gate is **not enforced by size tier** (FR-12 — e.g., `trivial` tier runs and the `session` Research Gate are skipped), no Acknowledgement record is required; the step transitions to `locked` on step-end with an implicit `verdict: accepted` and a `gate_mode: skipped` marker on the run event (NFR-Obs-1). A skipped Gate is never recorded as an explicit Acknowledgement — this is the only path to `locked` without one.

**Notes:**
- ✅ **D5 RESOLVED (2026-09-27):** v1 Gate acceptance shape is the **independent approval record** (`acknowledgements/<step>-<artifact-hash-prefix>.json`). See OQ-5 for the full record shape. The architectural question (where the file lives, signature scheme, retention policy) moves to `bmad-architecture` as a non-blocker.

#### FR-11: Artifact lock on Gate

When a Gate returns `verdict: accepted`, the artifact transitions from `pending` to `locked`. A locked artifact is immutable and content-hashed (`sha256:`). Realizes UJ-1, UJ-2, UJ-3.

**Consequences (testable):**
- A locked artifact cannot be edited; edits produce `artifact_locked` errors.
- The hash is stable across re-reads.
- A locked artifact remains the input to all subsequent step runs until the project is re-opened with an explicit unlock.

#### FR-12: Per-step size-tier Gate strictness

Gate strictness scales with project size tier: `trivial` (single operator `confirm` per step → `Done`, no formal Gate — see Glossary), `session` (light Gate on Design only; other steps `gate_mode: skipped` per FR-10's skipped-Gate clause), `epic` (Gates on all six steps; sub-Gates on key Coding stories; human-first for the first N stories), `project` (full Gate at every step; benchmark fed back into Skill Registry). Realizes UJ-1.

**Consequences (testable):**
- A `trivial` project with one step unconfirmed is held `pending`; on operator `confirm`, the step transitions to `Done` with `confirm_id` recorded (NFR-Obs-1). The run-status surface shows `Completed` (FR-24).
- A `session` project's Research step ends with `gate_mode: skipped` (FR-10 clause) and the artifact transitions to `locked` on step-end without an Acknowledgement.
- An `epic` project cannot start Coding without an explicit Design Gate Acknowledgement (FR-10).
- A `session` tier project's Design Gate is enforced (light Gate); the operator dashboard shows it as `awaiting_acknowledgement` until approved.

---

### 4.4 Error Store & Retry Ladder

**Description:** Every failed step writes a structured error record and the harness offers the next retry-ladder rung, persisted at every step. Realizes UJ-1, UJ-3.

**Functional Requirements:**

#### FR-13: Structured error record

A failed step writes an error record with `category` (closed list), `root_cause[]`, `correction[]`, `retry[]`, `result`. Schema is fixed (see `addendum.md §5`). Realizes UJ-1, UJ-3.

**Consequences (testable):**
- Every failed step has exactly one error record in the error store.
- The `category` field is one of the 12 values in the closed list.
- The record is append-only — it cannot be edited after creation.

#### FR-14: Append-only error store

The error store is append-only. Each step failure appends a new record; existing records are never mutated. Realizes UJ-1, UJ-3.

**Consequences (testable):**
- A read of the error store returns records in append order with stable hashes.
- An attempt to edit or delete an existing record returns `error_store_immutable`.

#### FR-15: Retry ladder

A failed step's retry options are presented in order: (1) same Agent + same LLM + same Skill; (2) same Agent + different LLM; (3) different Agent + better LLM; (4) different Agent + different LLM + different Skill — **the Skill at rung 4 must already be an operator-promoted bump** (FR-6 forbids auto-upgrade, FR-23 requires manual operator promotion; the harness does not bump Skills on the operator's behalf); (5) human intervention. The harness executes rung N+1 only if rung N is logged as `FAIL` in the error record. Realizes UJ-1.

**Consequences (testable):**
- A retry never skips a rung silently; every rung attempt is recorded.
- A retry at rung 4 with a Skill that has not been operator-promoted is rejected with `skill_not_promoted`; the operator must edit the project YAML (FR-6) and re-queue the retry.
- A retry that fails rung 4 (with an operator-promoted Skill) produces a `human_intervention_required` state and pauses the step.

**Notes:**
- `[NOTE FOR PM]` Failure at rung 4 must pause, not auto-escalate to rung 5. Rung 5 (human) is operator-initiated.

#### FR-16: Error filtering and search

The operator dashboard exposes filters on the error store: by project, by step, by `category`, by Agent/LLM/Skill tuple, by date. Realizes UJ-3.

**Consequences (testable):**
- A filter `category=skill, project_id=P11-foo` returns the matching records deterministically.
- A filter on a non-existent `category` value returns `category_not_found`.

---

### 4.5 Artifact Versioning & Reproducibility

**Description:** Each step output is content-addressed; each run is reproducible from the artifact hashes and the executor tuples. A past run can be replayed (artifact re-render) by re-invoking the same Agent + LLM + Skill tuple against the same locked inputs. Realizes UJ-3.

**Functional Requirements:**

#### FR-17: Content-addressed artifacts

Every step output is stored with a `sha256:` content hash. Two step outputs with identical content have identical hashes. Realizes UJ-3.

**Consequences (testable):**
- A locked artifact's hash is stable across reads.
- Re-running a step with identical inputs and executor tuple produces the same hash (or a documented hash mismatch is reported as `non_deterministic_executor`).

#### FR-18: Cross-run comparability

A benchmark query returns comparable runs from the regression set: same step, same project size tier, same artifact contract. Runs that differ on any of these are flagged `non_comparable` and not mixed. Realizes UJ-3.

**Consequences (testable):**
- A benchmark query that mixes `session` and `epic` runs without explicit override returns `non_comparable_set`.
- A benchmark query that includes a run with an unmapped `category` is filtered out by default.

#### FR-19: Audit trail from hashes

A past project's run history can be reconstructed from artifact hashes and executor tuples alone — no log scraping required. Realizes UJ-3.

**Consequences (testable):**
- For a closed project, the harness can list every step's `(input_hash, output_hash, executor_tuple, timestamp)` without reading logs.

---

### 4.6 Benchmark & Skill Promotion

**Description:** DevFlow picks a step's recommended Agent/LLM/Skill tuple from a regression set, not from raw success rate. BMAD Skill bumps must pass the regression set before promotion. Realizes G5, brief SM-4, SM-5.

**Functional Requirements:**

#### FR-20: Regression set

The harness maintains a regression set: a curated set of past runs across projects with stable artifact hashes, executor tuples, and outcomes. New runs are added on close; removed only via an explicit `regression_set_remove` action. Realizes UJ-1.

**Consequences (testable):**
- A `bench coding` query selects runs from the regression set with `step=coding` and a defined metric.
- An addition to the regression set is append-only.

#### FR-21: Benchmark query

A benchmark query takes (step, optional project size tier, optional artifact contract version) and returns the recommended Agent/LLM/Skill tuple ranked by the regression-set metric, not raw success rate. Realizes UJ-1, brief SM-4.

**Consequences (testable):**
- A benchmark query returns a recommendation tuple, not a single number.
- The metric definition is recorded with each benchmark run; two metrics on the same set can produce different recommendations.

#### FR-22: BMAD Skill bump regression gate

A proposed BMAD Skill version bump (`x.y.z → x.y.z+1`) must pass the regression set on the affected steps before it can replace a pin in any active project. A bump that fails produces a `skill_regression_failed` error and is held back. Realizes brief SM-5.

**Consequences (testable):**
- A bump that fails on the regression set does not become a valid pin in any new project.
- The failure is recorded with the per-step regression results.

#### FR-23: Manual promotion of Skill bumps

Bumps are manually promoted by an operator after the regression gate passes. Auto-promotion is not allowed in v1. Realizes brief rejection #4.

**Consequences (testable):**
- A `bmad build@0.4.3` regression-passed bump is held in `pending_promotion` until an operator approves.

**Out of Scope:**
- Auto-promotion of bumps.

---

### 4.7 Operator Dashboard (v1 surface)

**Description:** The v1 UI is operator-only: run status, error store, regression diffs, benchmark output. No end-user / chat surface in v1. Realizes UJ-1, UJ-3.

**Functional Requirements:**

#### FR-24: Run status surface

The dashboard shows each project's current run, the per-step state (`pending | locked | failed`), the executor tuple, and the artifact hash for each completed step. Realizes UJ-1, UJ-3.

**Consequences (testable):**
- A `locked` step's artifact hash is shown.
- A `failed` step links to its error record.

#### FR-25: Error store surface

The dashboard exposes the filters in FR-16 plus a per-record view (full error record, including `root_cause`, `correction`, `retry[]`, `result`). Realizes UJ-3.

**Consequences (testable):**
- A filter `category=skill` returns the matching records; clicking one shows the full record.

#### FR-26: Regression diff surface

The dashboard shows the result of a Skill bump's regression run: which runs passed, which failed, which were non-comparable. Realizes brief SM-5.

**Consequences (testable):**
- A bump's regression diff view shows the per-step pass/fail counts.

#### FR-27: Benchmark output surface

The dashboard shows a benchmark query's recommendation tuple, the metric used, and the contributing runs. Realizes brief SM-4.

**Consequences (testable):**
- A `bench coding` output lists the recommendation, the metric, and N contributing runs with hashes.

**Out of Scope:**
- End-user / chat surface.
- Cross-tenant / multi-org dashboards.

---

### 4.8 Herdr Execution Observation (Optional)

**Description:** Herdr is the **Execution layer** (see §3 Glossary). It watches executor activity (Pi, OMP, Codex, Claude Code, DSH) and reports it to the harness. It does NOT own state, Gates, or the error store. Realizes brief rejection #1, brief `addendum.md §2`.

**Functional Requirements:**

#### FR-28: Herdr is observation-only

Herdr observes executor invocations (start / end / output produced) and forwards structured events to the harness. Herdr does not decide Gates, does not store errors, does not advance runs. Realizes brief rejection #1.

**Consequences (testable):**
- A Herdr outage does not block a run; the harness invokes executors directly via the `ExecutorAdapter` interface (resolved under OQ-8, 2026-09-27 — stance (a)). Herdr remains an external observability feed that consumes adapter events for out-of-process dashboards and audit; the feed is advisory and never authoritative.
- Herdr events are advisory and do not override harness state.

#### FR-29: Herdr event schema

Herdr events are emitted in a fixed schema: `executor_id`, `step`, `project_id`, `started_at`, `ended_at`, `outcome`. Events are append-only and signed. Realizes UJ-3.

**Consequences (testable):**
- An event with a missing `executor_id` is rejected by the harness ingest path.

**Out of Scope:**
- Herdr owning the control plane.
- Herdr lifecycle management of agents (start / stop / restart) in v1.

**Notes:**
- `[NOTE FOR PM]` Decision D3 (Herdr v1 scope: observe-only vs. lifecycle) from the brief. v1 stance: observe-only. Revisit at v2.

---

## 5. Non-Goals (Explicit)

- **Not an end-user / chat product.** DevFlow is operator dashboards only; no consumer UI, no chat surface, no end-user notification.
- **Not a single-agent wrapper.** DevFlow must support swapping Agent/LLM/Skill per step; "wrap one agent" is a non-goal.
- **Not a BMAD replacement.** DevFlow consumes BMAD Method skills (`bmod-method`); it does not redefine the step contracts owned by BMAD skills.
- **Not a control plane for Herdr.** Herdr observes; the harness controls.
- **Not auto-promoting BMAD Skill upgrades.** Manual promotion only in v1 (brief rejection #4).
- **Not a fine-tune of any underlying LLM.** The platform consumes third-party LLMs; it does not train its own.
- **Not a cross-org / multi-tenant platform.** Single-org / single-team in v1.
- **Not a `data-v1` or `ml-v1` pipeline.** Vision-only in v1 (`addendum.md §4`); only `software-v1` ships in v1.

---

## 6. MVP Scope

### 6.1 In Scope

- `software-v1` pipeline with the six fixed steps and their artifact contracts (FR-1, FR-2, FR-3).
- Project YAML schema with per-step executor tuples and skill pins (FR-4, FR-5, FR-6).
- Mid-project executor swap (FR-7).
- Step executor invocation, gating, Acknowledgement, artifact lock, size-tier strictness (FR-8 … FR-12).
- Structured error store and retry ladder (FR-13 … FR-16).
- Content-addressed artifacts, cross-run comparability, audit trail from hashes (FR-17 … FR-19).
- Regression set, benchmark query, BMAD Skill bump regression gate, manual promotion (FR-20 … FR-23).
- Operator dashboard (run status, error store, regression diff, benchmark output) (FR-24 … FR-27).
- Herdr as observation-only, with event schema (FR-28, FR-29).

### 6.2 Out of Scope for MVP

- Native integration with every Agent (start with 1–2, add adapters per executor) — `[NOTE FOR PM]` pick the v1 two in the architecture step.
- Dynamic Agent/LLM router (success-rate-based selection) — `[NOTE FOR PM]` deferred to v2 per brief D6.
- Herdr lifecycle management (start/stop/restart agents) — deferred to v2.
- Cross-org / multi-tenant — `[NON-GOAL for MVP]`.
- Native fine-tuning of LLMs — `[NON-GOAL for MVP]`.
- `data-v1` / `ml-v1` pipelines — `[NON-GOAL for MVP]`, vision-only.
- Auto-promotion of Skill bumps — `[NON-GOAL for MVP]`.
- Auto-scaling / cloud execution of Herdr — `[NON-GOAL for MVP]`.

---

## 7. Success Metrics

**Primary**
- **SM-1**: Workflow adherence — % of runs using the six fixed steps in the fixed order. **Target:** 100% of runs on `software-v1`. **Validates:** FR-1, FR-2, FR-12. **Counter:** none (this is structural).
- **SM-2**: Mid-project swap success — % of executor swaps that resume from the next step without re-running prior steps. **Target:** ≥ 95% of swaps. **Validates:** FR-7, FR-11.
- **SM-3**: Error log completeness — % of failed steps that have a complete error record (`category`, `root_cause`, `correction`, `retry`, `result`) in the store. **Target:** ≥ 95% of failures. **Validates:** FR-13, FR-14.
- **SM-4**: Benchmark-driven recommendation — number of steps for which the platform has produced a benchmark-driven recommendation from ≥ 3 comparable runs. **Target:** at least one recommendation per step within 3 projects of usage. **Validates:** FR-20, FR-21, FR-27.
- **SM-5**: Skill-bump regression gate — % of BMAD Skill bumps that pass the regression set before promotion, and 0 promoted regressions. **Target:** 100% pass; 0 promoted regressions. **Validates:** FR-22, FR-23.

**Secondary**
- **SM-6**: Audit-from-hashes — % of closed projects whose full run history can be reconstructed from artifact hashes + executor tuples alone. **Target:** 100%. **Validates:** FR-19.
- **SM-7**: Artifact reproducibility — % of locked artifacts whose hash is stable across re-renders with identical inputs and executor tuples. **Target:** ≥ 90% (some LLM non-determinism is expected; the platform reports `non_deterministic_executor` for the rest). **Validates:** FR-17.

**Counter-metrics (do not optimize)**
- **SM-C1**: Raw per-step success rate — explicitly NOT a primary metric. Counterbalances SM-4; the recommendation is from the regression set on a defined metric, not from raw success rate. Validates brief clarification #3.
- **SM-C2**: Number of projects — NOT a primary metric. DevFlow value is comparability, not volume; a small team running 3 projects is the success case.
- **SM-C3**: Number of Skill bumps promoted — NOT a primary metric. Promotion is gated by regression; bump volume is irrelevant.

---

## 8. Open Questions

Numbered. Items needing a downstream decision (architecture, spec, ticketing) or a later session.

- **OQ-1** Where does the static v1 router live — in this repo or as a sidecar service? (Brief open question; deferred to `bmad-architecture`.)
- **OQ-2** ✅ **RESOLVED (2026-09-27):** What is the smallest v1 schema for `test-report.json`? — **Minimum v1 schema** (locked in this PRD; `bmad-spec` elaborates, does not redesign): top-level fields `step` (fixed `"testing"`), `run_id`, `project_id`, `executor_tuple` (`agent` / `model` / `skills[]`), `started_at`, `ended_at`, `outcome` (`pass | fail | error`), `cases[]` (each `{id, name, acceptance_ref, status, evidence}`), `acceptance_coverage` (FR-pass ratio). Schema source-of-truth file lives at `_bmad-output/contracts/test-report.schema.json`; spec step must not silently extend without versioning the schema.
- **OQ-3** Herdr v1 scope: observe-only or also process lifecycle? (Brief open question; PRD stance is observe-only — confirm during architecture review.)
- **OQ-4** BMAD Skill version pin policy: pin in project YAML (`@x`) vs. follow latest with regression gate? (Brief open question; PRD stance is pin + regression — confirm during architecture review.)
- **OQ-5** ✅ **RESOLVED (2026-09-27):** What is the v1 acceptance shape for "human approval Gate"? — **Independent approval record** (`acknowledgements/<step>-<artifact-hash-prefix>.json`) carrying `acknowledger` (human id or check name), `timestamp`, `verdict` (`accepted | accepted-with-open-items | rejected`), `signature`, and a back-reference to the artifact hash. Lives next to the artifact, not inside it (artifact stays immutable per FR-11). Automated acknowledgements use the same record shape with `acknowledger = check:<name>`. Matches UJ-3's audit-from-hashes requirement: a closed project's Gate history is reproducible from artifact hashes + the `acknowledgements/` directory alone.
- **OQ-6** Which 1–2 Agents ship as v1 executor adapters? (Out-of-MVP note; pick in architecture step.)
- **OQ-7** BMAD Skill ownership of each step's artifact contract — which skill owns which contract? (FR-3 notes; deferred to `bmad-architecture`.)
- **OQ-8** ✅ **RESOLVED (2026-09-27):** **Harness-direct executor invocation path — stance (a) adopted.** The harness owns the executor invocation contract: auth, lifecycle (start / cancel / restart), and error mapping per Agent (Pi / OMP / Codex / Claude Code / DSH). Herdr's role is rescoped to **external observability** (out-of-process event stream for operator dashboards, third-party audit, and post-hoc replay), not a control plane. Architecture must specify: (i) `ExecutorAdapter` interface (`start(capability) / cancel(id) / status(id) → outcome`); (ii) per-executor adapter implementations for the v1 1–2 Agents picked under OQ-6; (iii) the seam where Herdr consumes events from the adapter (advisory stream, never authoritative). Herdr outage no longer blocks a run — direct invocation already satisfies FR-28's first consequence. **Phase-blocker for `bmad-architecture` lifted; OQ-8 no longer gates downstream work.** See `addendum.md §A2` for stance (b) and why it was rejected.

---

## 9. Assumptions Index

The brief's `[ASSUMPTION]` tags are approved and now written as facts; they are re-listed here for traceability:

- **A1** (Brief, "What Makes This Different" / "Not a single-agent wrapper, not a UI product, not a chat tool") — Written as fact in §1 Vision, §5 Non-Goals.
- **A2** (Brief, "Vision / Long-tail risk") — Mitigations written as facts in §1 Vision ("workflow fixed, artifact contract clean") and §5 Non-Goals.

New assumptions made in this PRD:

- **A3** Error store is append-only and immutable (FR-14); rationale: an editable store is a worse audit trail than Slack. Counter would be "store compaction for size" — deferred to v2.
- **A4** v1 has exactly one pipeline (`software-v1`); rationale: more pipelines in v1 dilute the benchmark set. Additional pipelines (`data-v1`, `ml-v1`) are vision-only.
- **A5** Herdr is observation-only in v1 (FR-28); rationale: control-plane-vs-observation is a load-bearing distinction in the brief (`addendum.md §2`). On 2026-09-27, scope was refined (see A6) — Herdr is now *external observability* (advisory event stream), not an in-process observation path.
- **A6** (resolved 2026-09-27, OQ-8) The harness owns the executor invocation contract (auth / lifecycle / error mapping) for Pi / OMP / Codex / Claude Code / DSH via an `ExecutorAdapter` interface. Herdr consumes adapter events as an out-of-process observability feed; the feed is never authoritative. Rationale: stance (a) was already implied by FR-28 ("the harness invokes executors directly") and was the only stance compatible with UJ-2 (mid-project executor swap must work when Herdr is unavailable). Stance (b) was rejected because it re-routes control through Herdr and breaks the harness's authority over Gates.
- **A7** (resolved 2026-09-27, OQ-2) The minimum v1 `test-report.json` schema is: top-level `step` (`"testing"`), `run_id`, `project_id`, `executor_tuple` (`agent` / `model` / `skills[]`), `started_at`, `ended_at`, `outcome` (`pass | fail | error`), `cases[]` (each `{id, name, acceptance_ref, status, evidence}`), `acceptance_coverage` (FR-pass ratio). Schema source-of-truth: `_bmad-output/contracts/test-report.schema.json`. Rationale: minimum set needed to satisfy FR-3 (artifact contract), FR-13 (error record linkage), and UJ-3 (audit-from-hashes). Anything beyond is `bmad-spec`'s job to elaborate under versioning, not redesign.
- **A8** (resolved 2026-09-27, D5 / OQ-5) v1 Gate acceptance is an independent approval record at `acknowledgements/<step>-<artifact-hash-prefix>.json` carrying `acknowledger`, `timestamp`, `verdict`, `signature`, plus a back-reference to the artifact hash. Rationale: matches FR-11 (locked artifacts are immutable) and UJ-3 (audit from hashes + acknowledgements directory alone). Commit-comment and artifact-embedded signatures were rejected because they couple the Acknowledgement to the artifact's content or to VCS, both of which break under mid-project executor swap (UJ-2).

---

## 10. Cross-Cutting NFRs *(Adapt-In: system-wide quality attributes)*

- **NFR-Perf-1** Step-launch overhead (harness receipt of `mode: agent` step input to first executor process spawn): target p50 ≤ 2s, p95 ≤ 5s. Measured at the harness boundary using harness-side timestamps; does not depend on any executor-exposed latency property. *(Replaces an earlier draft that named "≤ 10× executor first-token latency"; that comparator was unmeasurable and is rescinded — see `addendum.md §A9`.)*
- **NFR-Perf-2** Error store query latency (filtered list): target ≤ 1s for up to 10,000 records.
- **NFR-Reliab-1** Artifact durability: locked artifacts survive harness restart; verification hash check on read.
- **NFR-Reliab-2** Run durability: a run interrupted mid-step can be resumed without re-doing completed locked steps.
- **NFR-Reliab-3** **Regression-set health floor.** A `bench <step>` query (FR-21) refuses to produce a recommendation when the regression set has fewer than **K comparable runs** for that `step × project-size-tier` cell, returning `regression_set_insufficient` instead. v1 default K=3 (consistent with SM-4); configurable per cell. `regression_set_remove` (FR-20) requires a written justification recorded as an audit event with `removed_run_id`, `removed_at`, `removed_by`, `reason` — this prevents the audit-from-hashes story (UJ-3) from silently evaporating.
- **NFR-Obs-1** Every step invocation produces a structured run event with `(project_id, run_id, step, executor_tuple, started_at, ended_at, outcome)`.
- **NFR-Obs-2** Error records and Acknowledgement records are queryable by `project_id`, `run_id`, `step`, and `category` / `acknowledger`.
- **NFR-Sec-1** Artifact hashes are signed by the harness on lock; unsigned artifacts cannot enter the Gate.
- **NFR-Sec-2** Acknowledgement records carry the acknowledger identity (human id or check name); unsigned acknowledgements are rejected.
- **NFR-Cost-1** v1 assumes single-org / single-team usage; no per-tenant cost accounting. Cost telemetry is logged at the run level (`executor_tuple`, `step`, `duration`, `tokens_in/out`) and is surfaced on the operator dashboard as a per-run total (FR-24).
- **NFR-Cost-2** **Per-tier cost ceilings.** Each project-size-tier carries a default cost ceiling per run (logged tokens in + out, no $ pricing): `trivial` ≤ 5e5 tokens, `session` ≤ 5e6, `epic` ≤ 5e7, `project` ≤ 2e8. When a run exceeds its ceiling, the harness **pauses** the next step invocation and requires an operator acknowledgement (`cost_overrun_ack`) before resuming. A Skill-bump regression pass (FR-22) has its own ceiling = 3× the affected step's normal ceiling. Ceilings are configurable per project YAML. Rationale: FR-15 (retry ladder), FR-22 (regression gate), and FR-7 (mid-project swap) compound LLM spend; without a ceiling + pause, the harness can silently consume the entire project budget on a single bad retry chain.
- **NFR-Privacy-1** Executor telemetry (Herdr events, FR-29) does not include prompt bodies; only invocation metadata (`executor_id`, `step`, `timestamps`, `outcome`). Prompt contents stay inside the Agent's own store.
- **NFR-Safety-1** A step with `mode: agent` cannot proceed past a Gate without an Acknowledgement; no silent auto-advance.

---

## 11. Constraints and Guardrails *(Adapt-In: safety / privacy / cost)*

The numbered NFRs above (NFR-Cost-1, NFR-Privacy-1, NFR-Safety-1) carry the v1 stance. Free-form guardrails not elevated to NFRs are reserved for v2 — e.g., per-tenant billing on the consolidated error tier (NFR-Cost-1's "v1 single-org" assumption will be revisited if v2 adds tenants).

---

## 12. Why Now *(Adapt-In: timing is load-bearing)*

The agent / LLM landscape is churning: every quarter a new agent ships and a new flagship LLM lands. Teams that have already standardized on a stack pay an audit cost when leadership asks "should we switch?" — DevFlow turns that question into a data point, not a debate. The BMAD Method skill catalog already supplies per-step "how", so DevFlow can stand up the harness layer without inventing method. The combination — fixed workflow + swappable execution + BMAD method skills + Herdr observation — exists in pieces elsewhere but not as an integrated harness today.
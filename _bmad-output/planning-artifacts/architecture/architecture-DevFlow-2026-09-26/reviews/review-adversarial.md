# Adversarial Architecture Review — DevFlow Spine

**Reviewer:** Reviewer 2 (Adversarial pressure-test)
**Subject:** `_bmad-output/planning-artifacts/architecture/architecture-DevFlow-2026-09-26/ARCHITECTURE-SPINE.md`
**PRD (binding):** `_bmad-output/planning-artifacts/prds/prd-DevFlow-2026-09-26/prd.md`
**Date:** 2026-09-26

---

## Verdict

**CONDITIONAL — 9 holes, 6 of them structural enough to ship-blocking.**

The spine is internally consistent in intent and reaches a defensible state for most ADs read in isolation. Read as a *system* — i.e. as the contract that two independently built units must both obey while still composing — it leaks in at least nine places. Each section below is one concrete scenario where a builder who follows every AD literally still produces something that does not fit with a builder next door. Every hole is paired with the minimum new or tightened AD that closes it.

Two ADs are also flagged for being *unenforceable as code* — the spine is otherwise a tight set of rules, but these two exist only as prose.

---

## Methodology

For each spine AD I asked: "If I am a competent engineer building unit X, and a different competent engineer is building unit Y at the same time, and we each obey every AD to the letter — is it possible for us to ship a system where X and Y disagree about state, identity, ownership, or ordering?" Every "yes" below is one hole.

I deliberately do **not** add tests that exercise the ADs in isolation (the spine already names error codes for that). I construct *interaction* scenarios — where two writers, two stores, or two paths converge on the same noun from different angles.

---

## Hole 1 — Two agents, same `executor_tuple_hash`, different `executor_tuple` (AD-3 / AD-10 / AD-14 bypass)

### Divergence scenario
Unit A builds the Workflow Controller. Unit B builds the Operator Dashboard. Both follow AD-3 (sha256 over canonical bytes for artifacts) and AD-10 (harness-signed invocation token; executor tuple hash recorded on every run event).

- Unit A computes `executor_tuple_hash = sha256(canonical_json(executor_tuple))` where `canonical_json` is its own in-process normalizer (sorted keys, no whitespace).
- Unit B computes the same hash for display. Its `canonical_json` differs: it sorts keys differently, includes a `null` field that A drops, or lowercases the model name (`gpt-5` vs `GPT-5`).

**Both obey AD-3 (sha256 is specified) and AD-10 (the token carries the hash).** The token issued by A validates fine inside A. When the dashboard re-derives the hash from the stored `executor_tuple` field to label a run, it computes a *different* hash than the run event claims. Audit trail (UJ-3, AD-14) silently disagrees with the dashboard view.

The same divergence kills AD-3's "two units computing different hashes for the same content" prevention *in spirit*: the audit story is consistent only within one unit, not across them.

### Required fix — **new AD-17: Canonical Serialization Is a Single Library Function**
- **Binds:** AD-3, AD-10, AD-14, FR-19
- **Rule:** All sha256 hashing in the harness (artifacts, executor tuples, run events, Acknowledgement records, error records, Herdr events) MUST go through a single `harness.canonical.canonical_bytes(value: Any) -> bytes` function. No unit may compute sha256 directly. The function is exported from `harness/canonical.py` and is the *only* path the dependency-direction rule permits across the harness. The CI lint enforces `from harness.canonical import canonical_bytes` as the sole importer.
- **Prevents:** every "two units compute different sha256" outcome at the source.

---

## Hole 2 — Two operators both edit project YAML mid-run (AD-7 lock lost; AD-2 + AD-13 read model writes)

### Divergence scenario
PRD FR-7 says project YAML edits are "between runs (not during a running step)". AD-15 enforces step order. AD-13 declares the dashboard is a read model. AD-7 forbids silent regression-set evaporation. **None of the ADs forbids concurrent YAML edits by two operators**, and none of the ADs names a lock primitive.

- Operator A opens `P7-sap-mig`'s YAML in a web editor at 10:00, changes Coding executor from `codex` to `omp`.
- Operator B does the same at 10:00:30 in a CLI `vim`, changes the Skill pin from `bmad-build@0.4.2` to `bmad-build@0.4.3`.
- Both edits read the YAML, mutate one field, write back. Last-writer-wins. The Coding step resumes with `codex + bmad-build@0.4.3` (A's skill pin + B's agent). Neither AD-7 nor AD-2 forbids this. AD-13 says the dashboard is a read model — but the dashboard also lets the operator "edit project YAML" via a "swap executor" button (FR-7 consequence). The button is a write path that the AD-13 exception list does NOT enumerate (only Acknowledgement is enumerated).

**Both operators obey every AD.** Audit shows one Coding tuple was used; the actual tuple was a Frankenstein neither operator chose.

### Required fix — **new AD-18: Project YAML Is a Locked Single-Writer Resource**
- **Binds:** FR-4, FR-7, AD-7, AD-13
- **Rule:** (a) every project YAML edit takes a `project_edit_lock` advisory lock keyed on `project_id`, implemented as a row in `var/devflow.sqlite` (`acquired_at`, `acquired_by`, `expires_at`); (b) only the lock holder may write the YAML; (c) the dashboard's "swap executor" action takes the same lock — the dashboard is **explicitly permitted one additional write path beyond Acknowledgement**, namely the project YAML edit (the AD-13 read-model rule is amended to permit it under the lock); (d) the YAML file on disk is content-addressed (sha256 of canonical bytes per Hole 1's AD-17) and every write records `{prev_yaml_hash, new_yaml_hash, edited_by, edited_at, intent}` in the Run Event Log.
- **Prevents:** silent Frankenstein tuples, lost edits, dashboard-back-door writes.

---

## Hole 3 — Herdr "observation-only" hides a real dependency (AD-9 violation by construction)

### Divergence scenario
AD-9 says Herdr outage MUST NOT block a run (NFR-Reliab-2). The structural seed shows Herdr as an out-of-process sidecar in prod. AD-10's invocation token is signed by the harness key. The Herdr Event Port is described as "telemetry only".

- Unit A builds the Cost Guard. It is told to "track per-run tokens" and notices that Herdr emits per-step token counts (via FR-29's `outcome` field, which is closed string only — but the Herdr *implementation* in `herdr/` ships its own enriched event with `tokens_in`, `tokens_out`, which the harness ingests into the Run Event Log per AD-14).
- Unit A's Cost Guard reads cost from the Run Event Log. The harness-direct path also writes cost into the Run Event Log. Both paths are "live". Herdr being down means one source is silent.
- The Cost Guard continues to work (NFR-Cost-1). But the *Herdr source's existence* is now load-bearing for a downstream metric Lin (UJ-3) relies on — the per-step token breakdown.

A Herdr outage then breaks the dashboard's "step-by-step cost breakdown" surface (FR-24). This is a hidden dependency on Herdr — exactly what AD-9 forbids. **Both builders obey AD-9 to the letter; the system still has a Herdr outage that breaks a real operator-visible surface.**

### Required fix — **new AD-19: Harness-Direct Path Is the Sole Authoritative Source for Run State**
- **Binds:** AD-9, AD-14, NFR-Cost-1, NFR-Reliab-2, FR-19
- **Rule:** (a) the Run Event Log is written **only** by harness-internal code paths triggered by Step Executor Port results; Herdr events are projected into a separate, read-only `var/herdr_mirror.sqlite` (the "Herdr mirror") with NO join keys, NO derived fields, and NO contribution to canonical state; (b) the dashboard's cost surface reads cost from `cost_tokens_in` / `cost_tokens_out` fields on the run event (harness source) — Herdr's tokens are *not* joined, ever; (c) a Herdr outage MUST NOT change any operator-visible number in the dashboard; the test is a smoke check that runs a full step with `herdr_enabled=false` and diffs the dashboard's per-run totals.
- **Prevents:** the "harness-direct path has a hidden dependency on Herdr" PRD adversarial pattern that AD-9 alone cannot close, because AD-9 only forbids Herdr *driving* state — not the harness *silently depending on* Herdr filling fields.

---

## Hole 4 — Cost Guard drifts from Run Event Log (AD-8 vs AD-14)

### Divergence scenario
AD-8 says per-tier ceilings apply; on overrun the harness pauses. AD-14 says every step invocation writes cost tokens to the Run Event Log.

- Unit A (Cost Guard) reads cost tokens from the Run Event Log. It uses the harness key (per Consistency Conventions) to verify the row signature.
- Unit B (Skill Bump Registry regression pass, AD-6) needs its OWN budget — AD-8 says it gets 3× the step's normal ceiling. Unit B does *not* write to the Run Event Log during the regression pass (a regression pass is not a project run; it's a benchmark pass; AD-14's "every step invocation" applies to project runs).
- Now the Cost Guard's per-run total disagrees with the Skill Bump Registry's per-regression-pass total. Two builders, two counters, no shared ledger. The operator sees "you've spent 8.2M tokens on this run" while the bump registry says "the regression pass cost 12M tokens", and there is no rule that the two be reconciled.

Both obey AD-8 (ceiling exists, pause on overrun) and AD-14 (run event written). The Cost Guard's "spent X tokens on this run" answer is **incomplete** because it ignores the regression pass that *caused* the spike. Audit cannot answer "why is my LLM bill double the run total".

### Required fix — **new AD-20: Cost Telemetry Has One Ledger, Two Projections**
- **Binds:** AD-8, AD-14, FR-22, NFR-Cost-1
- **Rule:** (a) every cost-bearing operation (project step, retry-ladder rung, Skill-bump regression pass, manual regression-set replay) writes to a single `cost_ledger` table keyed by `{op_id, project_id?, bump_id?, run_id?, step?, tokens_in, tokens_out, recorded_at, signed_hash}`; (b) the Run Event Log row carries a foreign key `cost_ledger_id` so audit can join; (c) the Cost Guard's "per project" total is a SUM over `cost_ledger WHERE project_id = ?`, NOT a SUM over Run Event Log; (d) the Skill-bump regression pass's ceiling check reads and writes the same `cost_ledger` (the 3× ceiling is computed against the same ledger); (e) cross-ledger joins in the dashboard MUST go through `cost_ledger`, never by re-aggregating from run events.
- **Prevents:** two budgets, two operators, two truths. The bug is real because AD-8 and AD-14 do not name a shared cost store; AD-20 names it.

---

## Hole 5 — Operator Dashboard gains a write path through "re-trigger" / "re-run step" (AD-13 violation)

### Divergence scenario
AD-13 says the dashboard is a read model. The single enumerated write path is Acknowledgement. The structural seed shows `OD -->|signed Acknowledgement| GE`. PRD FR-7 (mid-project executor swap) is explicitly an operator action — and operators perform swaps via the dashboard.

- Unit A builds the dashboard's project page. It shows the locked Coding artifact, the failed step, and a "Resume from Coding" button (UJ-2). Pressing that button writes a new run event AND changes the run's current step — *two* canonical store writes, neither enumerated by AD-13's exception list.
- Unit B builds the dashboard's regression diff page (FR-26). It shows a "Rerun this regression" button that triggers a Skill-bump regression pass (FR-22). This writes to the Regression Set and the Cost Ledger. Also unenumerated.

Both obey AD-13 as written (the rule says "no write paths *except Acknowledgement*" — but it has no CI hook to *enforce* the except list). The dashboard quietly becomes a second writer for at least three canonical stores (Run Event Log, Project State, Regression Set). Every store develops a write race against the dashboard.

### Required fix — **tightened AD-13 + new AD-21: Dashboard Write Paths Are a Closed Enum**
- **Tightened AD-13:** change "No write paths exist in the dashboard except Acknowledgement (signed via the harness key — AD-5)" to "No write paths exist in the dashboard except those enumerated in AD-21 (each signed via the harness key)."
- **New AD-21 — Dashboard Write Surface Is a Closed Enum:**
  - **Binds:** AD-5, AD-13, FR-7, FR-10, FR-22, FR-23
  - **Rule:** the dashboard's permissible write paths are exactly: (1) `submit_acknowledgement` (AD-5); (2) `swap_executor_take_lock` (AD-18); (3) `trigger_skill_bump_regression` (FR-22); (4) `promote_skill_bump` (FR-23); (5) `cost_overrun_ack` (AD-8); (6) `regression_set_remove` (AD-7). Every other dashboard action is a read. The dashboard backend's FastAPI router enforces this via an allowlist at import time — a CI hook greps for `@router.post` / `@router.put` in `dashboard/src/` and fails if any path is not in the AD-21 enum.
- **Prevents:** the dashboard becoming a second writer outside the named surface. The CI hook makes the rule enforceable, not just documented.

---

## Hole 6 — Retry-ladder rung 4 silently consumes an in-progress (not-yet-promoted) Skill (AD-6 boundary condition)

### Divergence scenario
AD-6 says rung 4 may ONLY use a Skill from the operator-promoted set; otherwise return `skill_not_promoted`. The operator-promoted set is the Skill Bump Registry minus entries in `pending_promotion`.

- Unit A (Retry Manager) consults the registry: a bump is in `pending_promotion`. It correctly returns `skill_not_promoted` and pauses.
- Operator decides to fast-track: they edit the registry directly via a CLI flag `--force-promote` (the brief mentions operators, the spine does not forbid direct registry edits outside the "manual promotion" path). The bump is now in the promoted set but the regression run that gated it has not actually completed (FR-22 says "must pass the regression set"; the operator just changed the flag).
- Unit B (Retry Manager, second instance / second workflow run) sees the bump in the promoted set. It allows rung 4 to consume the Skill. The Skill has not actually been regression-validated. The locked artifact chain breaks.

Both obey AD-6 to the letter. The Skill Bump Registry's `pending_promotion` → `promoted` transition is the missing rule. AD-6 forbids the retry-ladder from consuming a non-promoted Skill; it does not forbid the *promotion path* itself from skipping the regression gate.

### Required fix — **tightened AD-6 + new AD-22: Promotion Is Gated, Not Editable**
- **Tightened AD-6 (Rule, point 3):** add "(d) The `pending_promotion → promoted` transition is gated by a completed regression run with `result: pass` recorded in the Skill Bump Registry; manual promotion requires the operator to present the `regression_run_id`; the transition is rejected with `skill_regression_missing` if no passing regression run is found."
- **New AD-22 — Skill Bump Registry Has Exactly Two Writers:**
  - **Binds:** AD-6, FR-22, FR-23
  - **Rule:** (a) the Skill Bump Registry accepts writes from exactly two paths: (1) the `skill_bump_register` CLI (creates a `pending_promotion` row); (2) the `skill_bump_promote` CLI (transitions a row from `pending_promotion` to `promoted`, requires a passing `regression_run_id`); (b) any other write attempt (direct DB, direct FS, harness-internal ad-hoc promotion) returns `skill_bump_registry_immutable`; (c) the registry table is append-only at the row level (no UPDATE except the status transition in path 2, recorded with `prev_status`, `next_status`, `regression_run_id`, `promoted_by`, `promoted_at`).
- **Prevents:** AD-6's "promoted set" being hand-edited into a state that allows rung 4 to consume a non-validated Skill.

---

## Hole 7 — Acknowledgement record forged by replaying a signed JSON payload (AD-5 + AD-13 + AD-14 join)

### Divergence scenario
AD-5 says every Acknowledgement is a signed JSON record persisted under `acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json`. AD-13 says the dashboard's write path for Acknowledgement is signed via the harness key.

- Unit A (Operator Console) writes Acknowledgement `ACK-001` for project P1, run R1, step `design`, verdict `accepted`. The signed JSON is on disk.
- Unit B (an operator, using the dashboard's REST API or the `acknowledgements/` directory directly) copies `ACK-001.json` to `acknowledgements/P2/R1/design/ACK-001.json` — same signed_hash, different `{project_id, run_id, step}`. The harness signature validates (it covers the content, which is identical). The harness *also* accepts it because it has no rule that `{project_id, run_id, step}` inside the payload must match the path.

Both obey AD-5 and AD-13. The Acknowledgement for P2's Design step is a copy of P1's. Audit shows two Acknowledgements with identical `signed_hash` — a forgery that passes signature validation.

### Required fix — **new AD-23: Acknowledgement Signature Covers the Path**
- **Binds:** AD-5, AD-13, NFR-Sec-2
- **Rule:** the signed_hash in an Acknowledgement record MUST cover not only the JSON body but also the storage path — specifically the triple `(project_id, run_id, step)` as it appears in the path `acknowledgements/<project_id>/<run_id>/<step>/<acknowledgement_id>.json`. Any record whose body claims `project_id=P2` but lives under `acknowledgements/P1/...` is rejected with `acknowledgement_path_mismatch`. Equivalently, the harness key signs over the canonical serialization of `{path_triple, body}` (AD-17's canonical_bytes function). The Acknowledgement writer MUST verify the path triple before signing.
- **Prevents:** cross-project Acknowledgement forgery by file copy, the kind of forgery that AD-5's content-only signature does not catch.

---

## Hole 8 — `Done` mis-recorded as `Locked` because the dashboard's status view picks the wrong field (AD-11 vs AD-14)

### Divergence scenario
AD-11 says `Done` is the terminal state for trivial/session-tier skipped-Gate steps; the step-end run event carries `gate_mode: skipped` + implicit `verdict: accepted` + `confirm_id`. Dashboard distinguishes `Completed (Done)` from `Locked (Acknowledged)`. AD-14 writes every state transition to the Run Event Log.

- Unit A (dashboard's run status view, FR-24) shows a step's status. It picks `latest_event.outcome` and renders it as "locked" if `outcome == "completed"`. It does NOT check `gate_mode`.
- Unit B (dashboard's regression view, FR-26) shows the same step. It picks `latest_acknowledgement.verdict` if present, else falls back to "done" from the run event's `gate_mode`. This is correct.

Result: two pages on the same dashboard show two different states for the same step. **Both obey AD-11, AD-13, and AD-14** — none of which name a single function for resolving a step's terminal status. The "Completed (Done) vs Locked (Acknowledged)" rule lives in prose only.

### Required fix — **new AD-24: Step Terminal Status Has One Resolver**
- **Binds:** AD-11, AD-14, FR-24, FR-12
- **Rule:** (a) `harness/gate_engine/step_status(run_id, step) -> StepStatus` is the single function that returns `{terminal: Done|Locked|Pending|Failed, gate_mode: enforced|skipped, confirm_id?, acknowledgement_id?}`; (b) every dashboard view MUST call this function — no view may compute terminal status inline; (c) the function's logic is: `if latest_run_event.gate_mode == "skipped": return Done; elif latest_acknowledgement.verdict in {accepted, accepted-with-open-items}: return Locked; elif latest_run_event.outcome == "failed": return Failed; else: return Pending`; (d) CI hook fails any dashboard view that imports a different terminal-status resolver.
- **Prevents:** two dashboard views disagreeing on Done vs Locked for the same step. AD-11's prose rule is now enforced by code, not eyeballed.

---

## Hole 9 — `accepted-with-open-items` reachable in the schema but unreachable in the operator console (AD-12 enforcement)

### Divergence scenario
AD-12 makes `accepted-with-open-items` a closed enum value. The dashboard's Acknowledgement form has three buttons: Accept, Reject, and a comment box. There is no "Accept with open items" affordance.

- Operator wants to approve Coding with three follow-up TODOs. They click Accept (no comment box mechanism for "with open items"). The Acknowledgement is `verdict: accepted`. The open TODOs are lost — they live in a Slack thread.
- An operator who reads the spec strictly and tries to construct `verdict: accepted-with-open-items` must hand-edit the Acknowledgement JSON, which AD-5 forbids (`acknowledgement_unsigned` for unsigned, but a signed-by-hand record is still accepted if they sign it). AD-5 + AD-12 + AD-13 together do not require the *operator console* to expose the third verdict.

Both ADs are obeyed. The PRD adversarial pattern (AD-12 was added to close) is recreated: operators fall back to "accept and bury".

### Required fix — **new AD-25: Acknowledgement UI Exposes the Closed Verdict Enum**
- **Binds:** AD-5, AD-12, AD-13, FR-10
- **Rule:** the operator console's Acknowledgement form MUST present the closed enum `accepted | accepted-with-open-items | rejected` as a tri-state radio (or equivalent); selecting `accepted-with-open-items` reveals an `open_items[]` editor with `description` + `owner` + `severity` fields; the form is rejected client-side and server-side if `accepted-with-open-items` is selected with zero `open_items[]`. A CI lint fails the build if the Acknowledgement form template's allowed verdicts are not the AD-12 enum.
- **Prevents:** AD-12 being correct on paper but unreachable in practice.

---

## AD-9 dependency-direction rule is unenforceable as code (the spine's own "IS a rule" claim)

The dependency-direction mermaid is presented in the spine as **"this IS a rule — author it as valid mermaid"**. A mermaid diagram is *documentation*. Nothing in the spine (AD-1 through AD-16, the consistency conventions, the stack, the structural seed) names a CI hook, a linter, or a build check that fails when:

- A file under `skills/<skill>@<version>/` (Method layer) imports from `harness/` (Harness layer).
- A file under `agents/<adapter>/` (Execution layer) imports from `harness/` internals (not the port).
- A file under `herdr/` imports from `harness/`.

Two builders, each obeying the AD-12 *prose*, can still write `from harness.workflow_controller import route_step` inside `skills/bmad-build@0.4.2/...` — and the spine does not catch it.

### Required fix — **new AD-26: Dependency-Direction Rule Is a CI Import Boundary**
- **Binds:** all ADs (the dependency-direction is the spine of the spine)
- **Rule:** the repo contains a `tools/check_layer_boundaries.py` script (run in CI on every PR) that:
  1. Parses every `*.py` file under `skills/`, `agents/`, and `herdr/`.
  2. Rejects any import whose module path begins with `harness.` *except* a published allowlist of port types defined in `harness/ports/__init__.py` (`StepExecutorPort`, `HerdrEventPort`, `ExecutorTuple`, `SkillManifest`, `ArtifactContract`).
  3. Rejects any `harness/` import inside `herdr/` (no path is allowed; Herdr has no port into Harness).
  4. Rejects any cross-skill import inside `skills/<skill>@<version>/` (skills MUST NOT depend on each other directly — they share only published contracts).
- The script exits non-zero on any violation. CI fails the build.
- **Prevents:** the spine's own claim ("IS a rule") from being true only on paper.

---

## Cross-cutting: the spine has no AD for "shared-data shape" — the artifact contract

The PRD Glossary says *"Artifact contract — The schema a step output must satisfy to enter the Gate."* AD-3 says the artifact is content-addressed and signed. AD-7 says the regression set's `metric definition is recorded with every benchmark run`. None of these ADs name a *single function* for resolving "is this artifact body the same shape as the contract?".

- Unit A (Coding step) writes a `coding` artifact whose body matches schema version `coding-contract@3`.
- Unit B (Testing step) validates the body against schema version `coding-contract@2` (the version pinned in Testing's skill manifest).

**Both obey AD-3, AD-6, AD-7, AD-15.** Coding's locked artifact is "valid" by its own contract and "invalid" by Testing's. The run silently hangs at Testing, or Testing produces a non-comparable artifact that pollutes the regression set.

### Required fix — **new AD-27: Artifact Contracts Are Pinned Per-Pipeline**
- **Binds:** AD-3, AD-6, FR-3, FR-17
- **Rule:** (a) every pipeline definition (`pipelines/<name>@<version>.yaml`) carries an explicit `artifact_contracts: {step: name@version}` map; (b) the harness pins the contract version at pipeline load (AD-1, AD-16); (c) writing an artifact whose body does not match the pinned contract for that pipeline version returns `artifact_contract_mismatch`; (d) a bump of an artifact contract is a *pipeline* bump, not a skill bump — `software-v1@2` may change `coding-contract@3 → coding-contract@4`, but `software-v1@1` MUST NOT.
- **Prevents:** "two units obeying all ADs, producing incompatible artifacts because the contract version is implicit". This is the classic PRD adversarial pattern #2 the spine does not close.

---

## Cross-cutting: the `Herdr Event Port` schema has no `tokens_in` / `tokens_out` field — but the run-event schema does (cost drift, again)

The Run Event Log schema (AD-14) lists `cost_tokens_in` / `cost_tokens_out`. The Herdr Event Port schema (AD-9) does not list cost — and explicitly says Herdr events "do NOT drive state transitions". So far, so consistent.

But the deployment mermaid shows Herdr as "out-of-process observer" in prod. The Herdr Event Port schema is `{executor_id, step, project_id, started_at, ended_at, outcome}` (FR-29). The harness-direct path emits cost in the run event. **Herdr cannot emit cost; only the harness-direct path can.**

If an operator wants to audit "what did each Agent adapter consume on each step", they go to the Run Event Log (harness source). That is correct. But the dashboard's `per-run cost` view per FR-24's table conflates: "harness-recorded tokens" (always present) with "tokens reported by Herdr" (which Herdr never emits, because its schema has no cost field).

This is OK as long as nobody reads Herdr events for cost. **It becomes a hole the moment a dashboard author reads the Herdr mirror for cost.** There is no AD forbidding that.

### Required fix — **tightened AD-9** to explicitly state the Herdr Event Port schema is *closed* (no future field additions that the harness interprets for state), AND **new AD-19 (above)** makes Herdr mirror cost-less in any case. The combination closes both vectors.

---

## Summary table — holes and fixes

| # | Hole | Triggered AD | Severity | Fix |
| --- | --- | --- | --- | --- |
| 1 | Two `executor_tuple_hash` values for one tuple | AD-3, AD-10, AD-14 | High | **AD-17** canonical_bytes single function |
| 2 | Two operators edit YAML concurrently | FR-7, AD-7, AD-13 | High | **AD-18** project_edit_lock + dashboard write allowlist |
| 3 | Herdr outage breaks a dashboard surface | AD-9 (hidden dependency) | High | **AD-19** Herdr mirror is read-only and not joined |
| 4 | Cost Guard drifts from Run Event Log | AD-8, AD-14 | High | **AD-20** single cost_ledger, two projections |
| 5 | Dashboard gains write paths silently | AD-13 | Medium | **Tighten AD-13** + **AD-21** closed write enum + CI hook |
| 6 | Rung 4 consumes a `force-promoted` Skill | AD-6 | High | **Tighten AD-6** + **AD-22** Skill Bump Registry two writers |
| 7 | Acknowledgement JSON replayed cross-project | AD-5, AD-13 | High | **AD-23** signature covers path triple |
| 8 | Two dashboard pages disagree on Done/Locked | AD-11, AD-14 | Medium | **AD-24** single step_status resolver + CI hook |
| 9 | `accepted-with-open-items` unreachable in UI | AD-12 | Medium | **AD-25** Acknowledgement UI exposes enum |
| — | Dependency-direction rule unenforceable as code | AD-1..16, AD-Dependency-Direction | **High (meta)** | **AD-26** CI import-boundary checker |
| — | Implicit artifact-contract version drift | AD-3, AD-6, FR-3 | High | **AD-27** artifact contracts pinned per-pipeline |
| — | Herdr event schema silently extended for cost | AD-9 | Low (combination with #3) | Tighten AD-9 (closed Herdr event schema) |

---

## Items the spine gets right (under adversarial pressure)

For balance, the following ADs were tested and survived every divergence scenario I could construct at this altitude:

- **AD-1** Pipeline immutability holds even when operators have shell access — the read-only FS rule (AD-16) and the load-once-boot rule together block every variant I tried.
- **AD-4** Append-only error store is airtight given AD-22's two-writer rule on the bump registry (the two share an invariant).
- **AD-7** Regression-set health floor and `regression_set_remove` audit event together prevent silent evaporation.
- **AD-15** Six-step sequence is wired in code; no configuration surface to skip a step.
- **AD-16** Pipeline definitions are read-only on disk; the bump boundary is correct.

These are not promises — the spec and tests are where each will be proven. But the spine-level invariants are sound for them.

---

## Closing note for the Reviewer Gate

The spine is in good shape *if* the nine new/tightened ADs above are absorbed before bmad-spec begins. The two highest-leverage fixes are AD-17 (canonical-bytes library) and AD-26 (CI import-boundary check) — every other hole in this review gets harder to fix without them in place first. AD-26 is the one that turns the spine from "rules we follow" into "rules we *cannot* violate". Recommend the Reviewer Gate require these three as a precondition for bmad-spec handoff: AD-17, AD-26, AD-21.

— Reviewer 2 (Adversarial pressure-test), 2026-09-26
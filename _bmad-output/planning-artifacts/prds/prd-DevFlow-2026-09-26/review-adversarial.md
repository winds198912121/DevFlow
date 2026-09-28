# Adversarial PRD Review — DevFlow Harness

**Reviewer voice:** hostile engineering director. I am not here to validate; I am here to find the load-bearing assumptions this PRD asks me to accept on faith, then press until one of them breaks.

**Files reviewed:** `prd.md` (550 lines, status=draft), `addendum.md` (103 lines), plus brief + brief addendum for traceability.

---

## Overall verdict

**Do not greenlight a build from this PRD as written.** Three of its core promises — "cost is a constraint", "the benchmark drives recommendations", "Herdr is optional observation" — are stated as facts but collapse on contact with the mechanism the PRD itself defines. Two more (the only NFR with a numeric latency target, and the UJ structure) are theater in the technical sense: they read as rigor without functioning as rigor. The PRD is internally coherent only because it avoids quantifying what would expose the contradiction. Below are the five most damaging findings, ranked by impact on PRD usefulness for downstream architecture, SPEC, and ticketing.

---

## Findings

### 1. [CRITICAL] The PRD has a cost story that is not a story — it is "telemetry" with no budget, against a design that multiplies LLM spend by design

**Where:** §11 Constraints ("Cost guardrail: v1 assumes single-org / single-team usage; no per-tenant cost accounting. Cost telemetry is logged at the run level ... but not surfaced as a billing metric"); cross-cut against FR-15 (retry ladder), FR-22 (Skill bump regression gate), FR-20/21 (benchmark queries), SM-4 ("at least one recommendation per step within 3 projects of usage").

**Quote:** *"Cost telemetry is logged at the run level (`executor_tuple`, `step`, `duration`, `tokens_in/out`) but not surfaced as a billing metric."*

**Why this is broken:** The PRD defines a workload shape that compounds LLM spend:
- FR-15 retry ladder: up to **four** executor invocations per failing step before human intervention (same Agent/LLM/Skill → different LLM → different Agent + better LLM → different Agent + different LLM + improved Skill).
- FR-22: every BMAD Skill bump re-executes the regression set before promotion. There is no ceiling on regression-set size.
- SM-4: benchmark-driven recommendations must exist "within 3 projects" — to produce them, FR-20 needs comparable runs, which means the harness must keep re-running past projects (or carry them forward at full token cost in the regression store).
- FR-7: mid-project executor swap explicitly preserves prior artifacts so they can be replayed against new executors — i.e., swap is itself a re-execution path.
- NFR-Perf-1: "≤ 10× the underlying executor's first-token latency" is an NFR that pushes **toward** more aggressive invocation (more attempts to hit the latency target), not less.

A single `epic`-tier project that hits rung-4 failures on two steps and triggers one Skill bump already costs ~10× a linear run. The PRD's only answer to this is "telemetry is logged." A skeptical director's question — "what's the expected $/project ceiling, and what's the kill-switch when a run burns past it?" — has no answer in this document.

**Fix:** Add a Cost NFR with a numeric ceiling per project tier (e.g., `epic`: ≤ $X per project, ≤ $Y per Skill-bump regression pass). Define what the harness does when a run exceeds it (pause and require human acknowledgement; do not silently consume). Replace "telemetry is logged" with a named operator-visible cost view in §4.7 (currently FR-24–27 say nothing about cost).

---

### 2. [CRITICAL] The benchmark thesis is internally unstable — the asset that justifies the platform is constantly invalidated by the churn the platform exists to address

**Where:** §12 Why Now ("every quarter a new agent ships and a new flagship LLM lands"); SM-7 ("≥ 90% (some LLM non-determinism is expected; the platform reports `non_deterministic_executor` for the rest)"); FR-18 (non-comparable runs are flagged, not mixed); FR-20 (regression set is curated and removable).

**Quote:** *"some LLM non-determinism is expected; the platform reports `non_deterministic_executor` for the rest."*

**Why this is broken:** DevFlow's value proposition, stated plainly in §1, is "after N projects, I can recommend a stack from data instead of vibes." That recommendation depends on the regression set (FR-20) being large enough and stable enough to be meaningful. But:
- SM-7 admits up to **10% of locked artifacts are not reproducible across re-renders**. Those 10% are exactly the runs that would otherwise be benchmark inputs.
- FR-18 marks non-comparable runs rather than mixing them — so each new agent/LLM churn event shrinks the regression set.
- §12 explicitly says the underlying stack churns every quarter. So in the 3-project window SM-4 demands a recommendation from, the regression set has likely rotated at least once.
- FR-20 lets an operator remove runs from the regression set (`regression_set_remove`).

The result: the recommendation at SM-4 is built from a constantly-evaporating asset, with no metric for how stale the regression set is or what fraction of historical runs are still comparable. The PRD never names this paradox. Worse, FR-22's regression gate (Skill bump must pass the regression set) becomes self-defeating once the regression set is too small to be statistically meaningful — bumps start failing not because they are bad, but because the test bench is empty.

**Fix:** Add a "regression set health" NFR with a numeric floor (e.g., "regression set must contain ≥ K comparable runs per step per project size tier; queries below floor return `regression_set_insufficient` and refuse to recommend"). Make `regression_set_remove` require a written justification that is itself recorded in the error/audit store. State explicitly what happens when the regression set is too small to be the basis of a recommendation.

---

### 3. [HIGH] "Herdr is optional, observation-only, and the harness has its own invocation path" — but no FR specifies that invocation path. The PRD claims a decoupling it does not define.

**Where:** §4.8 (FR-28, FR-29); §5 Non-Goals ("Not a control plane for Herdr"); FR-8 ("The harness owns the invocation contract: the locked input artifact, the BMAD Skill versions, and the executor tuple").

**Quote:** *"A Herdr outage does not block a run (the harness has its own executor invocation path)."* — FR-28 consequence.
**Quote:** *"A step with `mode: agent` invokes the named Agent + LLM with the pinned Skills."* — FR-8 description.

**Why this is broken:** The PRD repeatedly insists Herdr is observation-only AND that the harness can run without Herdr. But the PRD never names the harness's own invocation path. The executors named are Pi, OMP, Codex, Claude Code, DSH — each of which has its own runtime, its own auth, its own lifecycle. None of them are specified to be invokable by the harness directly. The brief addendum §2 shows three layers, with Herdr as the *execution* layer; the PRD has stripped Herdr's role but kept the executors it was supposed to host. Either:
- The harness invokes Pi/OMP/Codex/Claude Code/DSH directly — in which case Herdr is not just optional, it is vestigial, and the PRD should say so; or
- Herdr is the actual execution layer and "observation-only" is wrong — in which case FR-28 contradicts §2 of the brief addendum.

This is not a stylistic ambiguity; it is a missing FR. An architecture spine cannot resolve this without picking a side, and the PRD punts the decision to "architecture step" without flagging that the two stances are mutually exclusive.

**Fix:** Either (a) add an FR-28a that names the harness's direct invocation path to each v1 executor (auth model, lifecycle, error contract), or (b) rescind "the harness has its own executor invocation path" from FR-28 and admit Herdr is the execution layer, with `observation-only` rescoped to a thinner subset. Pick a side. Do not ship a PRD whose execution model is "by Herdr, except when not by Herdr."

---

### 4. [HIGH] NFR-Perf-1 ("≤ 10× the underlying executor's first-token latency") is incoherent and unmeasurable. This is NFR theater.

**Where:** §10 Cross-Cutting NFRs.

**Quote:** *"NFR-Perf-1 Step invocation latency (start to first output): target ≤ 10× the underlying executor's first-token latency. Measured at the harness; not the executor itself."*

**Why this is broken:** "First-token latency" is a property of an LLM streaming response. For a coding agent (Codex, Claude Code, OMP), "first-token" is not the bottleneck and not even a meaningful boundary — the agent's work is multi-step (read, plan, edit, run, iterate), and what reaches the harness is the *final* artifact, not a stream. The comparator (the executor's own first-token latency) is itself noisy, model-dependent, and provider-dependent. Multiplying a noisy baseline by 10 does not produce a measurable threshold; it produces a number an engineer can argue with after every release.

This is NFR theater: it looks like a bound, it sounds like rigor, but it cannot fail and therefore cannot be used. A skeptical director will ask: "show me the dashboard that turns this NFR red." There is no such dashboard, and there cannot be, because the comparator is not a harness-internal quantity.

**Fix:** Replace NFR-Perf-1 with a measurable harness-internal latency bound that does not depend on a third-party baseline. Suggested: "p50 step-launch overhead (harness receipt of `mode: agent` to first executor process spawn) ≤ 2s, measured at the harness boundary." Or drop latency-as-NFR entirely and lean on NFR-Reliab-2 (run durability / resume) which is what the user actually cares about.

---

### 5. [HIGH] The three UJs are three time-slices of one persona. The PRD forces a UJ shape onto a capability spec and pretends it is user research.

**Where:** §2.3 UJ-1 (Mei), UJ-2 (Arjun), UJ-3 (Lin).

**Quote:** *"UJ-1. Mei runs a new SAP-BTP app project end-to-end on DevFlow. Persona + context: Mei, platform/DevEx engineer at a small consulting firm."*
**Quote:** *"UJ-2. Arjun swaps the Coding step's executor mid-project. ... Arjun, solo consultant mid-engagement."*
**Quote:** *"UJ-3. Lin audits a project's run history six months later. ... Lin, tech lead."*

**Why this is broken:** All three named protagonists are the platform owner in three career costumes. Mei = platform/DevEx engineer, Arjun = solo consultant (still the operator), Lin = tech lead (still the operator). The brief explicitly says DevFlow is "Not an end-user / chat product" (§5 Non-Goals) with "operator dashboards only" (§4.7). So there is exactly one user role: the platform operator. Naming three of them does not create three users; it creates three POVs of the same user.

The PRD claims these UJs feed architecture and ticketing ("Scope dial: Heavier"). But the downstream consumer does not get three distinct workflows; it gets one workflow described three times. UJ-2's actual new information is the mid-project executor swap (FR-7), and UJ-3's is the audit story (FR-19). Both are capability descriptions that would land better as FRs than as UJs. The UJ format here is shape-fit failure: the PRD's own product type (single-operator internal tool) does not need protagonist-named journeys; it needs capability boundaries.

A skeptical director would say: "if the only user is the platform owner, stop pretending otherwise. Show me the operator's actual workflow as a state diagram, not as three personas."

**Fix:** Either (a) collapse UJ-2 and UJ-3 into a single "operator workflow" capability description and stop calling them UJs, or (b) find a second real user role (e.g., the BMAD skill maintainer who consumes DevFlow's regression set to decide whether to promote a Skill version) and write that UJ honestly. The current triplet is persona theater.

---

## Smaller adversarial notes (not in the top 5 but worth flagging)

- **The trivial/six-step contradiction.** FR-12 says `trivial` has "default Done on a single confirm, no formal Gate." SM-1 says "100% of runs on `software-v1`" use six fixed steps. If `trivial` skips Gates, `trivial` projects do not produce six locked artifacts. Either SM-1 is wrong, or FR-12 is wrong, or `trivial` does something the PRD has not defined. This needs resolution before SPEC.

- **Mid-project executor swap has no threat model.** FR-7 lets an operator swap executors mid-project; NFR-Sec-1/2 cover artifact and acknowledgement signing; nothing covers executor authentication or trust. If the new executor is compromised or simply not the executor it claims to be, the locked inputs are leaked to it with no check. The addendum §A3 concedes "the brief does not name a security threat model in v1; the architecture step should produce one" — but executor swap is the most security-sensitive feature in the PRD and ships before the threat model exists.

- **FR-21's metric gaming problem.** FR-21: "the metric definition is recorded with each benchmark run; two metrics on the same set can produce different recommendations." This re-imports the exact gaming failure mode SM-C1 ("Raw per-step success rate — explicitly NOT a primary metric") was meant to prevent. If the operator picks the metric, the operator can pick the metric that justifies the stack they already use. The PRD names the disease and ships the vector.

- **The audit story depends on data that can be deleted.** FR-20 lets an operator `regression_set_remove` runs. UJ-3's audit answer ("content hashes, not vibes") requires comparable historical runs. If the regression set is curated away, Lin's audit reduces to "this project's hashes." The PRD never addresses this.

- **Rung 5 has no UX surface.** FR-15 pauses on rung-4 failure; "human intervention" is operator-initiated; FR-24–27 do not name a paused-step surface. The operator's path from "step paused" to "step resumed" is unspecified.

- **Mechanical:** `addendum.md §A7` claims "12 NFRs" but `prd.md §10` defines 8. This is a counting drift between sibling artifacts and will confuse downstream consumers who cross-reference the count.

---

## Closing

The PRD is well-structured and internally consistent on the level of grammar. It is not internally consistent on the level of mechanism. Three of its five most load-bearing claims (cost is bounded, benchmark is meaningful, execution is decoupled from observation) do not survive contact with the FRs that operationalize them. A skeptical engineering director should refuse to greenlight the build until findings 1, 2, and 3 are resolved; findings 4 and 5 are cosmetic but indicate the rigor level the rest of the PRD has not been held to.

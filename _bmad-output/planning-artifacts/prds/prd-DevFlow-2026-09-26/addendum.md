# PRD Addendum: DevFlow Harness

**Status:** draft (headless)
**Generated:** 2026-09-26
**Purpose:** Depth that belongs in downstream artifacts (architecture spine, SPEC, tickets) — too implementation-specific for the PRD itself. Mirrors the brief addendum and the design doc.

---

## A1. PRD vs. Brief — what changed in translation

The brief was 1–2 pages, narrative, with goals G1–G5. The PRD expands each goal into a feature group and numbered FRs. The mapping:

| Brief goal | PRD feature group | FRs |
|------------|-------------------|-----|
| G1 — Workflow fixed | §4.1 Pipeline Definition & Versioning | FR-1, FR-2, FR-3 |
| G2 — Each step manual or auto | §4.2 Project Config & Executor Selection | FR-4, FR-5 |
| G3 — Each step can swap Agent/LLM/Skills | §4.2 Project Config & Executor Selection | FR-6, FR-7 |
| G4 — Step linkage, human ack, controllable | §4.3 Step Execution & Gates | FR-8 … FR-12 |
| G5 — Error accumulation, review, change | §4.4 Error Store & Retry Ladder + §4.5 Artifact Versioning & Reproducibility + §4.6 Benchmark & Skill Promotion | FR-13 … FR-23 |

The brief's `[ASSUMPTION]` tags were approved by the user and are now written as facts in the PRD (see PRD §9 Assumptions Index A1, A2).

---

## A2. Deferred findings from the brief — state after PRD

From `brief-DevFlow-2026-09-26/addendum.md §8` (D1–D6):

| ID | Title | PRD stance | Resolved? | Owner |
|----|-------|------------|-----------|-------|
| D1 | v1 router location (repo vs. sidecar) | Not resolved in PRD (architecture concern). | No — defer to `bmad-architecture`. | architect |
| D2 | `test-report.json` v1 schema | **Resolved 2026-09-27 (PRD §8 OQ-2, Assumptions A7).** Minimum schema locked at `_bmad-output/contracts/test-report.schema.json`. | ✅ Yes — see `addendum.md §A6` for schema source-of-truth. Spec step elaborates, does not redesign. | PM (closed) |
| D3 | Herdr v1 scope (observe-only vs. lifecycle) | PRD picks observe-only (§4.8 FR-28). **Refined 2026-09-27 → external observability (Assumptions A6).** | ✅ Yes — Herdr is now an out-of-process advisory event stream; stance (a) adopted under OQ-8. | PM (closed) |
| D4 | BMAD Skill version pin policy | PRD picks pin + regression gate (§4.2 FR-6, §4.6 FR-22). | Tentative — confirm during architecture review. | architect |
| D5 | Human Gate acceptance shape | **Resolved 2026-09-27 (PRD §8 OQ-5, Assumptions A8).** Independent approval record at `acknowledgements/<step>-<artifact-hash-prefix>.json`. | ✅ Yes — schema source-of-truth at `_bmad-output/contracts/acknowledgement-record.schema.json`. Architecture owns signature scheme + retention policy (non-blocker). | PM (closed) |
| D6 | Dynamic Agent/LLM router (v2) | Out of MVP (PRD §6.2). | Yes — deferred to v2. | PM |

**Phase-blockers lifted (2026-09-27):** OQ-8 (harness-direct invocation path), OQ-2 (test-report.json schema), OQ-5 / D5 (Gate acceptance shape) are all resolved at the PRD level. `bmad-architecture` and `bmad-spec` no longer wait on these.

---

## A3. Cross-cutting quality attributes — rationale

PRD §10 carries NFRs for performance, reliability, observability, and security. The harness's value depends on these being measurable, not aspirational:

- **Performance** is bounded by the underlying executor's latency. DevFlow must not add measurable overhead to the executor invocation; the NFR is measured at the harness boundary.
- **Reliability** of artifacts (NFR-Reliab-1) is what makes the audit story in UJ-3 work. If a locked artifact can be silently mutated, the audit answer becomes fiction.
- **Observability** (NFR-Obs-1, NFR-Obs-2) is the source of all benchmark data; without structured run events and Acknowledgement records, FR-20 (regression set) cannot be populated.
- **Security** (NFR-Sec-1, NFR-Sec-2) prevents artifact / Acknowledgement spoofing. The brief does not name a security threat model in v1; the architecture step should produce one.

---

## A4. Constraints & Guardrails — rationale

PRD §11 covers cost, privacy, and safety. Cost: v1 is single-org, so per-tenant accounting is out — telemetry is logged for v2 readiness. Privacy: Herdr event payloads (FR-29) explicitly do not include prompt bodies, to keep prompt contents inside the Agent's own store. Safety: no silent auto-advance — every Gate requires an Acknowledgement.

---

## A5. Size tier Gate strictness — concrete behavior

From brief addendum §4 and PRD FR-12. Concrete behavior table for the architecture step:

| Tier | Research | Design | Coding | Testing | Review | Delivery |
|------|----------|--------|--------|---------|--------|----------|
| `trivial` | default Done | default Done | default Done | default Done | default Done | default Done |
| `session` | default Done | light Gate | default Done | default Done | default Done | default Done |
| `epic` | Gate | Gate | Gate + sub-Gates on key stories + human-first for first N | Gate | Gate | Gate |
| `project` | Gate | Gate | Gate + sub-Gates on key stories | Gate | Gate | Gate + benchmark |

The exact "light Gate" semantics on `session` are deferred to `bmad-spec` (D5 territory).

---

## A6. Step ↔ BMAD skill ownership — proposed

From PRD FR-3 (notes) and brief addendum §3. Proposed ownership, awaiting architecture confirmation:

| Step | Proposed owning BMAD skill | Output contract |
|------|----------------------------|-----------------|
| research | `bmad-deep-recon` | `research.md` (cited findings + recommendation) |
| design | `bmad-prd` → `bmad-architecture` → `bmad-spec` | `prd.md` + `ARCHITECTURE-SPINE.md` + `SPEC.md` |
| coding | `bmad-preview-ticketing` + `bmad-build` | tickets + code commits + change-log |
| testing | (no BMAD skill; project-defined `testing@n`) | `test-report.json` — schema source-of-truth: `_bmad-output/contracts/test-report.schema.json` (PRD A7, 2026-09-27) |
| review | `bmad-retrospective` + `bmad-code-review` | `review.md` + retro doc |
| delivery | (no BMAD skill; harness-native) | `delivery.json` (signed) |

**Gate Acknowledgement record** (every step's Gate, not just testing/review): schema source-of-truth `_bmad-output/contracts/acknowledgement-record.schema.json` (PRD A8, 2026-09-27). D2 and D5 are closed at the PRD level; spec step elaborates fields, architecture owns signature scheme + retention policy.

---

## A7. Files produced this run

- `prd.md` — PRD with FR-1 … FR-29, glossary-first, 6 UJs, 13 NFRs (added NFR-Reliab-3 regression-set health floor, NFR-Cost-1 + NFR-Cost-2 cost story in this Finalize pass), 8 OQs (added OQ-8 Herdr/harness execution decoupling in this Finalize pass).
- `addendum.md` — this file.
- `.memlog.md` — append-only run memory.

---

## A8. Recommended next-downstream steps (unchanged from brief addendum §9)

1. **`bmad-architecture`** in a fresh context — close D1 (router location), D4 (Skill pin confirm), OQ-6 (v1 1–2 agent adapters), OQ-7 (step↔BMAD-skill ownership). Take this PRD + brief + addendum as input. Produce `ARCHITECTURE-SPINE.md` defining the `ExecutorAdapter` interface (PRD A6) and the Gate acknowledgement storage layout (PRD A8).
2. **`bmad-spec`** — force the 5 goals (now FRs) into measurable acceptance. `test-report.json` schema is already locked (PRD A7); spec elaborates per-case evidence and acceptance-coverage semantics without redesigning the schema. Gate acknowledgement record schema is already locked (PRD A8); spec elaborates the per-tier Gate policy.
3. **`bmad-preview-ticketing`** once SPEC is approved.
4. **`bmad-build`** for the first M=2 stories, then `bmad-build-auto` for the rest.

---

## A9. Reviewer-driven changes (Finalize pass, 2026-09-26T22:18)

Two reviewer agents (rubric walker + adversarial) ran against the draft PRD before finalization. Three findings had already been resolved by earlier same-session edits that the reviewers did not see (FR-39 → FR-15 cross-ref, FR-15 rung-4 vs FR-6/FR-23, FR-10 vs FR-12 trivial/session verdict gap). Five findings drove live changes in this Finalize pass:

| # | Finding (source, severity) | Resolution |
|---|----------------------------|-----------|
| 1 | **NFR-Perf-1 theater** (adversarial, HIGH) — `≤10× executor first-token latency` is unmeasurable. | **Replaced.** NFR-Perf-1 now states harness-measured step-launch overhead: p50 ≤ 2s, p95 ≤ 5s. Old comparator rescinded. |
| 2 | **Cost story is "telemetry logged" with no budget, against a design that compounds LLM spend** (adversarial, CRITICAL). | **Added NFR-Cost-2.** Per-tier ceilings (`trivial`/`session`/`epic`/`project` defaults), `cost_overrun_ack` pause behavior, 3× ceiling for Skill-bump regression passes, configurable per project YAML. NFR-Cost-1 updated to surface per-run totals on FR-24 dashboard. |
| 3 | **Benchmark thesis unstable — regression set evaporates with LLM/agent churn** (adversarial, CRITICAL). | **Added NFR-Reliab-3.** `bench <step>` refuses to recommend below K=3 comparable runs per `step × project-size-tier` cell (returns `regression_set_insufficient`). `regression_set_remove` requires written justification recorded as an audit event. |
| 4 | **"Harness has its own executor invocation path" asserted, never defined** (adversarial, HIGH). | **Flagged, not resolved.** FR-28 consequence softened to point at OQ-8. OQ-8 added as a phase-blocker for `bmad-architecture` with both mutually exclusive stances spelled out. |
| 5 | **3 UJs = 1 persona** (adversarial, HIGH — persona theater). | **Deferred.** The PRD §2.3 already opts into "Heavier" scope and the three UJs map to three distinct capability clusters (full-pipeline run / mid-run swap / post-hoc audit) feeding architecture. Noted in `review-adversarial.md` for the architecture consumer to either accept or compress. |

Mechanical: §10 NFR count updated from 8 → 13; §8 OQ count updated from 7 → 8. Glossary term `Done` already added in earlier edit. Live PRD matches this addendum.

Smaller adversarial notes — deferred to architecture/spec (not blockers for PRD finalization):

- **Trivial/six-step contradiction** — already resolved in FR-12 live edit (`Done` semantics with `gate_mode: skipped`, Glossary §3).
- **Mid-project executor swap auth / threat model** — defer to `bmad-architecture` (PRD §11 addendum acknowledges "the architecture step should produce one").
- **FR-21 metric gaming** — SM-C1 already names the disease (raw success rate rejected as primary metric). Metric-definition rules belong in `bmad-spec`.
- **`regression_set_remove` deletes audit** — covered by NFR-Reliab-3 above (justification required).
- **Rung-5 (human) UX surface** — defer to `bmad-ux`.